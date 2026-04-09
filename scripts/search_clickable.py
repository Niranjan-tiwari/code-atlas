#!/usr/bin/env python3
"""
Search code and return CLICKABLE file paths in Cursor/VSCode terminal.

Usage:
    python3 scripts/search_clickable.py "ProcessMessage"
    python3 scripts/search_clickable.py "redis connection" --repo payment-service
    python3 scripts/search_clickable.py "handleAuth" -n 10
    python3 scripts/search_clickable.py "webhook generation" --hybrid
"""

import sys
import os
import argparse
import logging
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
logging.basicConfig(level=logging.WARNING)

# Base paths where actual repo clones live
BASE_PATHS = [
    "/path/to/your/repos",
    "/path/to/your/repos-alt",
]

# Load from config if available
try:
    config_path = Path(__file__).parent.parent / "config" / "config.json"
    if config_path.exists():
        with open(config_path) as f:
            cfg = json.load(f)
        BASE_PATHS = [cfg.get("base_path", BASE_PATHS[0])]
        BASE_PATHS += cfg.get("additional_base_paths", [])
except Exception:
    pass


class Colors:
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    MAGENTA = "\033[95m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    UNDERLINE = "\033[4m"
    RESET = "\033[0m"


def resolve_full_path(repo_name: str, relative_file: str) -> str:
    """Resolve repo+file to an absolute clickable path."""
    for base in BASE_PATHS:
        full = os.path.join(base, repo_name, relative_file)
        if os.path.isfile(full):
            return full
    # Fallback: return best guess
    return os.path.join(BASE_PATHS[0], repo_name, relative_file)


def find_line_number(file_path: str, query: str) -> int:
    """Try to find the line number where the query matches in the file."""
    if not os.path.isfile(file_path):
        return 1
    try:
        query_lower = query.lower()
        with open(file_path, 'r', errors='ignore') as f:
            for i, line in enumerate(f, 1):
                if query_lower in line.lower():
                    return i
    except Exception:
        pass
    return 1


def search(query, n_results=10, repo_filter=None, use_enhanced=False):
    """Run search and return results with resolved paths."""
    if use_enhanced:
        from src.ai.rag_enhanced import EnhancedRAGRetriever
        rag = EnhancedRAGRetriever(
            vector_db_path="./data/qdrant_db",
            llm_manager=None,
            use_hyde=False,
            use_deep_context=False,
            use_reranking=True,
            use_hybrid_search=True,
            enable_cache=True,
        )
    else:
        from src.ai.rag import RAGRetriever
        rag = RAGRetriever(persist_directory="./data/qdrant_db")

    t0 = time.time()
    results = rag.search_code(query, n_results=n_results, repo_filter=repo_filter)
    elapsed = time.time() - t0
    return results, elapsed


def main():
    parser = argparse.ArgumentParser(description="Search code with clickable file paths")
    parser.add_argument("query", help="Search query (function name, keyword, or question)")
    parser.add_argument("-n", "--num", type=int, default=10, help="Number of results (default: 10)")
    parser.add_argument("-r", "--repo", default=None, help="Filter to specific repo")
    parser.add_argument("--hybrid", action="store_true", help="Use enhanced hybrid search (BM25 + vector + reranking)")
    parser.add_argument("--no-code", action="store_true", help="Hide code preview, show paths only")
    args = parser.parse_args()

    results, elapsed = search(args.query, args.num, args.repo, args.hybrid)

    if not results:
        print(f"\n{Colors.YELLOW}No results found for \"{args.query}\"{Colors.RESET}")
        return

    mode = "hybrid+rerank" if args.hybrid else "vector"
    repo_label = f" in {Colors.CYAN}{args.repo}{Colors.RESET}" if args.repo else ""
    print(f"\n{Colors.BOLD}Found {len(results)} results{Colors.RESET} for "
          f"\"{Colors.GREEN}{args.query}{Colors.RESET}\"{repo_label} "
          f"{Colors.DIM}({mode}, {elapsed*1000:.0f}ms){Colors.RESET}\n")

    for i, r in enumerate(results, 1):
        repo = r.get("repo", "unknown")
        rel_file = r.get("file", "unknown")
        lang = r.get("language", "?")
        score = r.get("rerank_score") or r.get("hybrid_score") or r.get("distance", 0)
        code = r.get("code", "")

        full_path = resolve_full_path(repo, rel_file)
        line_num = find_line_number(full_path, args.query)
        file_exists = os.path.isfile(full_path)

        # Clickable path format: /absolute/path/file.go:LINE
        # Cursor/VSCode terminal makes these Ctrl+clickable
        clickable = f"{full_path}:{line_num}"

        # Score bar
        score_pct = min(score, 1.0) * 100
        bar_len = int(score_pct / 5)
        bar = "█" * bar_len + "░" * (20 - bar_len)

        print(f"  {Colors.CYAN}[{i}]{Colors.RESET} {Colors.BOLD}{repo}{Colors.RESET}/{rel_file} "
              f"{Colors.DIM}({lang}){Colors.RESET}")
        print(f"      Score: {Colors.GREEN}{score:.4f}{Colors.RESET} {Colors.DIM}{bar}{Colors.RESET}")

        if file_exists:
            print(f"      {Colors.UNDERLINE}{clickable}{Colors.RESET}")
        else:
            print(f"      {Colors.RED}(file not on disk){Colors.RESET} {clickable}")

        if not args.no_code and code:
            lines = code.strip().split("\n")
            preview = "\n".join(f"        {l}" for l in lines[:4])
            if len(lines) > 4:
                preview += f"\n        {Colors.DIM}... ({len(lines)-4} more lines){Colors.RESET}"
            print(f"{Colors.DIM}{preview}{Colors.RESET}")

        print()


if __name__ == "__main__":
    main()
