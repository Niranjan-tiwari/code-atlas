#!/usr/bin/env python3
"""
Interactive CLI for querying the codebase using RAG + LLM

Usage:
    python3 scripts/query_code.py                    # Interactive mode
    python3 scripts/query_code.py --query "..."       # Single query
    python3 scripts/query_code.py --search "..."      # Search only (no LLM)
    python3 scripts/query_code.py --repo my-service   # Filter to specific repo
    python3 scripts/query_code.py --list-repos        # List indexed repos
    python3 scripts/query_code.py --stats             # Show stats
    python3 scripts/query_code.py --enhanced-rag     # Enhanced RAG (HyDE + hybrid; slower)
"""

import sys
import os
import json
import argparse
import logging
import readline
import signal
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# Enable arrow keys, history, and line editing in interactive input()
readline.parse_and_bind('"\e[A": history-search-backward')
readline.parse_and_bind('"\e[B": history-search-forward')
readline.parse_and_bind('set editing-mode emacs')

# Add project root to path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.ai.llm.env_keys import cli_export_block, cli_set_keys_tip


def _load_dotenv() -> None:
    """Populate os.environ from repo-root .env if present (does not override existing env)."""
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env", override=False)
    except ImportError:
        pass


def _effective_qdrant_path(args) -> str:
    return os.environ.get("QDRANT_PATH") or args.db_path


def _query_engine_rag_options(
    llm_config_path: Optional[str], cli_enhanced: bool
) -> Tuple[bool, Optional[Dict]]:
    """
    Whether to use EnhancedRAGRetriever (HyDE, hybrid BM25+vector, optional rerank/graph/deep).
    Precedence: CLI --enhanced-rag > env CODE_ATLAS_ENHANCED_RAG > ai_config query_engine.use_enhanced_rag
    """
    use = False
    extra: Optional[Dict] = None
    if llm_config_path and Path(llm_config_path).is_file():
        try:
            with open(llm_config_path, encoding="utf-8") as f:
                data = json.load(f)
            qe = data.get("query_engine") or {}
            use = bool(qe.get("use_enhanced_rag", False))
            raw = qe.get("enhanced_rag")
            if isinstance(raw, dict) and raw:
                extra = dict(raw)
        except (OSError, json.JSONDecodeError):
            pass
    env = os.environ.get("CODE_ATLAS_ENHANCED_RAG", "").strip().lower()
    if env in ("1", "true", "yes", "on"):
        use = True
    if cli_enhanced:
        use = True
    return use, extra


def _print_missing_deps(e: Exception) -> None:
    name = getattr(e, "name", None) or "dependency"
    if "qdrant" in str(e).lower():
        name = "qdrant_client"
    print(
        f"\n❌ Missing Python package ({name})\n\n"
        f"Install from repo root ({ROOT}):\n"
        "    pip install -r requirements-query.txt\n"
        "  or full stack:\n"
        "    pip install -r requirements.txt -r requirements-ai.txt\n\n"
        "  Prefer the project venv (deps are not installed for root by default):\n"
        "    exit   # leave sudo su / root shell\n"
        "    cd " + str(ROOT) + "\n"
        "    source .venv/bin/activate   # if you use a venv\n"
        "    PYTHONPATH=. python3 scripts/query_code.py --list-repos\n",
        file=sys.stderr,
    )


def _run_list_repos_light(db_path: str) -> None:
    from src.ai.vector_backend import QdrantEmbeddedLockError, list_indexed_repos_with_chunks

    try:
        format_repos_list(list_indexed_repos_with_chunks(db_path))
    except QdrantEmbeddedLockError as e:
        print(f"\n{e}", file=sys.stderr)
        sys.exit(1)


def _run_stats_light(db_path: str, llm_config_path: Optional[str]) -> None:
    from src.ai.vector_backend import QdrantEmbeddedLockError, list_indexed_repos_with_chunks

    try:
        repos = list_indexed_repos_with_chunks(db_path)
    except QdrantEmbeddedLockError as e:
        print(f"\n{e}", file=sys.stderr)
        sys.exit(1)
    total = sum(r["chunks"] for r in repos)
    providers: list[str] = []
    try:
        from src.ai.llm.manager import LLMManager

        lm = LLMManager(config_path=llm_config_path)
        providers = lm.get_usage_stats().get("available_providers", [])
    except Exception:
        pass
    print(f"📊 Repos: {len(repos)}, Chunks: {total:,}")
    if providers:
        print(f"🤖 Providers: {', '.join(providers)}")
    else:
        print("🤖 Providers: (none — set API keys or configure config/ai_config.json)")


# Colors for terminal output
class Colors:
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    MAGENTA = "\033[95m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"


def setup_logging(verbose: bool = False):
    """Setup logging"""
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )


def print_banner():
    """Print the application banner"""
    print(f"""
{Colors.CYAN}{Colors.BOLD}╔══════════════════════════════════════════════════════════╗
║          🤖 Code Intelligence - RAG + LLM               ║
║        Ask questions about your codebase                 ║
╚══════════════════════════════════════════════════════════╝{Colors.RESET}
""")


def print_help():
    """Print interactive mode help"""
    print(f"""
{Colors.BOLD}Commands:{Colors.RESET}
  {Colors.GREEN}/search <query>{Colors.RESET}     - Search code (no LLM, just vector search)
  {Colors.GREEN}/explain <question>{Colors.RESET} - Explain function/repo/logic (RAG + LLM)
  {Colors.GREEN}/explain <question> --diagram{Colors.RESET} - Explain + Mermaid architecture diagram
  {Colors.GREEN}/repo <name>{Colors.RESET}         - Filter to specific repo (or 'all' to reset)
  {Colors.GREEN}/repos{Colors.RESET}               - List all indexed repos
  {Colors.GREEN}/info <repo>{Colors.RESET}          - Get repo details
  {Colors.GREEN}/stats{Colors.RESET}               - Show usage stats
  {Colors.GREEN}/provider <name>{Colors.RESET}      - Switch LLM (groq/ollama/openai/anthropic/gemini/auto)
  {Colors.GREEN}/history{Colors.RESET}              - Show query history
  {Colors.GREEN}/help{Colors.RESET}                 - Show this help
  {Colors.GREEN}/quit{Colors.RESET}                 - Exit

{Colors.DIM}This session uses standard or enhanced RAG depending on how you started the script
  (--enhanced-rag or CODE_ATLAS_ENHANCED_RAG=1 or query_engine.use_enhanced_rag in ai_config.json).{Colors.RESET}

{Colors.BOLD}Examples:{Colors.RESET}
  {Colors.DIM}How does message routing work in this codebase?
  /repo payment-service
  /explain how payment_service works
  /explain what does ProcessMessage do
  /search error handling in Go
  /repo all
  Show me the webhook generation flow{Colors.RESET}
""")


def format_search_results(results):
    """Format search results for display"""
    if not results:
        print(f"\n{Colors.YELLOW}No results found.{Colors.RESET}")
        return
    
    print(f"\n{Colors.BOLD}🔍 Found {len(results)} results:{Colors.RESET}\n")
    
    for i, r in enumerate(results, 1):
        relevance = 1 - (r.get("distance", 0) or 0)
        pct = f"{relevance*100:.0f}%"
        print(f"{Colors.CYAN}[{i}]{Colors.RESET} {Colors.BOLD}{r['repo']}{Colors.RESET}/{r['file']} ({r['language']}) - {Colors.GREEN}{pct}{Colors.RESET}")
        
        # Show first 3 lines of code
        lines = r["code"].split("\n")
        preview = "\n".join(lines[:5])
        if len(lines) > 5:
            preview += f"\n{Colors.DIM}  ... ({len(lines)-5} more lines){Colors.RESET}"
        print(f"{Colors.DIM}{preview}{Colors.RESET}")
        print()


def format_repos_list(repos):
    """Format repos list for display"""
    if not repos:
        print(f"\n{Colors.YELLOW}No indexed repos found.{Colors.RESET}")
        return
    
    print(f"\n{Colors.BOLD}📚 Indexed Repositories ({len(repos)}):{Colors.RESET}\n")
    
    total_chunks = 0
    for r in repos:
        total_chunks += r["chunks"]
        print(f"  {Colors.GREEN}✅{Colors.RESET} {r['name']:45s} {r['chunks']:>6} chunks")
    
    print(f"\n  {Colors.BOLD}Total: {len(repos)} repos, {total_chunks:,} chunks{Colors.RESET}")


def interactive_mode(engine: Any, initial_repo: str = None):
    """Run interactive query mode"""
    print_banner()
    
    # Show available providers
    providers = engine.llm.get_available_providers()
    if providers:
        print(f"{Colors.BOLD}Available LLM Providers:{Colors.RESET}")
        for p in providers:
            status = f"{Colors.GREEN}✅{Colors.RESET}" if p["available"] else f"{Colors.RED}❌{Colors.RESET}"
            print(f"  {status} {p['name']:12s} → {p['model']}")
        print()
    else:
        print(f"{Colors.RED}⚠️  No LLM providers configured!{Colors.RESET}")
        print(cli_set_keys_tip())
        print()
    
    # Show repo count
    repos = engine.list_repos()
    print(f"{Colors.BOLD}📊 {len(repos)} repositories indexed ({sum(r['chunks'] for r in repos):,} chunks){Colors.RESET}")
    lm = getattr(engine, "latency_bundle", {}).get("mode", "balanced")
    print(f"{Colors.DIM}⏱️  Latency mode: {lm} (config latency.* + --latency / CODE_ATLAS_LATENCY_MODE){Colors.RESET}")
    if getattr(engine, "is_enhanced", False):
        print(
            f"{Colors.CYAN}🔬 Enhanced RAG on{Colors.RESET} "
            f"{Colors.DIM}(HyDE + hybrid when enabled in config; --latency fast forces them off){Colors.RESET}"
        )
    else:
        print(
            f"{Colors.DIM}Standard vector RAG — for HyDE/hybrid pipeline: "
            f"--enhanced-rag or CODE_ATLAS_ENHANCED_RAG=1{Colors.RESET}"
        )
    
    repo_filter = initial_repo
    if repo_filter:
        print(f"{Colors.YELLOW}🔒 Filtered to repo: {repo_filter}{Colors.RESET}")
    
    provider_override = None
    
    print(f"\nType your question or {Colors.GREEN}/help{Colors.RESET} for commands. {Colors.DIM}Ctrl+C to exit.{Colors.RESET}\n")
    
    while True:
        try:
            # Show prompt
            repo_display = f" [{Colors.YELLOW}{repo_filter}{Colors.RESET}]" if repo_filter else ""
            prompt = f"{Colors.BOLD}{Colors.BLUE}❓{repo_display} > {Colors.RESET}"
            
            user_input = input(prompt).strip()
            
            if not user_input:
                continue
            
            # Handle commands
            if user_input.startswith("/"):
                parts = user_input.split(maxsplit=1)
                cmd = parts[0].lower()
                arg = parts[1] if len(parts) > 1 else ""
                
                if cmd in ("/quit", "/exit", "/q"):
                    print(f"\n{Colors.CYAN}Goodbye! 👋{Colors.RESET}")
                    break
                
                elif cmd == "/help":
                    print_help()
                
                elif cmd == "/repos":
                    format_repos_list(engine.list_repos())
                
                elif cmd == "/repo":
                    if arg.lower() == "all" or arg == "":
                        repo_filter = None
                        print(f"{Colors.GREEN}🔓 Searching all repos{Colors.RESET}")
                    else:
                        repo_filter = arg
                        print(f"{Colors.YELLOW}🔒 Filtered to: {repo_filter}{Colors.RESET}")
                
                elif cmd == "/info":
                    if arg:
                        info = engine.get_repo_info(arg)
                        print(f"\n{Colors.BOLD}📋 {info['name']}{Colors.RESET}")
                        print(f"  Chunks: {info.get('chunks', 0)}")
                        print(f"  Languages: {', '.join(info.get('languages', []))}")
                        if info.get('sample_files'):
                            print(f"  Sample files:")
                            for f in info['sample_files'][:5]:
                                print(f"    - {f}")
                    else:
                        print(f"{Colors.YELLOW}Usage: /info <repo-name>{Colors.RESET}")
                
                elif cmd == "/search":
                    if arg:
                        search_repo = repo_filter
                        if not search_repo:
                            detected = engine.retriever.detect_repo_in_query(arg)
                            if detected:
                                search_repo = detected
                                print(f"{Colors.YELLOW}🎯 Auto-detected repo: {detected}{Colors.RESET}")
                        results = engine.search_only(arg, n_results=10, repo_filter=search_repo)
                        format_search_results(results)
                    else:
                        print(f"{Colors.YELLOW}Usage: /search <query>{Colors.RESET}")
                
                elif cmd == "/explain":
                    if arg:
                        use_diagram = " --diagram" in arg or " --diagram" in user_input
                        question = arg.replace(" --diagram", "").strip()
                        # Auto-detect repo name from question if no explicit filter
                        effective_repo = repo_filter
                        if not effective_repo:
                            detected = engine.retriever.detect_repo_in_query(question)
                            if detected:
                                effective_repo = detected
                                print(f"{Colors.YELLOW}🎯 Auto-detected repo: {detected}{Colors.RESET}")
                        print(f"\n{Colors.DIM}🔍 Explaining... (LLM may take 30-90s){Colors.RESET}")
                        from src.ai.rag import RAGRetriever
                        from src.tools.repo_explainer import explain
                        retriever = engine.retriever
                        result = explain(retriever, question, repo_filter=effective_repo, include_diagram=use_diagram)
                        if result.get("error"):
                            print(f"\n{Colors.RED}❌ {result['error']}{Colors.RESET}")
                        else:
                            print(f"\n{Colors.BOLD}{Colors.GREEN}📝 Explanation:{Colors.RESET}\n")
                            print(result.get("explanation", ""))
                            if result.get("diagram"):
                                print(f"\n{Colors.BOLD}{Colors.CYAN}📐 Mermaid Diagram:{Colors.RESET}\n```mermaid\n{result['diagram']}\n```")
                            if result.get("sources"):
                                print(f"\n{Colors.BOLD}📚 Sources:{Colors.RESET}")
                                for s in result["sources"][:8]:
                                    print(f"  • {s['repo']}/{s['file']}")
                            print(f"\n{Colors.DIM}⚡ {result.get('provider','')}/{result.get('model','')}{Colors.RESET}")
                    else:
                        print(f"{Colors.YELLOW}Usage: /explain <question> [--diagram]{Colors.RESET}")
                
                elif cmd == "/stats":
                    stats = engine.get_stats()
                    print(f"\n{Colors.BOLD}📊 Engine Stats:{Colors.RESET}")
                    print(f"  Repos indexed: {stats['repos_indexed']}")
                    print(f"  Total chunks: {stats['total_chunks']:,}")
                    print(f"  Queries answered: {stats['queries_answered']}")
                    print(f"  LLM requests: {stats['llm']['total_requests']}")
                    print(f"  Total tokens: {stats['llm']['total_tokens']:,}")
                    print(f"  Total cost: ${stats['llm']['total_cost_usd']:.6f}")
                    print(f"  Providers: {', '.join(stats['llm']['available_providers'])}")
                    print(
                        f"{Colors.DIM}  (Query counts = natural-language questions only; /search and /explain are not included.){Colors.RESET}"
                    )
                
                elif cmd == "/provider":
                    if arg:
                        provider_override = arg if arg != "auto" else None
                        print(f"{Colors.GREEN}🤖 Provider: {arg}{Colors.RESET}")
                    else:
                        print(f"{Colors.YELLOW}Usage: /provider <groq|ollama|openai|anthropic|gemini|auto>{Colors.RESET}")
                
                elif cmd == "/history":
                    if engine.history:
                        print(f"\n{Colors.BOLD}📜 Query History:{Colors.RESET}")
                        for i, h in enumerate(engine.history, 1):
                            print(f"  {i}. {h['question'][:80]}... ({h['provider']})")
                    else:
                        print(f"{Colors.DIM}No queries yet.{Colors.RESET}")
                        print(
                            f"{Colors.DIM}  Type a question without a leading slash (not /search or /explain) to run RAG + LLM and record history.{Colors.RESET}"
                        )
                
                else:
                    print(f"{Colors.YELLOW}Unknown command: {cmd}. Type /help for commands.{Colors.RESET}")
                
                continue
            
            # Regular question - use full RAG + LLM pipeline
            # Auto-detect repo name from question if no explicit filter
            effective_repo = repo_filter
            if not effective_repo:
                detected = engine.retriever.detect_repo_in_query(user_input)
                if detected:
                    effective_repo = detected
                    print(f"{Colors.YELLOW}🎯 Auto-detected repo: {detected}{Colors.RESET}")
            
            print(f"\n{Colors.DIM}🔍 Searching codebase...{Colors.RESET}")
            
            try:
                result = engine.query(
                    question=user_input,
                    repo_filter=effective_repo,
                    provider=provider_override,
                    n_context=5,
                    temperature=0.3
                )
                
                print(f"\n{Colors.BOLD}{Colors.GREEN}📝 Answer:{Colors.RESET}\n")
                print(result.answer)
                
                # Print sources
                if result.sources:
                    print(f"\n{Colors.BOLD}📚 Sources:{Colors.RESET}")
                    for src in result.sources:
                        relevance = src.get("relevance", 0)
                        pct = f"{relevance*100:.0f}%" if relevance else "N/A"
                        print(f"  {Colors.CYAN}[{src['index']}]{Colors.RESET} {src['repo']}/{src['file']} ({src['language']}) - {pct}")
                
                print(f"\n{Colors.DIM}⚡ {result.provider}/{result.model} | {result.tokens_used} tokens | ${result.cost_estimate:.6f} | {result.latency_seconds:.1f}s{Colors.RESET}")
                
            except RuntimeError as e:
                print(f"\n{Colors.RED}❌ Error: {e}{Colors.RESET}")
                print(f"{Colors.YELLOW}Make sure at least one LLM API key is set:{Colors.RESET}")
                print(cli_export_block())
            except Exception as e:
                print(f"\n{Colors.RED}❌ Error: {e}{Colors.RESET}")
            
            print()
            
        except KeyboardInterrupt:
            print(f"\n\n{Colors.CYAN}Goodbye! 👋{Colors.RESET}")
            break
        except EOFError:
            print(f"\n{Colors.CYAN}Goodbye! 👋{Colors.RESET}")
            break


def main():
    parser = argparse.ArgumentParser(description="Query your codebase using RAG + LLM")
    parser.add_argument("--query", "-q", help="Single query (non-interactive)")
    parser.add_argument("--search", "-s", help="Search code only (no LLM)")
    parser.add_argument("--repo", "-r", help="Filter to specific repository")
    parser.add_argument("--list-repos", action="store_true", help="List indexed repos")
    parser.add_argument("--stats", action="store_true", help="Show stats")
    parser.add_argument("--provider", "-p", help="LLM provider (groq/ollama/openai/anthropic/gemini)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    parser.add_argument(
        "--db-path",
        default="./data/qdrant_db",
        help="Qdrant storage directory (env QDRANT_PATH overrides default location)",
    )
    parser.add_argument(
        "--enhanced-rag",
        action="store_true",
        help=(
            "Use EnhancedRAGRetriever (HyDE + hybrid BM25/vector; optional rerank/graph in ai_config). "
            "Slower than plain RAG, not a separate 'agent' — see docs. "
            "Or set CODE_ATLAS_ENHANCED_RAG=1 or query_engine.use_enhanced_rag in config/ai_config.json"
        ),
    )
    parser.add_argument(
        "--latency",
        choices=("fast", "balanced", "quality"),
        default=None,
        help=(
            "Latency budget: fast (minimal augmentations), balanced (default from config), "
            "quality (allow HyDE/deep from ai_config). Overrides config latency.mode; "
            "or set CODE_ATLAS_LATENCY_MODE=fast|balanced|quality"
        ),
    )

    args = parser.parse_args()

    _load_dotenv()

    setup_logging(args.verbose)
    
    llm_cfg = ROOT / "config" / "ai_config.json"
    llm_config_path = str(llm_cfg) if llm_cfg.is_file() else None
    db_path = _effective_qdrant_path(args)

    if args.list_repos:
        try:
            _run_list_repos_light(db_path)
        except ImportError as e:
            _print_missing_deps(e)
            sys.exit(1)
        return

    if args.stats:
        try:
            _run_stats_light(db_path, llm_config_path)
        except ImportError as e:
            _print_missing_deps(e)
            sys.exit(1)
        return

    try:
        from src.ai.query_engine import QueryEngine
        from src.ai.vector_backend import QdrantEmbeddedLockError
    except (ModuleNotFoundError, ImportError) as e:
        _print_missing_deps(e)
        sys.exit(1)

    use_enhanced, er_extra = _query_engine_rag_options(llm_config_path, args.enhanced_rag)
    latency_mode = args.latency or os.environ.get("CODE_ATLAS_LATENCY_MODE", "").strip() or None
    if latency_mode and latency_mode not in ("fast", "balanced", "quality"):
        latency_mode = None
    engine = None
    try:
        engine = QueryEngine(
            vector_db_path=db_path,
            llm_config_path=llm_config_path,
            use_enhanced_rag=use_enhanced,
            enhanced_rag_config=er_extra,
            latency_mode=latency_mode,
        )
    except QdrantEmbeddedLockError as e:
        print(f"\n{e}", file=sys.stderr)
        sys.exit(1)

    _active_engine = engine

    def _graceful_signal(signum, _frame):
        if _active_engine is not None:
            _active_engine.shutdown()
        sys.exit(128 + signum)

    try:
        signal.signal(signal.SIGTERM, _graceful_signal)
    except (ValueError, OSError):
        pass

    try:
        if args.search:
            results = engine.search_only(args.search, n_results=10, repo_filter=args.repo)
            format_search_results(results)
            return

        if args.query:
            try:
                result = engine.query(
                    question=args.query,
                    repo_filter=args.repo,
                    provider=args.provider,
                    temperature=0.3,
                )
                print(result.format_answer())
            except Exception as e:
                print(f"❌ Error: {e}")
            return

        interactive_mode(engine, initial_repo=args.repo)
    finally:
        if engine is not None:
            engine.shutdown()


if __name__ == "__main__":
    main()
