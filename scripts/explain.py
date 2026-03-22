#!/usr/bin/env python3
"""
Explain code, functions, or entire repos - with optional architecture diagram.

Usage:
  # Explain how a repo works (end-to-end)
  python3 scripts/explain.py "how whatsapp_segregator works"
  python3 scripts/explain.py "how does whatsapp_segregator repo work" --repo whatsapp-segregator --diagram

  # Explain a function or logic
  python3 scripts/explain.py "what does ProcessMessage do in whatsapp-segregator"
  python3 scripts/explain.py "explain the error handling flow" --repo go-es-gateway

  # With Mermaid architecture diagram
  python3 scripts/explain.py "how whatsapp_segregator works" --diagram

  # Non-interactive (for scripting)
  python3 scripts/explain.py -q "how the webhook flow works"
"""

import sys
import os
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ai.rag import RAGRetriever
from src.tools.repo_explainer import explain

# Colors
class C:
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"


def print_explanation(result: dict):
    """Print explanation with optional diagram"""
    if result.get("error"):
        print(f"\n{C.RED}❌ {result['error']}{C.RESET}")
        return
    
    text = result.get("explanation", "")
    if not text:
        return
    
    print(f"\n{C.BOLD}{C.GREEN}📝 Explanation:{C.RESET}\n")
    print(text)
    
    diagram = result.get("diagram")
    if diagram:
        print(f"\n{C.BOLD}{C.CYAN}📐 Architecture Diagram (Mermaid):{C.RESET}\n")
        print("```mermaid")
        print(diagram)
        print("```")
        print(f"\n{C.DIM}Tip: Paste the diagram into https://mermaid.live to render{C.RESET}")
    
    sources = result.get("sources", [])
    if sources:
        print(f"\n{C.BOLD}📚 Sources ({len(sources)}):{C.RESET}")
        seen = set()
        for s in sources[:10]:
            key = f"{s['repo']}/{s['file']}"
            if key not in seen:
                seen.add(key)
                print(f"  • {s['repo']}/{s['file']}")
    
    if result.get("provider"):
        print(f"\n{C.DIM}⚡ {result['provider']}/{result['model']}{C.RESET}")


def main():
    parser = argparse.ArgumentParser(
        description="Explain code, functions, or entire repos with optional architecture diagram"
    )
    parser.add_argument(
        "question",
        nargs="?",
        help="What to explain (e.g. 'how whatsapp_segregator works', 'what does ProcessMessage do')",
    )
    parser.add_argument(
        "-q", "--query",
        help="Question (alternative to positional)",
    )
    parser.add_argument(
        "-r", "--repo",
        help="Limit to specific repo (e.g. whatsapp-segregator)",
    )
    parser.add_argument(
        "-d", "--diagram",
        action="store_true",
        help="Generate Mermaid architecture diagram",
    )
    parser.add_argument(
        "-n", "--context",
        type=int,
        default=15,
        help="Number of code chunks to retrieve (default: 15)",
    )
    parser.add_argument(
        "--db-path",
        default="./data/vector_db",
        help="Vector DB path",
    )
    
    args = parser.parse_args()
    
    question = args.question or args.query
    if not question:
        print(__doc__)
        print("\nExamples:")
        print('  python3 scripts/explain.py "how whatsapp_segregator works" --diagram')
        print('  python3 scripts/explain.py "what does ProcessMessage do" -r whatsapp-segregator')
        sys.exit(1)
    
    print(f"{C.CYAN}{C.BOLD}🔍 Explain: {question}{C.RESET}")
    
    print(f"\n{C.DIM}Loading retriever & fetching context...{C.RESET}")
    
    retriever = RAGRetriever(persist_directory=args.db_path)
    
    # Auto-detect repo name from question if no explicit --repo flag
    repo = args.repo
    if not repo:
        detected = retriever.detect_repo_in_query(question)
        if detected:
            repo = detected
            print(f"{C.YELLOW}🎯 Auto-detected repo: {detected}{C.RESET}")
    
    if repo:
        print(f"{C.DIM}   Repo filter: {repo}{C.RESET}")
    
    result = explain(
        retriever=retriever,
        question=question,
        repo_filter=repo,
        n_context=args.context,
        include_diagram=args.diagram,
    )
    
    print_explanation(result)
    
    if result.get("error"):
        sys.exit(1)


if __name__ == "__main__":
    main()
