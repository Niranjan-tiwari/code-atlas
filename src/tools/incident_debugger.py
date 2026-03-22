"""
Incident Debugger: Paste an error log, find the relevant code path,
and suggest fixes based on similar patterns in the codebase.
"""

import re
import logging
from typing import Dict, List

logger = logging.getLogger("incident_debugger")


def debug_error(retriever, error_text: str) -> dict:
    """
    Debug an error by finding relevant code in the codebase.
    
    Args:
        retriever: RAGRetriever instance
        error_text: Error log/stack trace text
    """
    if not error_text.strip():
        return {"error": "Empty error text"}
    
    # Extract useful info from error
    extracted = _extract_error_info(error_text)
    
    # Search for relevant code
    search_results = {}
    
    # Search by function names found in stack trace
    for func in extracted.get("functions", [])[:3]:
        results = retriever.search_code(func, n_results=3)
        if results:
            search_results[f"func:{func}"] = [{
                "repo": r["repo"], "file": r["file"],
                "score": round(r.get("hybrid_score", 0), 3),
                "preview": r.get("code", "")[:150]
            } for r in results]
    
    # Search by file paths
    for fpath in extracted.get("files", [])[:3]:
        results = retriever.search_code(fpath.split("/")[-1].replace(".go", ""), n_results=3)
        if results:
            search_results[f"file:{fpath}"] = [{
                "repo": r["repo"], "file": r["file"],
                "score": round(r.get("hybrid_score", 0), 3),
                "preview": r.get("code", "")[:150]
            } for r in results]
    
    # Search by error message
    if extracted.get("error_message"):
        results = retriever.search_code(extracted["error_message"][:100], n_results=5)
        search_results["error_message"] = [{
            "repo": r["repo"], "file": r["file"],
            "score": round(r.get("hybrid_score", 0), 3),
            "preview": r.get("code", "")[:150]
        } for r in results]
    
    # Find similar error handling patterns
    error_patterns = retriever.search_code("error handling return err", n_results=5)
    
    # Build analysis
    analysis = {
        "extracted": extracted,
        "relevant_code": search_results,
        "error_patterns": [{
            "repo": r["repo"], "file": r["file"],
            "preview": r.get("code", "")[:100]
        } for r in error_patterns[:3]],
        "suggestions": _generate_suggestions(extracted, search_results)
    }
    
    # Try LLM analysis
    try:
        import os
        if os.environ.get("SKIP_LLM"):
            raise RuntimeError("LLM skipped")
        from src.ai.llm.manager import LLMManager
        llm = LLMManager()
        if llm.get_available_providers():
            context = "\n".join(
                f"[{k}]: {v[0]['preview']}" for k, v in search_results.items() if v
            )
            prompt = f"""Analyze this error and suggest a fix based on the codebase context.

ERROR:
{error_text[:1500]}

RELEVANT CODE FROM CODEBASE:
{context[:2000]}

Provide:
1. Root cause analysis
2. Affected code path
3. Suggested fix
4. Prevention strategy"""
            
            response = llm.generate(prompt, max_tokens=600, temperature=0.3)
            analysis["ai_analysis"] = response.content
    except Exception:
        pass
    
    return analysis


def _extract_error_info(error_text: str) -> dict:
    """Extract structured info from error text"""
    info = {
        "error_type": "",
        "error_message": "",
        "functions": [],
        "files": [],
        "line_numbers": [],
        "packages": []
    }
    
    lines = error_text.split("\n")
    
    for line in lines:
        line = line.strip()
        
        # Go panic/error
        if line.startswith("panic:") or line.startswith("error:"):
            info["error_message"] = line.split(":", 1)[-1].strip()
            info["error_type"] = line.split(":")[0]
        
        # Go stack trace: goroutine, file:line
        match = re.search(r'(\S+\.go):(\d+)', line)
        if match:
            info["files"].append(match.group(1))
            info["line_numbers"].append(int(match.group(2)))
        
        # Function names
        match = re.search(r'(\w+)\.(\w+)\(', line)
        if match:
            info["packages"].append(match.group(1))
            info["functions"].append(match.group(2))
        
        # Python traceback
        if "File " in line:
            match = re.search(r'File "([^"]+)", line (\d+)', line)
            if match:
                info["files"].append(match.group(1))
                info["line_numbers"].append(int(match.group(2)))
        
        # Generic error patterns
        if not info["error_message"]:
            for prefix in ["Error:", "ERROR:", "Exception:", "FATAL:"]:
                if prefix in line:
                    info["error_message"] = line.split(prefix, 1)[-1].strip()[:200]
                    info["error_type"] = prefix.rstrip(":")
                    break
    
    # Deduplicate
    info["functions"] = list(dict.fromkeys(info["functions"]))
    info["files"] = list(dict.fromkeys(info["files"]))
    info["packages"] = list(dict.fromkeys(info["packages"]))
    
    return info


def _generate_suggestions(extracted: dict, search_results: dict) -> list:
    """Generate fix suggestions based on findings"""
    suggestions = []
    
    if extracted.get("error_type") == "panic":
        suggestions.append("Add nil checks before dereferencing pointers")
        suggestions.append("Add recover() in goroutines to prevent crashes")
    
    if "timeout" in extracted.get("error_message", "").lower():
        suggestions.append("Increase timeout or add context.WithTimeout")
        suggestions.append("Check network connectivity and service health")
    
    if "connection refused" in extracted.get("error_message", "").lower():
        suggestions.append("Verify the target service is running")
        suggestions.append("Check connection pool settings and retry logic")
    
    if any("redis" in f.lower() for f in extracted.get("files", [])):
        suggestions.append("Check Redis connection pool and TTL settings")
    
    if not suggestions:
        suggestions.append("Check the error handling in the identified functions")
        suggestions.append("Add structured logging around the error path")
    
    return suggestions
