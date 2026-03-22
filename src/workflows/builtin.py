"""
Pre-built workflow definitions for common multi-tool pipelines.

Each workflow is a dict with:
  - name:        unique identifier
  - description: what it does
  - required:    user params that MUST be provided
  - optional:    user params that CAN be provided
  - steps:       list of WorkflowStep definitions
"""

from src.workflows.engine import WorkflowStep


# ===================================================================
# 1. Pre-MR Review  —  "Before I merge, what breaks?"
# ===================================================================

PRE_MR_REVIEW = {
    "name": "pre_mr_review",
    "description": (
        "Full pre-merge review pipeline: analyse the diff for changed symbols, "
        "run cross-repo impact analysis, static + AI code review, and suggest "
        "missing tests."
    ),
    "required": ["diff"],
    "optional": ["repo"],
    "steps": [
        WorkflowStep(
            id="diff_impact",
            tool="diff_impact",
            params={"diff": "{user.diff}", "repo": "{user.repo}"},
            label="Analyse changed symbols & cross-repo impact",
            on_error="continue",
        ),
        WorkflowStep(
            id="review",
            tool="pr_review",
            params={"diff": "{user.diff}", "repo": "{user.repo}"},
            label="Static + AI code review",
            on_error="continue",
        ),
        WorkflowStep(
            id="tests",
            tool="generate_tests",
            params={"repo": "{user.repo}"},
            label="Find untested functions & generate stubs",
            condition="{user.repo}",
            on_error="continue",
        ),
    ],
}


# ===================================================================
# 2. Safe Refactor  —  "Rename X to Y without breaking anything"
# ===================================================================

SAFE_REFACTOR = {
    "name": "safe_refactor",
    "description": (
        "Safely rename a symbol: first check cross-repo impact, then apply "
        "the refactor (dry-run by default), then generate tests for affected code."
    ),
    "required": ["old_name", "new_name"],
    "optional": ["repo", "base_path", "file_pattern", "dry_run"],
    "steps": [
        WorkflowStep(
            id="impact",
            tool="impact_analysis",
            params={"symbol": "{user.old_name}", "repo": "{user.repo}"},
            label="Check cross-repo impact of the symbol",
            on_error="abort",
        ),
        WorkflowStep(
            id="refactor",
            tool="refactor",
            params={
                "old_name": "{user.old_name}",
                "new_name": "{user.new_name}",
                "base_path": "{user.base_path}",
                "file_pattern": "{user.file_pattern}",
                "dry_run": "{user.dry_run}",
            },
            label="Apply refactoring (dry-run by default)",
            on_error="abort",
        ),
        WorkflowStep(
            id="tests",
            tool="generate_tests",
            params={"repo": "{user.repo}"},
            label="Generate tests for affected code",
            condition="{user.repo}",
            on_error="continue",
        ),
    ],
}


# ===================================================================
# 3. Incident Response  —  "Prod is down, what happened?"
# ===================================================================

INCIDENT_RESPONSE = {
    "name": "incident_response",
    "description": (
        "Incident response pipeline: parse the error / stack trace, find "
        "related code across repos, identify impacted services, and suggest fixes."
    ),
    "required": ["error"],
    "optional": ["repo"],
    "steps": [
        WorkflowStep(
            id="debug",
            tool="debug_error",
            params={"error": "{user.error}"},
            label="Parse error & find related code",
            on_error="continue",
        ),
        WorkflowStep(
            id="search",
            tool="search",
            params={"query": "{user.error}", "n_results": "15"},
            label="Broad codebase search for error context",
            on_error="continue",
        ),
        WorkflowStep(
            id="explain",
            tool="explain",
            params={
                "question": "What could cause this error and how to fix it: {user.error}",
                "repo": "{user.repo}",
                "diagram": True,
            },
            label="AI explanation & fix suggestion",
            on_error="continue",
        ),
    ],
}


# ===================================================================
# 4. Onboarding  —  "I'm new, explain this repo"
# ===================================================================

ONBOARDING = {
    "name": "onboarding",
    "description": (
        "New developer onboarding: explain the repo, scan dependencies, "
        "generate docs, and find code duplicates."
    ),
    "required": ["repo"],
    "optional": [],
    "steps": [
        WorkflowStep(
            id="explain",
            tool="explain",
            params={
                "question": "Give a high-level overview of this repository: architecture, key packages, entry points, and how data flows through it.",
                "repo": "{user.repo}",
                "diagram": True,
            },
            label="High-level repo explanation with diagram",
            on_error="continue",
        ),
        WorkflowStep(
            id="docs",
            tool="generate_docs",
            params={"repo": "{user.repo}"},
            label="Generate documentation",
            on_error="continue",
        ),
        WorkflowStep(
            id="deps",
            tool="dependency_scan",
            params={"repo_path": "{user.repo_path}"},
            label="Scan dependencies",
            condition="{user.repo_path}",
            on_error="continue",
        ),
        WorkflowStep(
            id="duplicates",
            tool="find_duplicates",
            params={"repo": "{user.repo}", "threshold": "0.12"},
            label="Find code duplication patterns",
            on_error="continue",
        ),
    ],
}


# ===================================================================
# 5. Code Health Check  —  "How healthy is this repo?"
# ===================================================================

CODE_HEALTH = {
    "name": "code_health",
    "description": (
        "Comprehensive code health audit: find duplicates, scan dependencies, "
        "identify untested functions, and generate a health summary."
    ),
    "required": ["repo"],
    "optional": ["repo_path"],
    "steps": [
        WorkflowStep(
            id="duplicates",
            tool="find_duplicates",
            params={"repo": "{user.repo}", "threshold": "0.12", "max_results": "30"},
            label="Find code duplication",
            on_error="continue",
        ),
        WorkflowStep(
            id="tests",
            tool="generate_tests",
            params={"repo": "{user.repo}"},
            label="Find untested functions",
            on_error="continue",
        ),
        WorkflowStep(
            id="deps",
            tool="dependency_scan",
            params={"repo_path": "{user.repo_path}"},
            label="Scan dependencies",
            condition="{user.repo_path}",
            on_error="continue",
        ),
        WorkflowStep(
            id="docs",
            tool="generate_docs",
            params={"repo": "{user.repo}"},
            label="Generate / audit documentation",
            on_error="continue",
        ),
    ],
}


# ===================================================================
# 6. Migration Pipeline  —  "Replace X with Y across all repos"
# ===================================================================

MIGRATION_PIPELINE = {
    "name": "migration",
    "description": (
        "End-to-end migration: search for the pattern, check impact, apply "
        "find-and-replace across repos (dry-run by default), then review."
    ),
    "required": ["find", "replace"],
    "optional": ["repo", "base_path", "file_pattern", "branch", "commit_message", "dry_run"],
    "steps": [
        WorkflowStep(
            id="search",
            tool="search",
            params={"query": "{user.find}", "n_results": "20"},
            label="Search for migration pattern",
            on_error="continue",
        ),
        WorkflowStep(
            id="impact",
            tool="impact_analysis",
            params={"symbol": "{user.find}"},
            label="Impact analysis on pattern",
            on_error="continue",
        ),
        WorkflowStep(
            id="migrate",
            tool="migrate",
            params={
                "find": "{user.find}",
                "replace": "{user.replace}",
                "base_path": "{user.base_path}",
                "file_pattern": "{user.file_pattern}",
                "branch": "{user.branch}",
                "commit_message": "{user.commit_message}",
                "dry_run": "{user.dry_run}",
            },
            label="Apply migration (dry-run by default)",
            on_error="abort",
        ),
    ],
}


# ===================================================================
# Registry
# ===================================================================

BUILTIN_WORKFLOWS = {
    w["name"]: w
    for w in [
        PRE_MR_REVIEW,
        SAFE_REFACTOR,
        INCIDENT_RESPONSE,
        ONBOARDING,
        CODE_HEALTH,
        MIGRATION_PIPELINE,
    ]
}


def list_workflows() -> list:
    """Return summary of all built-in workflows."""
    return [
        {
            "name": w["name"],
            "description": w["description"],
            "required_params": w["required"],
            "optional_params": w.get("optional", []),
            "steps": len(w["steps"]),
        }
        for w in BUILTIN_WORKFLOWS.values()
    ]


def get_workflow(name: str) -> dict:
    """Get a built-in workflow definition by name."""
    return BUILTIN_WORKFLOWS.get(name)
