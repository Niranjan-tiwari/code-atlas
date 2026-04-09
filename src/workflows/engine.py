"""
Workflow Engine — run multi-step tool pipelines with context passing.

A workflow is a list of WorkflowStep objects.  Each step:
  1. Runs a registered tool function
  2. Stores its output in a shared context dict  (context[step.id] = result)
  3. Can reference previous step outputs via {step_id.key} placeholders

Example:
    steps = [
        WorkflowStep(id="impact", tool="impact_analysis", params={"symbol": "Foo"}),
        WorkflowStep(id="review", tool="pr_review",
                     params={"diff": "{user.diff}", "repo": "{user.repo}"}),
    ]
    engine = WorkflowEngine(retriever)
    result = engine.run("my_workflow", steps, user_params={"diff": "...", "repo": "x"})
"""

import copy
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("workflow_engine")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class WorkflowStep:
    """Single step in a workflow pipeline."""
    id: str                         # unique key, used to reference output
    tool: str                       # registered tool name
    params: Dict[str, Any]          # parameters (may contain {ref} placeholders)
    label: str = ""                 # human-readable label
    condition: Optional[str] = None # skip step when condition evals false
    on_error: str = "continue"      # "continue" | "abort"


@dataclass
class StepResult:
    """Result of a single step execution."""
    step_id: str
    tool: str
    label: str
    status: str             # "success" | "skipped" | "error"
    output: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    time_ms: int = 0


@dataclass
class WorkflowResult:
    """Result of a complete workflow run."""
    workflow: str
    status: str                         # "completed" | "aborted" | "error"
    steps: List[StepResult] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
    time_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "workflow": self.workflow,
            "status": self.status,
            "steps": [
                {
                    "step_id": s.step_id,
                    "tool": s.tool,
                    "label": s.label,
                    "status": s.status,
                    "output": s.output,
                    "error": s.error,
                    "time_ms": s.time_ms,
                }
                for s in self.steps
            ],
            "summary": self.summary,
            "time_ms": self.time_ms,
        }


# ---------------------------------------------------------------------------
# Tool registry — maps tool names to callables
# ---------------------------------------------------------------------------

_TOOL_REGISTRY: Dict[str, Callable] = {}


def register_tool(name: str, fn: Callable):
    """Register a tool function by name."""
    _TOOL_REGISTRY[name] = fn


def _lazy_register_all(retriever):
    """
    Lazily import and register every tool the first time the engine runs.
    Each registered function has a uniform signature:
        fn(params: dict, retriever) -> dict
    """
    if _TOOL_REGISTRY:
        return

    # --- impact analysis ---
    def _impact(params, ret):
        from src.tools.impact_analyzer import analyze_impact
        return analyze_impact(
            ret,
            symbol=params.get("symbol", ""),
            repo_filter=params.get("repo"),
            max_results=int(params.get("max_results", 50)),
        )
    register_tool("impact_analysis", _impact)

    # --- diff impact ---
    def _diff_impact(params, ret):
        from src.tools.impact_analyzer import analyze_diff_impact
        return analyze_diff_impact(
            ret,
            diff_text=params.get("diff", ""),
            repo_name=params.get("repo"),
            max_results=int(params.get("max_results", 50)),
        )
    register_tool("diff_impact", _diff_impact)

    # --- PR review ---
    def _review(params, ret):
        from src.tools.pr_reviewer import review_diff
        return review_diff(
            ret,
            diff_text=params.get("diff", ""),
            repo_name=params.get("repo", ""),
            max_context=int(params.get("max_context", 5)),
        )
    register_tool("pr_review", _review)

    # --- duplicates ---
    def _dupes(params, ret):
        from src.tools.duplication_finder import find_duplicates
        return find_duplicates(
            ret,
            repo_filter=params.get("repo"),
            threshold=float(params.get("threshold", 0.15)),
            max_results=int(params.get("max_results", 20)),
        )
    register_tool("find_duplicates", _dupes)

    # --- dependency scan ---
    def _deps(params, _ret):
        from src.tools.dependency_scanner import scan_all, scan_repo
        repo_path = params.get("repo_path")
        if repo_path:
            return scan_repo(repo_path)
        return scan_all(params.get("base_path"))
    register_tool("dependency_scan", _deps)

    # --- explain ---
    def _explain(params, ret):
        from src.tools.repo_explainer import explain
        return explain(
            ret,
            question=params.get("question", params.get("query", "")),
            repo_filter=params.get("repo"),
            n_context=int(params.get("n_context", 15)),
            include_diagram=params.get("diagram", False),
        )
    register_tool("explain", _explain)

    # --- doc generation ---
    def _docs(params, ret):
        from src.tools.doc_generator import generate_docs
        return generate_docs(ret, params.get("repo", ""))
    register_tool("generate_docs", _docs)

    # --- test generation ---
    def _tests(params, ret):
        from src.tools.test_generator import generate_tests
        return generate_tests(
            ret,
            repo_name=params.get("repo", ""),
            file_path=params.get("file", ""),
        )
    register_tool("generate_tests", _tests)

    # --- incident debug ---
    def _debug(params, ret):
        from src.tools.incident_debugger import debug_error
        return debug_error(ret, params.get("error", ""))
    register_tool("debug_error", _debug)

    # --- refactoring ---
    def _refactor(params, _ret):
        from src.tools.refactoring_engine import run_refactor
        return run_refactor(params)
    register_tool("refactor", _refactor)

    # --- migration ---
    def _migrate(params, _ret):
        from src.tools.migration_automator import run_migration
        return run_migration(params)
    register_tool("migrate", _migrate)

    # --- reindex ---
    def _reindex(params, _ret):
        from src.tools.auto_reindexer import reindex_repo
        return reindex_repo(
            params.get("repo_path", ""),
            vector_db_path=params.get("vector_db_path", "./data/qdrant_db"),
        )
    register_tool("reindex", _reindex)

    # --- code search (raw RAG) ---
    def _search(params, ret):
        results = ret.search_code(
            params.get("query", ""),
            n_results=int(params.get("n_results", 10)),
            repo_filter=params.get("repo"),
            language_filter=params.get("language"),
        )
        return {
            "query": params.get("query", ""),
            "results": [
                {"repo": r["repo"], "file": r["file"],
                 "language": r.get("language", "?"),
                 "score": round(r.get("hybrid_score", 0), 4),
                 "code_preview": r.get("code", "")[:200]}
                for r in results
            ],
            "count": len(results),
        }
    register_tool("search", _search)


# ---------------------------------------------------------------------------
# Placeholder resolution
# ---------------------------------------------------------------------------

_PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_.]*)\}")


def _resolve_value(value: Any, context: Dict[str, Any]) -> Any:
    """
    Resolve {step_id.key} placeholders in a value.

    Supports:
      {user.repo}           -> context["user"]["repo"]
      {impact.summary}      -> context["impact"]["summary"]
      {user.symbol}         -> context["user"]["symbol"]
      plain strings         -> returned as-is
      non-strings           -> returned as-is
    """
    if not isinstance(value, str):
        return value

    def _lookup(match):
        path = match.group(1).split(".")
        obj = context
        for part in path:
            if isinstance(obj, dict):
                obj = obj.get(part, "")
            else:
                return match.group(0)  # can't resolve, keep placeholder
        if isinstance(obj, (dict, list)):
            return str(obj)  # stringify complex types in string context
        return str(obj) if obj is not None else ""

    # If the entire value is a single placeholder, return the raw object
    # (preserves dicts/lists instead of stringifying them)
    single = _PLACEHOLDER.fullmatch(value)
    if single:
        path = single.group(1).split(".")
        obj = context
        for part in path:
            if isinstance(obj, dict):
                obj = obj.get(part, "")
            else:
                return value
        return obj

    return _PLACEHOLDER.sub(_lookup, value)


def _resolve_params(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve all placeholders in a params dict."""
    resolved = {}
    for k, v in params.items():
        if isinstance(v, dict):
            resolved[k] = _resolve_params(v, context)
        elif isinstance(v, list):
            resolved[k] = [_resolve_value(item, context) for item in v]
        else:
            resolved[k] = _resolve_value(v, context)
    return resolved


# ---------------------------------------------------------------------------
# Condition evaluation
# ---------------------------------------------------------------------------

def _eval_condition(condition: Optional[str], context: Dict[str, Any]) -> bool:
    """
    Evaluate a simple condition string against the context.

    Supported:
      "impact.summary.total_affected_repos > 0"
      "review.issue_count > 0"
      None / "" -> True (no condition = always run)
    """
    if not condition:
        return True
    try:
        resolved = _PLACEHOLDER.sub(
            lambda m: repr(_resolve_value(m.group(0), context)),
            condition,
        )
        return bool(eval(resolved, {"__builtins__": {}}, {}))  # noqa: S307
    except Exception as exc:
        logger.warning(f"Condition eval failed: {condition!r} -> {exc}")
        return True  # default to running step


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class WorkflowEngine:
    """
    Executes a workflow (list of steps) with shared context.

    Usage:
        engine = WorkflowEngine(retriever)
        result = engine.run("pre_mr_review", steps, user_params={...})
    """

    def __init__(self, retriever=None):
        self.retriever = retriever
        _lazy_register_all(retriever)

    def run(
        self,
        workflow_name: str,
        steps: List[WorkflowStep],
        user_params: Optional[Dict[str, Any]] = None,
    ) -> WorkflowResult:
        """Execute a workflow and return results."""
        t0 = time.time()
        context: Dict[str, Any] = {"user": user_params or {}}
        step_results: List[StepResult] = []

        logger.info(f"Starting workflow: {workflow_name} ({len(steps)} steps)")

        for i, step in enumerate(steps, 1):
            step_t0 = time.time()
            label = step.label or f"{step.tool} ({step.id})"
            logger.info(f"  Step {i}/{len(steps)}: {label}")

            # Condition check
            if not _eval_condition(step.condition, context):
                sr = StepResult(
                    step_id=step.id, tool=step.tool, label=label,
                    status="skipped", time_ms=0,
                )
                step_results.append(sr)
                logger.info(f"    -> Skipped (condition: {step.condition})")
                continue

            # Resolve parameters
            resolved = _resolve_params(step.params, context)

            # Execute
            tool_fn = _TOOL_REGISTRY.get(step.tool)
            if not tool_fn:
                sr = StepResult(
                    step_id=step.id, tool=step.tool, label=label,
                    status="error", error=f"Unknown tool: {step.tool}",
                    time_ms=round((time.time() - step_t0) * 1000),
                )
                step_results.append(sr)
                if step.on_error == "abort":
                    return WorkflowResult(
                        workflow=workflow_name, status="aborted",
                        steps=step_results,
                        time_ms=round((time.time() - t0) * 1000),
                    )
                continue

            try:
                output = tool_fn(resolved, self.retriever)
                if not isinstance(output, dict):
                    output = {"result": output}
                context[step.id] = output
                elapsed = round((time.time() - step_t0) * 1000)
                sr = StepResult(
                    step_id=step.id, tool=step.tool, label=label,
                    status="success", output=output, time_ms=elapsed,
                )
                step_results.append(sr)
                logger.info(f"    -> OK ({elapsed}ms)")
            except Exception as exc:
                elapsed = round((time.time() - step_t0) * 1000)
                error_msg = f"{type(exc).__name__}: {exc}"
                logger.error(f"    -> FAILED: {error_msg}")
                context[step.id] = {"error": error_msg}
                sr = StepResult(
                    step_id=step.id, tool=step.tool, label=label,
                    status="error", error=error_msg, time_ms=elapsed,
                )
                step_results.append(sr)
                if step.on_error == "abort":
                    return WorkflowResult(
                        workflow=workflow_name, status="aborted",
                        steps=step_results,
                        time_ms=round((time.time() - t0) * 1000),
                    )

        total_ms = round((time.time() - t0) * 1000)
        succeeded = sum(1 for s in step_results if s.status == "success")
        failed = sum(1 for s in step_results if s.status == "error")
        skipped = sum(1 for s in step_results if s.status == "skipped")

        summary = {
            "total_steps": len(steps),
            "succeeded": succeeded,
            "failed": failed,
            "skipped": skipped,
        }

        # Pull key insights from step outputs
        for sr in step_results:
            if sr.status != "success":
                continue
            out = sr.output
            if sr.tool == "impact_analysis" and "summary" in out:
                summary["impact"] = {
                    "affected_repos": out["summary"].get("total_affected_repos", 0),
                    "affected_files": out["summary"].get("total_affected_files", 0),
                }
            elif sr.tool == "pr_review":
                summary["review"] = {
                    "issues": out.get("issue_count", 0),
                    "approval": out.get("approval", "unknown"),
                }
            elif sr.tool == "find_duplicates":
                summary["duplicates"] = out.get("count", 0)
            elif sr.tool == "generate_tests":
                summary["tests"] = {
                    "untested": out.get("total_functions", 0) - out.get("tested_functions", 0),
                    "generated": len(out.get("generated_stubs", [])),
                }
            elif sr.tool == "debug_error":
                summary["debug"] = {
                    "suggestions": len(out.get("suggestions", [])),
                    "related_code": len(out.get("relevant_code", [])),
                }

        return WorkflowResult(
            workflow=workflow_name, status="completed",
            steps=step_results, summary=summary,
            time_ms=total_ms,
        )

    def get_tools(self) -> List[str]:
        """Return registered tool names."""
        return sorted(_TOOL_REGISTRY.keys())
