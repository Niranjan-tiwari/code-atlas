"""
Documentation Generator: Auto-generate docs from indexed code using RAG.
Generates README summaries, API docs, and architecture overviews.
"""

import logging
from typing import Dict, Optional

logger = logging.getLogger("doc_generator")


def generate_docs(retriever, repo_name: str) -> dict:
    """
    Generate documentation for a repo.
    
    Args:
        retriever: RAGRetriever instance
        repo_name: Name of the repo to document
    """
    if not repo_name:
        return {"error": "Missing repo_name"}
    
    # Search for key files
    main_files = retriever.search_code("main func init", n_results=5, repo_filter=repo_name)
    handlers = retriever.search_code("handler router endpoint", n_results=5, repo_filter=repo_name)
    models = retriever.search_code("struct type model", n_results=5, repo_filter=repo_name)
    configs = retriever.search_code("config env variable", n_results=3, repo_filter=repo_name)
    
    # Build documentation structure
    doc = {
        "repo": repo_name,
        "sections": {}
    }
    
    # Overview
    all_files = set()
    all_packages = set()
    for results in [main_files, handlers, models, configs]:
        for r in results:
            all_files.add(r.get("file", ""))
            pkg = r.get("code", "").split("\n")[0] if r.get("code") else ""
            if pkg.startswith("package "):
                all_packages.add(pkg.replace("package ", "").strip())
    
    doc["sections"]["overview"] = {
        "files_found": len(all_files),
        "packages": list(all_packages),
        "key_files": list(all_files)[:10]
    }
    
    # Entry points
    entry_points = []
    for r in main_files:
        code = r.get("code", "")
        if "func main()" in code or "func init()" in code:
            entry_points.append({
                "file": r.get("file", ""),
                "preview": code[:200]
            })
    doc["sections"]["entry_points"] = entry_points
    
    # API Endpoints
    endpoints = []
    for r in handlers:
        code = r.get("code", "")
        for line in code.split("\n"):
            line = line.strip()
            if any(method in line for method in [".GET(", ".POST(", ".PUT(", ".DELETE(",
                    "HandleFunc(", "Handle(", ".Get(", ".Post("]):
                endpoints.append({
                    "file": r.get("file", ""),
                    "line": line[:100]
                })
    doc["sections"]["endpoints"] = endpoints[:20]
    
    # Data Models
    structs = []
    for r in models:
        code = r.get("code", "")
        import re
        for match in re.finditer(r'type\s+(\w+)\s+struct\s*\{', code):
            structs.append({
                "name": match.group(1),
                "file": r.get("file", "")
            })
    doc["sections"]["models"] = structs[:20]
    
    # Try LLM summary
    try:
        import os
        if os.environ.get("SKIP_LLM"):
            raise RuntimeError("LLM skipped")
        from src.ai.llm.manager import LLMManager
        llm = LLMManager()
        if llm.get_available_providers():
            context = "\n".join(r.get("code", "")[:300] for r in main_files[:3])
            response = llm.generate(
                f"Write a brief README summary for the '{repo_name}' repository based on this code:\n{context}",
                max_tokens=300, temperature=0.3
            )
            doc["sections"]["ai_summary"] = response.content
    except Exception:
        pass
    
    # Generate markdown
    doc["markdown"] = _build_markdown(doc)
    
    return doc


def _build_markdown(doc: dict) -> str:
    """Build markdown documentation"""
    md = []
    repo = doc.get("repo", "")
    sections = doc.get("sections", {})
    
    md.append(f"# {repo}\n")
    
    if sections.get("ai_summary"):
        md.append(sections["ai_summary"])
        md.append("")
    
    overview = sections.get("overview", {})
    if overview:
        md.append(f"## Overview\n")
        md.append(f"- **Packages**: {', '.join(overview.get('packages', []))}")
        md.append(f"- **Files**: {overview.get('files_found', 0)} indexed")
        md.append("")
    
    entries = sections.get("entry_points", [])
    if entries:
        md.append("## Entry Points\n")
        for e in entries[:5]:
            md.append(f"- `{e['file']}`")
        md.append("")
    
    endpoints = sections.get("endpoints", [])
    if endpoints:
        md.append("## API Endpoints\n")
        for ep in endpoints[:10]:
            md.append(f"- `{ep['line']}`  ({ep['file']})")
        md.append("")
    
    models = sections.get("models", [])
    if models:
        md.append("## Data Models\n")
        for m in models[:10]:
            md.append(f"- `{m['name']}` ({m['file']})")
        md.append("")
    
    return "\n".join(md)
