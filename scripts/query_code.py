#!/usr/bin/env python3
"""
Interactive CLI for querying the codebase using RAG + LLM

Usage:
    python3 scripts/query_code.py                    # Interactive mode
    python3 scripts/query_code.py --query "..."       # Single query
    python3 scripts/query_code.py --search "..."      # Search only (no LLM)
    python3 scripts/query_code.py --repo whatsapp     # Filter to specific repo
    python3 scripts/query_code.py --list-repos        # List indexed repos
    python3 scripts/query_code.py --stats             # Show stats
"""

import sys
import os
import argparse
import logging
import readline
from pathlib import Path

# Enable arrow keys, history, and line editing in interactive input()
readline.parse_and_bind('"\e[A": history-search-backward')
readline.parse_and_bind('"\e[B": history-search-forward')
readline.parse_and_bind('set editing-mode emacs')

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ai.query_engine import QueryEngine


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
  {Colors.GREEN}/provider <name>{Colors.RESET}      - Switch LLM provider (openai/anthropic/gemini)
  {Colors.GREEN}/history{Colors.RESET}              - Show query history
  {Colors.GREEN}/help{Colors.RESET}                 - Show this help
  {Colors.GREEN}/quit{Colors.RESET}                 - Exit

{Colors.BOLD}Examples:{Colors.RESET}
  {Colors.DIM}How does the WhatsApp message routing work?
  /repo whatsapp-segregator
  /explain how whatsapp_segregator works
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


def interactive_mode(engine: QueryEngine, initial_repo: str = None):
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
        print(f"Set API keys: export OPENAI_API_KEY=sk-... (or ANTHROPIC_API_KEY or GEMINI_API_KEY)")
        print()
    
    # Show repo count
    repos = engine.list_repos()
    print(f"{Colors.BOLD}📊 {len(repos)} repositories indexed ({sum(r['chunks'] for r in repos):,} chunks){Colors.RESET}")
    
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
                
                elif cmd == "/provider":
                    if arg:
                        provider_override = arg if arg != "auto" else None
                        print(f"{Colors.GREEN}🤖 Provider: {arg}{Colors.RESET}")
                    else:
                        print(f"{Colors.YELLOW}Usage: /provider <openai|anthropic|gemini|auto>{Colors.RESET}")
                
                elif cmd == "/history":
                    if engine.history:
                        print(f"\n{Colors.BOLD}📜 Query History:{Colors.RESET}")
                        for i, h in enumerate(engine.history, 1):
                            print(f"  {i}. {h['question'][:80]}... ({h['provider']})")
                    else:
                        print(f"{Colors.DIM}No queries yet.{Colors.RESET}")
                
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
                print(f"  export OPENAI_API_KEY=sk-...")
                print(f"  export ANTHROPIC_API_KEY=sk-ant-...")
                print(f"  export GEMINI_API_KEY=AI...")
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
    parser.add_argument("--provider", "-p", help="LLM provider (openai/anthropic/gemini)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    parser.add_argument("--db-path", default="./data/vector_db", help="Vector DB path")
    
    args = parser.parse_args()
    
    setup_logging(args.verbose)
    
    # Initialize engine
    engine = QueryEngine(vector_db_path=args.db_path)
    
    # Handle specific commands
    if args.list_repos:
        format_repos_list(engine.list_repos())
        return
    
    if args.stats:
        stats = engine.get_stats()
        print(f"📊 Repos: {stats['repos_indexed']}, Chunks: {stats['total_chunks']:,}")
        print(f"🤖 Providers: {', '.join(stats['llm']['available_providers'])}")
        return
    
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
                temperature=0.3
            )
            print(result.format_answer())
        except Exception as e:
            print(f"❌ Error: {e}")
        return
    
    # Default: interactive mode
    interactive_mode(engine, initial_repo=args.repo)


if __name__ == "__main__":
    main()
