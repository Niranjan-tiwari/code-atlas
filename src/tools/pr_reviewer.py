"""
PR Auto-Reviewer: Reviews code diffs using RAG context + LLM.
Can be triggered by GitLab webhook or manual diff input.
"""

import logging
import time
from typing import Dict, Optional

logger = logging.getLogger("pr_reviewer")


def review_diff(retriever, diff_text: str, repo_name: str = "", max_context: int = 5) -> dict:
    """
    Review a code diff using RAG context.
    
    Args:
        retriever: RAGRetriever instance
        diff_text: Git diff text
        repo_name: Repository name for context
        max_context: Number of context snippets to retrieve
    """
    t = time.time()
    
    if not diff_text.strip():
        return {"error": "Empty diff"}
    
    # Extract key terms from diff for RAG search
    search_terms = _extract_diff_keywords(diff_text)
    
    # Find relevant code patterns
    context_results = []
    for term in search_terms[:3]:
        results = retriever.search_code(term, n_results=3, repo_filter=repo_name or None)
        context_results.extend(results)
    
    # Build review
    review = _static_review(diff_text, context_results)
    
    # Try LLM review if available (skip in fast mode)
    try:
        import os
        if os.environ.get("SKIP_LLM"):
            raise RuntimeError("LLM skipped")
        from src.ai.llm.manager import LLMManager
        llm = LLMManager()
        if llm.get_available_providers():
            context_str = "\n".join(
                f"[{r['repo']}/{r['file']}]: {r['code'][:200]}" for r in context_results[:5]
            )
            prompt = f"""Review this code diff. Focus on: bugs, security issues, Go best practices, error handling.

DIFF:
{diff_text[:3000]}

EXISTING PATTERNS IN CODEBASE:
{context_str[:2000]}

Provide:
1. Summary (1-2 sentences)
2. Issues found (if any)
3. Suggestions
4. Approval: APPROVE / REQUEST_CHANGES / COMMENT"""
            
            response = llm.generate(prompt, max_tokens=800, temperature=0.3)
            review["llm_review"] = response.content
            review["model"] = response.model
            review["provider"] = response.provider
    except Exception as e:
        review["llm_note"] = f"LLM review skipped: {str(e)[:100]}"
    
    review["time_ms"] = round((time.time() - t) * 1000)
    return review


def _static_review(diff_text: str, context: list) -> dict:
    """Static code review (no LLM needed)"""
    issues = []
    suggestions = []
    
    lines = diff_text.split("\n")
    added = [l[1:] for l in lines if l.startswith("+") and not l.startswith("+++")]
    removed = [l[1:] for l in lines if l.startswith("-") and not l.startswith("---")]
    
    # Check for common issues
    for i, line in enumerate(added):
        # Hardcoded secrets
        if any(kw in line.lower() for kw in ["password", "secret", "api_key", "token"]):
            if "=" in line and not line.strip().startswith("//") and not line.strip().startswith("#"):
                issues.append({"type": "security", "line": i, "msg": "Possible hardcoded secret", "severity": "high"})
        
        # Empty error handling in Go
        if "if err != nil {" in line:
            # Check if next line returns or handles the error
            pass
        
        # TODO/FIXME/HACK
        for tag in ["TODO", "FIXME", "HACK", "XXX"]:
            if tag in line:
                issues.append({"type": "quality", "line": i, "msg": f"Contains {tag}", "severity": "low"})
        
        # Large functions (rough check)
        if "func " in line and "{" in line:
            suggestions.append(f"New function added - ensure it has error handling and tests")
        
        # fmt.Println in Go (should use logger)
        if "fmt.Println" in line or "fmt.Printf" in line:
            issues.append({"type": "quality", "line": i, "msg": "Use structured logger instead of fmt.Print", "severity": "medium"})
    
    # Check against patterns in codebase
    pattern_matches = []
    for ctx in context[:3]:
        pattern_matches.append({
            "repo": ctx.get("repo", ""),
            "file": ctx.get("file", ""),
            "relevance": round(1 - (ctx.get("distance", 1) or 1), 2)
        })
    
    return {
        "summary": f"Reviewed {len(added)} added, {len(removed)} removed lines",
        "issues": issues,
        "issue_count": len(issues),
        "suggestions": suggestions,
        "similar_patterns": pattern_matches,
        "approval": "REQUEST_CHANGES" if any(i["severity"] == "high" for i in issues) else "APPROVE"
    }


def _extract_diff_keywords(diff_text: str) -> list:
    """Extract meaningful keywords from a diff"""
    import re
    
    # Get function names, types, packages
    keywords = set()
    for line in diff_text.split("\n"):
        if line.startswith("+") or line.startswith("-"):
            # Go function names
            match = re.search(r'func\s+(?:\([^)]+\)\s+)?(\w+)', line)
            if match:
                keywords.add(match.group(1))
            # Package names
            match = re.search(r'package\s+(\w+)', line)
            if match:
                keywords.add(match.group(1))
            # Import paths
            match = re.search(r'"([^"]+)"', line)
            if match and "/" in match.group(1):
                keywords.add(match.group(1).split("/")[-1])
    
    return list(keywords)[:5] or ["error handling"]


def handle_gitlab_mr_webhook(payload: dict, retriever) -> dict:
    """Handle GitLab MR webhook and auto-review"""
    mr = payload.get("object_attributes", {})
    project = payload.get("project", {})
    
    title = mr.get("title", "")
    description = mr.get("description", "")
    source_branch = mr.get("source_branch", "")
    target_branch = mr.get("target_branch", "")
    repo_name = project.get("name", "")
    
    # Get the diff (would need GitLab API call in production)
    diff_text = mr.get("last_commit", {}).get("message", "")
    
    if not diff_text:
        return {"note": "No diff available from webhook payload"}
    
    review = review_diff(retriever, diff_text, repo_name)
    review["mr_title"] = title
    review["source_branch"] = source_branch
    review["target_branch"] = target_branch
    
    return review
