#!/usr/bin/env python3
"""
Run a multi-step workflow pipeline.

Built-in workflows:
  pre_mr_review   — diff impact + code review + test generation
  safe_refactor   — impact check + refactor + tests
  incident_response — error debug + search + AI explanation
  onboarding      — explain repo + docs + deps + duplicates
  code_health     — duplicates + tests + deps + docs
  migration       — search + impact + find-replace

Usage:
    # List available workflows
    python3 scripts/run_workflow.py --list

    # Pre-MR review (provide a diff)
    python3 scripts/run_workflow.py pre_mr_review --diff changes.patch --repo my-service

    # Incident response
    python3 scripts/run_workflow.py incident_response --error "panic: runtime error: index out of range"

    # Onboarding a new dev to a repo
    python3 scripts/run_workflow.py onboarding --repo common-message-router

    # Code health check
    python3 scripts/run_workflow.py code_health --repo rcs-sender

    # Safe refactor
    python3 scripts/run_workflow.py safe_refactor --old-name ProcessPayment --new-name HandlePayment

    # Migration
    python3 scripts/run_workflow.py migration --find "oldPkg.Call" --replace "newPkg.Call"

    # JSON output
    python3 scripts/run_workflow.py code_health --repo rcs-sender --json

    # Custom workflow from JSON file
    python3 scripts/run_workflow.py --custom workflow.json
"""
import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _print_result(result, verbose=False):
    """Pretty-print workflow result."""
    d = result.to_dict() if hasattr(result, "to_dict") else result

    print(f"\n{'='*70}")
    print(f"  Workflow: {d['workflow']}   Status: {d['status']}")
    print(f"{'='*70}\n")

    for i, step in enumerate(d["steps"], 1):
        icon = {"success": "[OK]", "skipped": "[SKIP]", "error": "[FAIL]"}.get(step["status"], "[??]")
        label = step["label"] or step["tool"]
        print(f"  {i}. {icon} {label}  ({step['time_ms']}ms)")
        if step["status"] == "error":
            print(f"       Error: {step['error']}")
        elif step["status"] == "success" and verbose:
            out = step["output"]
            if "summary" in out and isinstance(out["summary"], dict):
                for k, v in out["summary"].items():
                    print(f"       {k}: {v}")
            if "issue_count" in out:
                print(f"       Issues found: {out['issue_count']}")
            if "count" in out:
                print(f"       Matches: {out['count']}")
            if "explanation" in out:
                expl = out["explanation"]
                print(f"       Explanation: {expl[:200]}...")
            if "generated_stubs" in out:
                print(f"       Test stubs generated: {len(out['generated_stubs'])}")
        print()

    # Summary
    summary = d.get("summary", {})
    if summary:
        print(f"  {'─'*50}")
        print(f"  Summary:")
        for k, v in summary.items():
            if isinstance(v, dict):
                print(f"    {k}:")
                for kk, vv in v.items():
                    print(f"      {kk}: {vv}")
            else:
                print(f"    {k}: {v}")

    print(f"\n  Total time: {d['time_ms']}ms")
    print(f"{'='*70}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Run multi-step workflow pipelines",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("workflow", nargs="?", help="Workflow name (e.g. pre_mr_review, code_health)")
    parser.add_argument("--list", action="store_true", help="List available workflows")
    parser.add_argument("--custom", help="Path to custom workflow JSON file")

    # Common params
    parser.add_argument("--repo", help="Repository name")
    parser.add_argument("--repo-path", help="Repository filesystem path")
    parser.add_argument("--diff", help="Path to diff / patch file")
    parser.add_argument("--error", help="Error text or stack trace")
    parser.add_argument("--old-name", help="Old symbol name (for refactor)")
    parser.add_argument("--new-name", help="New symbol name (for refactor)")
    parser.add_argument("--find", help="Pattern to find (for migration)")
    parser.add_argument("--replace", help="Replacement text (for migration)")
    parser.add_argument("--symbol", help="Symbol name (for impact)")
    parser.add_argument("--base-path", help="Base path for repos")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Dry run mode (default)")
    parser.add_argument("--apply", action="store_true", help="Actually apply changes (disable dry-run)")
    parser.add_argument("--db", default="./data/vector_db", help="Vector DB path")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose step output")
    args = parser.parse_args()

    if args.list:
        from src.workflows.builtin import list_workflows
        workflows = list_workflows()
        print(f"\nAvailable workflows ({len(workflows)}):\n")
        for w in workflows:
            print(f"  {w['name']:<20s} {w['description'][:80]}")
            print(f"  {'':20s} required: {w['required_params']}")
            if w["optional_params"]:
                print(f"  {'':20s} optional: {w['optional_params']}")
            print(f"  {'':20s} steps: {w['steps']}")
            print()
        return

    if not args.workflow and not args.custom:
        parser.error("Provide a workflow name or --custom <file>. Use --list to see options.")

    # Build user params from CLI args
    user_params = {}
    if args.repo:
        user_params["repo"] = args.repo
    if args.repo_path:
        user_params["repo_path"] = args.repo_path
    if args.diff:
        user_params["diff"] = Path(args.diff).read_text()
    if args.error:
        user_params["error"] = args.error
    if args.old_name:
        user_params["old_name"] = args.old_name
    if args.new_name:
        user_params["new_name"] = args.new_name
    if args.find:
        user_params["find"] = args.find
    if args.replace:
        user_params["replace"] = args.replace
    if args.symbol:
        user_params["symbol"] = args.symbol
    if args.base_path:
        user_params["base_path"] = args.base_path
    user_params["dry_run"] = not args.apply

    # Load retriever
    from src.ai.rag import RAGRetriever
    print("Loading RAG retriever...", flush=True)
    retriever = RAGRetriever(persist_directory=args.db)

    from src.workflows.engine import WorkflowEngine, WorkflowStep
    engine = WorkflowEngine(retriever)

    if args.custom:
        custom = json.loads(Path(args.custom).read_text())
        steps = [
            WorkflowStep(
                id=s["id"], tool=s["tool"], params=s.get("params", {}),
                label=s.get("label", ""), condition=s.get("condition"),
                on_error=s.get("on_error", "continue"),
            )
            for s in custom.get("steps", [])
        ]
        name = custom.get("name", "custom")
        user_params.update(custom.get("params", {}))
    else:
        from src.workflows.builtin import get_workflow
        wf_def = get_workflow(args.workflow)
        if not wf_def:
            from src.workflows.builtin import list_workflows
            names = [w["name"] for w in list_workflows()]
            parser.error(f"Unknown workflow: {args.workflow}. Available: {names}")
        missing = [p for p in wf_def["required"] if not user_params.get(p)]
        if missing:
            parser.error(f"Workflow '{args.workflow}' requires: {missing}")
        steps = wf_def["steps"]
        name = wf_def["name"]

    print(f"Running workflow: {name} ({len(steps)} steps)\n", flush=True)
    result = engine.run(name, steps, user_params)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, default=str))
    else:
        _print_result(result, verbose=args.verbose)


if __name__ == "__main__":
    main()
