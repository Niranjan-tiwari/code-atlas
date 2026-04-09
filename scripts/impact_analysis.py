#!/usr/bin/env python3
"""
Code Change Impact Analysis — CLI

Trace every caller / dependent of a function or class across all indexed repos.

Usage:
    # By symbol name
    python3 scripts/impact_analysis.py ProcessPayment
    python3 scripts/impact_analysis.py ProcessPayment --repo rcs-sender
    python3 scripts/impact_analysis.py "SendMessage" --max 30

    # By diff file
    python3 scripts/impact_analysis.py --diff changes.patch

    # JSON output (for piping)
    python3 scripts/impact_analysis.py ProcessPayment --json
"""
import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _print_impact(result: dict, verbose: bool = False):
    """Pretty-print impact analysis results."""
    symbol = result.get("symbol", "?")
    defs = result.get("definition_sites", [])
    impacts = result.get("impact", [])
    summary = result.get("summary", {})
    elapsed = result.get("time_ms", 0)

    print(f"\n{'='*60}")
    print(f"  Impact Analysis: {symbol}")
    print(f"{'='*60}")

    # Definitions
    if defs:
        print(f"\n  DEFINED IN ({len(defs)} site(s)):")
        for d in defs:
            print(f"    {d['repo']}/{d['file']}  [{d['language']}]")
            for a in d.get("appearances", []):
                if a["usage"] == "definition":
                    print(f"      L{a['line']}: {a['text'][:120]}")
    else:
        print("\n  DEFINITION: not found in indexed code")

    # Impact
    print(f"\n  AFFECTED ({summary.get('total_affected_files', 0)} files in "
          f"{summary.get('total_affected_repos', 0)} repos):\n")

    if not impacts:
        print("    No callers / dependents found.")
    else:
        # Group by repo
        by_repo = {}
        for entry in impacts:
            repo = entry["repo"]
            by_repo.setdefault(repo, []).append(entry)

        for repo in sorted(by_repo):
            entries = by_repo[repo]
            print(f"    [{repo}]  ({len(entries)} file(s))")
            for entry in entries:
                types = ", ".join(entry.get("usage_types", []))
                print(f"      {entry['file']}  ({types})")
                if verbose:
                    for a in entry.get("appearances", []):
                        print(f"        L{a['line']} [{a['usage']}] {a['text'][:100]}")
            print()

    # Usage breakdown
    breakdown = summary.get("usage_breakdown", {})
    if breakdown:
        parts = [f"{k}: {v}" for k, v in sorted(breakdown.items(), key=lambda x: -x[1])]
        print(f"  Usage breakdown: {', '.join(parts)}")

    print(f"\n  Completed in {elapsed}ms")
    print(f"{'='*60}\n")


def _print_diff_impact(result: dict, verbose: bool = False):
    """Pretty-print diff impact analysis results."""
    symbols = result.get("changed_symbols", [])
    agg = result.get("aggregate_summary", {})
    elapsed = result.get("time_ms", 0)

    print(f"\n{'='*60}")
    print(f"  Diff Impact Analysis")
    print(f"  Changed symbols: {', '.join(symbols) if symbols else 'none detected'}")
    print(f"{'='*60}")

    if not symbols:
        print(f"\n  {result.get('note', 'No changes detected')}")
        return

    print(f"\n  Aggregate: {agg.get('total_affected_files', 0)} files across "
          f"{agg.get('total_affected_repos', 0)} repos")

    for sym, data in result.get("per_symbol", {}).items():
        _print_impact(data, verbose=verbose)

    print(f"\n  Total time: {elapsed}ms\n")


def main():
    parser = argparse.ArgumentParser(
        description="Trace callers & dependents of a symbol across all repos",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("symbol", nargs="?", help="Function/class/symbol name to trace")
    parser.add_argument("--diff", help="Path to a unified diff / patch file")
    parser.add_argument("--repo", help="Scope analysis to a specific repo")
    parser.add_argument("--max", type=int, default=50, help="Max results (default: 50)")
    parser.add_argument("--db", default="./data/qdrant_db", help="Vector DB path")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show line-level detail")
    args = parser.parse_args()

    if not args.symbol and not args.diff:
        parser.error("Provide a symbol name or --diff <file>")

    from src.ai.rag import RAGRetriever
    print("Loading RAG retriever...", flush=True)
    retriever = RAGRetriever(persist_directory=args.db)

    if args.diff:
        diff_text = Path(args.diff).read_text()
        from src.tools.impact_analyzer import analyze_diff_impact
        result = analyze_diff_impact(retriever, diff_text, repo_name=args.repo, max_results=args.max)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            _print_diff_impact(result, verbose=args.verbose)
    else:
        from src.tools.impact_analyzer import analyze_impact
        result = analyze_impact(retriever, args.symbol, repo_filter=args.repo, max_results=args.max)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            _print_impact(result, verbose=args.verbose)


if __name__ == "__main__":
    main()
