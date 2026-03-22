"""
RAG Pipeline Monitoring & Feedback Collection

Production monitoring for RAG system:
1. Query Performance: latency (p50/p95/p99), throughput, error rates
2. Retrieval Quality: result count, score distributions, cache hit rates
3. User Feedback: thumbs up/down, click-through, query reformulation
4. Cost Tracking: token usage, API calls, model costs
5. Quality Drift: score degradation over time

Exports metrics in Prometheus-compatible format and provides
a feedback API for user satisfaction tracking.
"""

import logging
import time
import threading
import statistics
import json
import os
from typing import Dict, List, Optional, Any, Tuple
from collections import deque, defaultdict
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from functools import wraps

logger = logging.getLogger("rag_monitoring")

# Feedback storage file
FEEDBACK_FILE = "data/user_feedback.jsonl"
METRICS_FILE = "data/rag_metrics.json"


@dataclass
class QueryMetric:
    """Metrics for a single query"""
    query: str
    timestamp: str
    total_latency_ms: float
    stage_latencies: Dict[str, float] = field(default_factory=dict)
    result_count: int = 0
    cache_hit: bool = False
    error: Optional[str] = None
    
    # Score distributions
    top_score: float = 0.0
    avg_score: float = 0.0
    
    # Pipeline config
    use_hyde: bool = False
    use_hybrid: bool = False
    use_reranking: bool = False
    use_graphrag: bool = False
    
    # Cost
    tokens_used: int = 0
    api_calls: int = 0
    estimated_cost_usd: float = 0.0


@dataclass
class FeedbackEntry:
    """User feedback for a query result"""
    query: str
    result_file: str
    result_repo: str
    action: str  # "click", "thumbs_up", "thumbs_down", "skip", "reformulate"
    timestamp: str = ""
    session_id: str = ""
    original_rank: int = 0
    score: float = 0.0
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


class LatencyTracker:
    """
    Tracks latency percentiles (p50, p95, p99) for RAG stages.
    Thread-safe with sliding window.
    """
    
    def __init__(self, window_size: int = 1000):
        self._latencies: Dict[str, deque] = defaultdict(lambda: deque(maxlen=window_size))
        self._lock = threading.Lock()
    
    def record(self, stage: str, latency_ms: float):
        with self._lock:
            self._latencies[stage].append(latency_ms)
    
    def percentiles(self, stage: str) -> Dict[str, float]:
        with self._lock:
            values = list(self._latencies.get(stage, []))
        
        if not values:
            return {"p50": 0, "p95": 0, "p99": 0, "avg": 0, "count": 0}
        
        sorted_values = sorted(values)
        n = len(sorted_values)
        
        return {
            "p50": sorted_values[int(n * 0.50)] if n > 0 else 0,
            "p95": sorted_values[int(n * 0.95)] if n > 1 else sorted_values[-1],
            "p99": sorted_values[int(n * 0.99)] if n > 1 else sorted_values[-1],
            "avg": round(statistics.mean(values), 2),
            "min": round(min(values), 2),
            "max": round(max(values), 2),
            "count": n
        }
    
    def all_stages(self) -> Dict[str, Dict]:
        stages = {}
        with self._lock:
            stage_names = list(self._latencies.keys())
        for stage in stage_names:
            stages[stage] = self.percentiles(stage)
        return stages


class CostTracker:
    """Track API costs and token usage"""
    
    # Approximate costs per 1K tokens (USD)
    MODEL_COSTS = {
        "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
        "gpt-4o": {"input": 0.0025, "output": 0.01},
        "claude-3-5-sonnet": {"input": 0.003, "output": 0.015},
        "gemini-2.0-flash": {"input": 0.0001, "output": 0.0004},
        "codellama": {"input": 0.0, "output": 0.0},  # Local
        "ollama": {"input": 0.0, "output": 0.0},      # Local
    }
    
    def __init__(self):
        self._total_tokens = 0
        self._total_cost = 0.0
        self._api_calls = 0
        self._by_model: Dict[str, Dict] = defaultdict(
            lambda: {"tokens": 0, "cost": 0.0, "calls": 0}
        )
        self._lock = threading.Lock()
    
    def record(self, model: str, input_tokens: int = 0, output_tokens: int = 0):
        with self._lock:
            total_tokens = input_tokens + output_tokens
            self._total_tokens += total_tokens
            self._api_calls += 1
            
            # Estimate cost
            model_key = None
            for key in self.MODEL_COSTS:
                if key in model.lower():
                    model_key = key
                    break
            
            cost = 0.0
            if model_key:
                costs = self.MODEL_COSTS[model_key]
                cost = (input_tokens / 1000 * costs["input"]) + \
                       (output_tokens / 1000 * costs["output"])
            
            self._total_cost += cost
            self._by_model[model]["tokens"] += total_tokens
            self._by_model[model]["cost"] += cost
            self._by_model[model]["calls"] += 1
    
    def summary(self) -> Dict:
        with self._lock:
            return {
                "total_tokens": self._total_tokens,
                "total_cost_usd": round(self._total_cost, 6),
                "api_calls": self._api_calls,
                "by_model": dict(self._by_model),
                "cost_per_query": round(
                    self._total_cost / max(self._api_calls, 1), 6
                )
            }


class FeedbackCollector:
    """
    Collects and stores user feedback for search results.
    Persists to JSONL file for training data generation.
    """
    
    def __init__(self, feedback_file: str = FEEDBACK_FILE):
        self._feedback_file = feedback_file
        self._recent: deque = deque(maxlen=500)
        self._lock = threading.Lock()
        self._satisfaction_scores: deque = deque(maxlen=1000)
        
        os.makedirs(os.path.dirname(feedback_file), exist_ok=True)
    
    def record(self, feedback: FeedbackEntry):
        """Record a feedback entry"""
        with self._lock:
            self._recent.append(feedback)
            
            # Track satisfaction
            if feedback.action == "thumbs_up":
                self._satisfaction_scores.append(1.0)
            elif feedback.action == "thumbs_down":
                self._satisfaction_scores.append(0.0)
            elif feedback.action == "click":
                self._satisfaction_scores.append(0.7)
            elif feedback.action == "skip":
                self._satisfaction_scores.append(0.3)
        
        # Append to JSONL file
        try:
            with open(self._feedback_file, 'a') as f:
                f.write(json.dumps(asdict(feedback), default=str) + '\n')
        except Exception as e:
            logger.warning(f"Could not save feedback: {e}")
    
    def get_satisfaction_score(self) -> float:
        """Get CSAT (Customer Satisfaction) score (0-1)"""
        with self._lock:
            scores = list(self._satisfaction_scores)
        if not scores:
            return 0.0
        return round(statistics.mean(scores), 4)
    
    def get_recent(self, limit: int = 50) -> List[Dict]:
        with self._lock:
            return [asdict(f) for f in list(self._recent)[-limit:]]
    
    def summary(self) -> Dict:
        with self._lock:
            recent = list(self._recent)
        
        action_counts = defaultdict(int)
        for f in recent:
            action_counts[f.action] += 1
        
        return {
            "total_feedback": len(recent),
            "satisfaction_score": self.get_satisfaction_score(),
            "action_distribution": dict(action_counts)
        }


class QualityDriftDetector:
    """
    Detect quality degradation over time.
    Compares recent score distributions against baseline.
    """
    
    def __init__(self, window_size: int = 100, alert_threshold: float = 0.15):
        self._scores: deque = deque(maxlen=window_size * 2)
        self._alert_threshold = alert_threshold
        self._baseline_mean: Optional[float] = None
        self._lock = threading.Lock()
    
    def record_scores(self, scores: List[float]):
        with self._lock:
            self._scores.extend(scores)
            
            # Set baseline after collecting enough data
            all_scores = list(self._scores)
            if self._baseline_mean is None and len(all_scores) >= 50:
                self._baseline_mean = statistics.mean(all_scores)
    
    def check_drift(self) -> Dict:
        """Check if quality has drifted from baseline"""
        with self._lock:
            all_scores = list(self._scores)
        
        if len(all_scores) < 20 or self._baseline_mean is None:
            return {"drift_detected": False, "reason": "insufficient_data"}
        
        # Compare recent vs baseline
        recent = all_scores[-50:]
        recent_mean = statistics.mean(recent)
        drift = abs(recent_mean - self._baseline_mean) / max(self._baseline_mean, 0.001)
        
        return {
            "drift_detected": drift > self._alert_threshold,
            "baseline_mean": round(self._baseline_mean, 4),
            "recent_mean": round(recent_mean, 4),
            "drift_pct": round(drift * 100, 2),
            "threshold_pct": round(self._alert_threshold * 100, 2)
        }


class MetricsCollector:
    """
    Central metrics collector for the RAG pipeline.
    Aggregates all monitoring data.
    """
    
    def __init__(self):
        self.latency = LatencyTracker()
        self.costs = CostTracker()
        self.feedback = FeedbackCollector()
        self.quality_drift = QualityDriftDetector()
        
        self._query_count = 0
        self._error_count = 0
        self._cache_hits = 0
        self._cache_misses = 0
        self._recent_queries: deque = deque(maxlen=100)
        self._lock = threading.Lock()
        
        logger.info("RAG Metrics Collector initialized")
    
    def record_query(self, metric: QueryMetric):
        """Record metrics for a completed query"""
        with self._lock:
            self._query_count += 1
            if metric.error:
                self._error_count += 1
            if metric.cache_hit:
                self._cache_hits += 1
            else:
                self._cache_misses += 1
            self._recent_queries.append(asdict(metric))
        
        # Record latencies
        self.latency.record("total", metric.total_latency_ms)
        for stage, latency in metric.stage_latencies.items():
            self.latency.record(stage, latency)
        
        # Record quality scores
        if metric.top_score > 0:
            self.quality_drift.record_scores([metric.top_score])
    
    def record_feedback(self, feedback: FeedbackEntry):
        """Record user feedback"""
        self.feedback.record(feedback)
    
    def record_cost(self, model: str, input_tokens: int = 0, output_tokens: int = 0):
        """Record API cost"""
        self.costs.record(model, input_tokens, output_tokens)
    
    def get_summary(self) -> Dict:
        """Get comprehensive metrics summary"""
        with self._lock:
            total = self._cache_hits + self._cache_misses
            cache_hit_rate = self._cache_hits / max(total, 1)
        
        return {
            "queries": {
                "total": self._query_count,
                "errors": self._error_count,
                "error_rate": round(self._error_count / max(self._query_count, 1), 4),
                "cache_hit_rate": round(cache_hit_rate, 4)
            },
            "latency": self.latency.all_stages(),
            "costs": self.costs.summary(),
            "feedback": self.feedback.summary(),
            "quality_drift": self.quality_drift.check_drift(),
            "timestamp": datetime.now().isoformat()
        }
    
    def get_prometheus_metrics(self) -> str:
        """
        Export metrics in Prometheus exposition format.
        
        Use with /metrics endpoint for Prometheus scraping.
        """
        lines = []
        
        # Query metrics
        lines.append(f"# HELP rag_queries_total Total number of RAG queries")
        lines.append(f"# TYPE rag_queries_total counter")
        lines.append(f"rag_queries_total {self._query_count}")
        
        lines.append(f"# HELP rag_errors_total Total number of RAG errors")
        lines.append(f"# TYPE rag_errors_total counter")
        lines.append(f"rag_errors_total {self._error_count}")
        
        lines.append(f"# HELP rag_cache_hits_total Total cache hits")
        lines.append(f"# TYPE rag_cache_hits_total counter")
        lines.append(f"rag_cache_hits_total {self._cache_hits}")
        
        # Latency percentiles
        for stage, percs in self.latency.all_stages().items():
            safe_stage = stage.replace("-", "_")
            lines.append(f"# HELP rag_latency_{safe_stage}_ms Latency for {stage}")
            lines.append(f"# TYPE rag_latency_{safe_stage}_ms summary")
            lines.append(f'rag_latency_{safe_stage}_ms{{quantile="0.5"}} {percs["p50"]}')
            lines.append(f'rag_latency_{safe_stage}_ms{{quantile="0.95"}} {percs["p95"]}')
            lines.append(f'rag_latency_{safe_stage}_ms{{quantile="0.99"}} {percs["p99"]}')
        
        # Cost
        cost_summary = self.costs.summary()
        lines.append(f"# HELP rag_cost_usd_total Total estimated cost in USD")
        lines.append(f"# TYPE rag_cost_usd_total counter")
        lines.append(f'rag_cost_usd_total {cost_summary["total_cost_usd"]}')
        
        lines.append(f"# HELP rag_tokens_total Total tokens used")
        lines.append(f"# TYPE rag_tokens_total counter")
        lines.append(f'rag_tokens_total {cost_summary["total_tokens"]}')
        
        # Satisfaction
        satisfaction = self.feedback.get_satisfaction_score()
        lines.append(f"# HELP rag_satisfaction_score User satisfaction (0-1)")
        lines.append(f"# TYPE rag_satisfaction_score gauge")
        lines.append(f"rag_satisfaction_score {satisfaction}")
        
        return "\n".join(lines) + "\n"


def measure_stage(metrics: MetricsCollector, stage_name: str):
    """
    Decorator/context manager to measure stage latency.
    
    Usage as decorator:
        @measure_stage(metrics, "hyde")
        def expand_query(query):
            ...
    
    Usage as context manager:
        with measure_stage(metrics, "reranking"):
            results = reranker.rerank(...)
    """
    class StageMeasure:
        def __init__(self):
            self.start = None
            self.latency = 0
        
        def __enter__(self):
            self.start = time.time()
            return self
        
        def __exit__(self, *args):
            self.latency = (time.time() - self.start) * 1000
            metrics.latency.record(stage_name, self.latency)
        
        def __call__(self, func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                start = time.time()
                try:
                    result = func(*args, **kwargs)
                    return result
                finally:
                    latency = (time.time() - start) * 1000
                    metrics.latency.record(stage_name, latency)
            return wrapper
    
    return StageMeasure()


# Global metrics collector (singleton)
_global_metrics: Optional[MetricsCollector] = None
_metrics_lock = threading.Lock()


def get_metrics_collector() -> MetricsCollector:
    """Get or create the global metrics collector"""
    global _global_metrics
    with _metrics_lock:
        if _global_metrics is None:
            _global_metrics = MetricsCollector()
        return _global_metrics
