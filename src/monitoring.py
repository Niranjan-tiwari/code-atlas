"""
Monitoring and health checks
"""

import time
import logging
from typing import Dict, List
from datetime import datetime
from collections import deque


class HealthMonitor:
    """Monitor system health and metrics"""
    
    def __init__(self, max_history: int = 100):
        self.logger = logging.getLogger("health_monitor")
        self.task_history: deque = deque(maxlen=max_history)
        self.error_history: deque = deque(maxlen=max_history)
        self.start_time = time.time()
        self.metrics = {
            "tasks_completed": 0,
            "tasks_failed": 0,
            "tasks_total": 0,
            "last_task_time": None,
            "average_task_duration": 0.0
        }
    
    def record_task(self, task_id: str, status: str, duration: float):
        """Record task execution"""
        self.task_history.append({
            "task_id": task_id,
            "status": status,
            "duration": duration,
            "timestamp": datetime.now().isoformat()
        })
        
        self.metrics["tasks_total"] += 1
        if status == "completed":
            self.metrics["tasks_completed"] += 1
        elif status == "failed":
            self.metrics["tasks_failed"] += 1
        
        self.metrics["last_task_time"] = datetime.now().isoformat()
        
        # Update average duration
        if self.task_history:
            durations = [t["duration"] for t in self.task_history if "duration" in t]
            if durations:
                self.metrics["average_task_duration"] = sum(durations) / len(durations)
    
    def record_error(self, error_type: str, error_message: str):
        """Record error"""
        self.error_history.append({
            "error_type": error_type,
            "error_message": error_message,
            "timestamp": datetime.now().isoformat()
        })
    
    def get_health_status(self) -> Dict:
        """Get current health status"""
        uptime = time.time() - self.start_time
        
        # Calculate success rate
        success_rate = 0.0
        if self.metrics["tasks_total"] > 0:
            success_rate = (self.metrics["tasks_completed"] / self.metrics["tasks_total"]) * 100
        
        return {
            "status": "healthy",
            "uptime_seconds": uptime,
            "metrics": self.metrics.copy(),
            "success_rate": round(success_rate, 2),
            "recent_errors": len([e for e in self.error_history if time.time() - datetime.fromisoformat(e["timestamp"]).timestamp() < 3600])
        }
    
    def get_metrics(self) -> Dict:
        """Get detailed metrics"""
        return {
            "metrics": self.metrics.copy(),
            "task_history_count": len(self.task_history),
            "error_history_count": len(self.error_history),
            "uptime_seconds": time.time() - self.start_time
        }
