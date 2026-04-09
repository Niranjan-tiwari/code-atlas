"""
Tests for the Workflow Engine and built-in workflows.

Covers:
  - Placeholder resolution ({user.x}, {step_id.key})
  - Condition evaluation
  - Step execution with mock tools
  - Error handling (abort vs continue)
  - Built-in workflow definitions
  - Custom inline workflows
"""

import pytest
from unittest.mock import MagicMock, patch

from src.workflows.engine import (
    WorkflowEngine,
    WorkflowStep,
    WorkflowResult,
    StepResult,
    _resolve_value,
    _resolve_params,
    _eval_condition,
    register_tool,
    _TOOL_REGISTRY,
)
from src.workflows.builtin import (
    BUILTIN_WORKFLOWS,
    list_workflows,
    get_workflow,
)


# ============================================================
# Placeholder Resolution
# ============================================================

class TestResolveValue:

    def test_simple_user_param(self):
        ctx = {"user": {"repo": "my-repo"}}
        assert _resolve_value("{user.repo}", ctx) == "my-repo"

    def test_nested_lookup(self):
        ctx = {"impact": {"summary": {"total_affected_repos": 5}}}
        result = _resolve_value("{impact.summary.total_affected_repos}", ctx)
        assert result == 5

    def test_non_string_passthrough(self):
        assert _resolve_value(42, {}) == 42
        assert _resolve_value(True, {}) is True
        assert _resolve_value(None, {}) is None

    def test_missing_key_returns_empty(self):
        ctx = {"user": {}}
        assert _resolve_value("{user.missing}", ctx) == ""

    def test_dict_returned_for_single_placeholder(self):
        ctx = {"step1": {"data": {"a": 1, "b": 2}}}
        result = _resolve_value("{step1.data}", ctx)
        assert isinstance(result, dict)
        assert result == {"a": 1, "b": 2}

    def test_embedded_placeholder_stringified(self):
        ctx = {"user": {"repo": "my-repo"}}
        result = _resolve_value("Repo: {user.repo} done", ctx)
        assert result == "Repo: my-repo done"

    def test_multiple_placeholders(self):
        ctx = {"user": {"a": "hello", "b": "world"}}
        result = _resolve_value("{user.a} {user.b}", ctx)
        assert result == "hello world"

    def test_plain_string_unchanged(self):
        assert _resolve_value("no placeholders", {}) == "no placeholders"


class TestResolveParams:

    def test_dict_params(self):
        ctx = {"user": {"x": "val"}}
        result = _resolve_params({"key": "{user.x}", "static": "abc"}, ctx)
        assert result == {"key": "val", "static": "abc"}

    def test_nested_dict(self):
        ctx = {"user": {"repo": "r"}}
        result = _resolve_params({"outer": {"inner": "{user.repo}"}}, ctx)
        assert result == {"outer": {"inner": "r"}}

    def test_list_params(self):
        ctx = {"user": {"a": "1", "b": "2"}}
        result = _resolve_params({"items": ["{user.a}", "{user.b}"]}, ctx)
        assert result == {"items": ["1", "2"]}


# ============================================================
# Condition Evaluation
# ============================================================

class TestEvalCondition:

    def test_none_is_true(self):
        assert _eval_condition(None, {}) is True

    def test_empty_string_is_true(self):
        assert _eval_condition("", {}) is True

    def test_truthy_value(self):
        ctx = {"user": {"repo": "my-repo"}}
        assert _eval_condition("{user.repo}", ctx) is True

    def test_falsy_value(self):
        ctx = {"user": {"repo": ""}}
        assert _eval_condition("{user.repo}", ctx) is False

    def test_invalid_condition_defaults_true(self):
        assert _eval_condition("!!invalid!!", {}) is True


# ============================================================
# Engine with Mock Tools
# ============================================================

def _mock_retriever():
    r = MagicMock()
    r._unified = MagicMock()
    r._collections = {}
    r.search_code = MagicMock(return_value=[])
    return r


class TestWorkflowEngine:

    def setup_method(self):
        _TOOL_REGISTRY.clear()

    def test_simple_two_step_workflow(self):
        register_tool("step_a", lambda params, ret: {"result": f"a-{params.get('x', '')}"})
        register_tool("step_b", lambda params, ret: {"result": f"b-{params.get('y', '')}"})

        engine = WorkflowEngine.__new__(WorkflowEngine)
        engine.retriever = None

        steps = [
            WorkflowStep(id="a", tool="step_a", params={"x": "hello"}),
            WorkflowStep(id="b", tool="step_b", params={"y": "world"}),
        ]
        result = engine.run("test", steps, {})

        assert result.status == "completed"
        assert len(result.steps) == 2
        assert result.steps[0].status == "success"
        assert result.steps[0].output["result"] == "a-hello"
        assert result.steps[1].output["result"] == "b-world"

    def test_context_passing_between_steps(self):
        register_tool("produce", lambda p, r: {"value": 42})
        register_tool("consume", lambda p, r: {"got": p.get("input")})

        engine = WorkflowEngine.__new__(WorkflowEngine)
        engine.retriever = None

        steps = [
            WorkflowStep(id="s1", tool="produce", params={}),
            WorkflowStep(id="s2", tool="consume", params={"input": "{s1.value}"}),
        ]
        result = engine.run("test", steps, {})

        assert result.steps[1].output["got"] == 42

    def test_user_params_accessible(self):
        register_tool("echo", lambda p, r: {"echo": p.get("msg")})

        engine = WorkflowEngine.__new__(WorkflowEngine)
        engine.retriever = None

        steps = [
            WorkflowStep(id="s1", tool="echo", params={"msg": "{user.name}"}),
        ]
        result = engine.run("test", steps, {"name": "TestUser"})

        assert result.steps[0].output["echo"] == "TestUser"

    def test_condition_skip(self):
        register_tool("tool", lambda p, r: {"ok": True})

        engine = WorkflowEngine.__new__(WorkflowEngine)
        engine.retriever = None

        steps = [
            WorkflowStep(id="s1", tool="tool", params={}, condition="{user.run_this}"),
        ]
        result = engine.run("test", steps, {"run_this": ""})

        assert result.steps[0].status == "skipped"

    def test_condition_run(self):
        register_tool("tool", lambda p, r: {"ok": True})

        engine = WorkflowEngine.__new__(WorkflowEngine)
        engine.retriever = None

        steps = [
            WorkflowStep(id="s1", tool="tool", params={}, condition="{user.run_this}"),
        ]
        result = engine.run("test", steps, {"run_this": "yes"})

        assert result.steps[0].status == "success"

    def test_error_continue(self):
        register_tool("fail", lambda p, r: (_ for _ in ()).throw(ValueError("boom")))
        register_tool("ok", lambda p, r: {"fine": True})

        engine = WorkflowEngine.__new__(WorkflowEngine)
        engine.retriever = None

        steps = [
            WorkflowStep(id="s1", tool="fail", params={}, on_error="continue"),
            WorkflowStep(id="s2", tool="ok", params={}),
        ]
        result = engine.run("test", steps, {})

        assert result.status == "completed"
        assert result.steps[0].status == "error"
        assert "boom" in result.steps[0].error
        assert result.steps[1].status == "success"

    def test_error_abort(self):
        register_tool("fail", lambda p, r: (_ for _ in ()).throw(RuntimeError("fatal")))
        register_tool("ok", lambda p, r: {"fine": True})

        engine = WorkflowEngine.__new__(WorkflowEngine)
        engine.retriever = None

        steps = [
            WorkflowStep(id="s1", tool="fail", params={}, on_error="abort"),
            WorkflowStep(id="s2", tool="ok", params={}),
        ]
        result = engine.run("test", steps, {})

        assert result.status == "aborted"
        assert len(result.steps) == 1

    def test_unknown_tool(self):
        engine = WorkflowEngine.__new__(WorkflowEngine)
        engine.retriever = None

        steps = [
            WorkflowStep(id="s1", tool="nonexistent", params={}),
        ]
        result = engine.run("test", steps, {})

        assert result.steps[0].status == "error"
        assert "Unknown tool" in result.steps[0].error

    def test_summary_counts(self):
        register_tool("ok", lambda p, r: {"x": 1})
        register_tool("fail", lambda p, r: (_ for _ in ()).throw(ValueError("err")))

        engine = WorkflowEngine.__new__(WorkflowEngine)
        engine.retriever = None

        steps = [
            WorkflowStep(id="s1", tool="ok", params={}),
            WorkflowStep(id="s2", tool="fail", params={}, on_error="continue"),
            WorkflowStep(id="s3", tool="ok", params={}, condition=""),
        ]
        result = engine.run("test", steps, {})

        assert result.summary["succeeded"] == 2
        assert result.summary["failed"] == 1
        assert result.summary["total_steps"] == 3

    def test_to_dict(self):
        register_tool("ok", lambda p, r: {"x": 1})

        engine = WorkflowEngine.__new__(WorkflowEngine)
        engine.retriever = None

        steps = [WorkflowStep(id="s1", tool="ok", params={})]
        result = engine.run("test", steps, {})

        d = result.to_dict()
        assert d["workflow"] == "test"
        assert d["status"] == "completed"
        assert isinstance(d["steps"], list)
        assert d["steps"][0]["step_id"] == "s1"
        assert "time_ms" in d


# ============================================================
# Built-in Workflows
# ============================================================

class TestBuiltinWorkflows:

    def test_all_workflows_have_required_fields(self):
        for name, wf in BUILTIN_WORKFLOWS.items():
            assert "name" in wf, f"{name} missing 'name'"
            assert "description" in wf, f"{name} missing 'description'"
            assert "required" in wf, f"{name} missing 'required'"
            assert "steps" in wf, f"{name} missing 'steps'"
            assert len(wf["steps"]) > 0, f"{name} has no steps"

    def test_all_steps_have_id_and_tool(self):
        for name, wf in BUILTIN_WORKFLOWS.items():
            for step in wf["steps"]:
                assert hasattr(step, "id"), f"{name} step missing 'id'"
                assert hasattr(step, "tool"), f"{name} step missing 'tool'"
                assert step.id, f"{name} has step with empty id"
                assert step.tool, f"{name} has step with empty tool"

    def test_step_ids_unique_per_workflow(self):
        for name, wf in BUILTIN_WORKFLOWS.items():
            ids = [s.id for s in wf["steps"]]
            assert len(ids) == len(set(ids)), f"{name} has duplicate step IDs"

    def test_list_workflows(self):
        wfs = list_workflows()
        assert len(wfs) >= 6
        names = {w["name"] for w in wfs}
        assert "pre_mr_review" in names
        assert "safe_refactor" in names
        assert "incident_response" in names
        assert "onboarding" in names
        assert "code_health" in names
        assert "migration" in names

    def test_get_workflow(self):
        wf = get_workflow("pre_mr_review")
        assert wf is not None
        assert wf["name"] == "pre_mr_review"

    def test_get_workflow_not_found(self):
        assert get_workflow("nonexistent") is None

    def test_pre_mr_review_steps(self):
        wf = get_workflow("pre_mr_review")
        tools = [s.tool for s in wf["steps"]]
        assert "diff_impact" in tools
        assert "pr_review" in tools

    def test_incident_response_steps(self):
        wf = get_workflow("incident_response")
        tools = [s.tool for s in wf["steps"]]
        assert "debug_error" in tools
        assert "search" in tools
        assert "explain" in tools

    def test_onboarding_steps(self):
        wf = get_workflow("onboarding")
        tools = [s.tool for s in wf["steps"]]
        assert "explain" in tools
        assert "generate_docs" in tools

    def test_code_health_steps(self):
        wf = get_workflow("code_health")
        tools = [s.tool for s in wf["steps"]]
        assert "find_duplicates" in tools
        assert "generate_tests" in tools

    def test_safe_refactor_steps(self):
        wf = get_workflow("safe_refactor")
        tools = [s.tool for s in wf["steps"]]
        assert "impact_analysis" in tools
        assert "refactor" in tools

    def test_migration_steps(self):
        wf = get_workflow("migration")
        tools = [s.tool for s in wf["steps"]]
        assert "search" in tools
        assert "impact_analysis" in tools
        assert "migrate" in tools


# ============================================================
# Lazy Tool Registration
# ============================================================

class TestLazyToolRegistration:

    def setup_method(self):
        _TOOL_REGISTRY.clear()

    def test_lazy_registers_all_tools(self):
        from src.workflows.engine import _lazy_register_all
        _lazy_register_all(MagicMock())
        expected = [
            "impact_analysis", "diff_impact", "pr_review",
            "find_duplicates", "dependency_scan", "explain",
            "generate_docs", "generate_tests", "debug_error",
            "refactor", "migrate", "reindex", "search",
        ]
        for name in expected:
            assert name in _TOOL_REGISTRY, f"Tool '{name}' not registered"

    def test_lazy_registers_only_once(self):
        from src.workflows.engine import _lazy_register_all
        _lazy_register_all(MagicMock())
        count = len(_TOOL_REGISTRY)
        _lazy_register_all(MagicMock())
        assert len(_TOOL_REGISTRY) == count
