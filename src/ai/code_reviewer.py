"""
AI-powered Code Review module using RAG + LLM.

Analyzes code changes (git diff) against the existing codebase patterns
retrieved from the vector database, and provides review feedback via LLM.

Uses:
  - RAG retriever to find similar/related code in the indexed repos
  - LLM to analyze the diff and provide review comments
  - Falls back gracefully if no LLM API key is configured
"""

import os
import subprocess
import logging
from typing import Dict, Optional, List
from pathlib import Path


logger = logging.getLogger("parallel_repo_worker.code_reviewer")


class CodeReviewer:
    """AI-powered code reviewer using RAG context + LLM analysis"""
    
    def __init__(self):
        self._rag_retriever = None
        self._llm_manager = None
    
    @property
    def rag_retriever(self):
        """Lazy-load RAG retriever"""
        if self._rag_retriever is None:
            try:
                from .rag import RAGRetriever
                self._rag_retriever = RAGRetriever()
            except Exception as e:
                logger.warning(f"Could not load RAG retriever: {e}")
        return self._rag_retriever
    
    @property
    def llm_manager(self):
        """Lazy-load LLM manager"""
        if self._llm_manager is None:
            try:
                from .llm.manager import LLMManager
                self._llm_manager = LLMManager()
            except Exception as e:
                logger.warning(f"Could not load LLM manager: {e}")
        return self._llm_manager
    
    def review_changes(self, repo_path: str, task=None) -> Optional[Dict]:
        """
        Review code changes in a repository.
        
        Workflow:
          1. Get the git diff of staged/unstaged changes
          2. Retrieve related code patterns from RAG
          3. Send diff + context to LLM for review
          4. Return structured review feedback
        
        Args:
            repo_path: Absolute path to the repository
            task: Optional Task object with context about what was changed
            
        Returns:
            {
                "summary": str,         # One-line summary
                "issues": [             # List of issues found
                    {
                        "severity": "error" | "warning" | "suggestion",
                        "file": str,
                        "message": str
                    }
                ],
                "approval": "approve" | "request_changes" | "comment",
                "details": str          # Full review text from LLM
            }
        """
        # Step 1: Get the diff
        diff = self._get_diff(repo_path)
        if not diff:
            return {
                "summary": "No changes to review",
                "issues": [],
                "approval": "approve",
                "details": "No diff found."
            }
        
        # Step 2: Get RAG context (related code patterns)
        rag_context = self._get_rag_context(repo_path, diff, task)
        
        # Step 3: Run LLM review
        review = self._llm_review(diff, rag_context, repo_path, task)
        
        return review
    
    def _get_diff(self, repo_path: str) -> str:
        """Get git diff of current changes"""
        try:
            # Try staged changes first
            result = subprocess.run(
                ["git", "diff", "--cached", "--no-color"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=30
            )
            diff = result.stdout.strip()
            
            if not diff:
                # Fall back to unstaged changes
                result = subprocess.run(
                    ["git", "diff", "--no-color"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                diff = result.stdout.strip()
            
            if not diff:
                # Show all changes including untracked files
                result = subprocess.run(
                    ["git", "status", "--short"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.stdout.strip():
                    diff = f"[New/untracked files]\n{result.stdout.strip()}"
            
            # Truncate if too long (LLMs have context limits)
            max_diff_len = 8000
            if len(diff) > max_diff_len:
                diff = diff[:max_diff_len] + f"\n\n... [diff truncated, {len(diff)} total chars]"
            
            return diff
            
        except Exception as e:
            logger.warning(f"Could not get diff: {e}")
            return ""
    
    def _get_rag_context(self, repo_path: str, diff: str, task=None) -> str:
        """Retrieve related code patterns from the vector database"""
        if not self.rag_retriever:
            return ""
        
        try:
            repo_name = os.path.basename(repo_path)
            
            # Build a search query from the diff and task description
            query_parts = []
            if task and task.description:
                query_parts.append(task.description)
            
            # Extract file names from diff
            changed_files = self._extract_files_from_diff(diff)
            if changed_files:
                query_parts.append(f"files: {', '.join(changed_files[:5])}")
            
            if not query_parts:
                # Use first few lines of diff as query
                query_parts.append(diff[:500])
            
            query = " ".join(query_parts)
            
            # Search for related code
            results = self.rag_retriever.search_code(
                query=query,
                n_results=5,
                repo_filter=repo_name
            )
            
            if not results:
                # Try without repo filter
                results = self.rag_retriever.search_code(
                    query=query,
                    n_results=3
                )
            
            if results:
                context_parts = ["## Related code patterns from the codebase:\n"]
                for i, r in enumerate(results[:5], 1):
                    context_parts.append(
                        f"### {i}. {r.get('repo', '?')}/{r.get('file', '?')}\n"
                        f"```\n{r.get('code', '')[:500]}\n```\n"
                    )
                return "\n".join(context_parts)
            
            return ""
            
        except Exception as e:
            logger.warning(f"RAG context retrieval failed: {e}")
            return ""
    
    def _extract_files_from_diff(self, diff: str) -> List[str]:
        """Extract file paths from a git diff"""
        files = []
        for line in diff.split("\n"):
            if line.startswith("+++ b/"):
                files.append(line[6:])
            elif line.startswith("--- a/"):
                files.append(line[6:])
        return list(set(files))
    
    def _llm_review(self, diff: str, rag_context: str, repo_path: str,
                    task=None) -> Dict:
        """Send diff + context to LLM for code review"""
        
        # If no LLM available, do a basic static review
        if not self.llm_manager or not self.llm_manager.get_available_providers():
            return self._static_review(diff, repo_path)
        
        repo_name = os.path.basename(repo_path)
        task_desc = task.description if task else "Unknown task"
        jira_id = task.jira_id if task and task.jira_id else ""
        
        system_prompt = """You are a senior code reviewer. Review the following code changes (git diff) and provide concise, actionable feedback.

Your review should:
1. Check for bugs, logic errors, or potential crashes
2. Check if the code follows the patterns established in the existing codebase (provided as context)
3. Check for security issues (hardcoded secrets, SQL injection, etc.)
4. Check for performance issues
5. Suggest improvements if any

Be concise. Focus only on real issues, not style nitpicks.

Respond in this exact JSON format:
{
    "summary": "One line summary of the review",
    "issues": [
        {"severity": "error|warning|suggestion", "file": "filename", "message": "description"}
    ],
    "approval": "approve|request_changes|comment"
}

If the code looks good, return approval: "approve" with an empty issues list."""

        user_prompt = f"""## Task
Repository: {repo_name}
Task: {task_desc}
{f"Jira: {jira_id}" if jira_id else ""}

## Code Changes (Git Diff)
```diff
{diff}
```

{rag_context}

Please review these changes."""

        try:
            response = self.llm_manager.generate(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.2,
                max_tokens=2000
            )
            
            if response and response.content:
                return self._parse_llm_review(response.content)
            
        except Exception as e:
            logger.warning(f"LLM review failed: {e}")
        
        return self._static_review(diff, repo_path)
    
    def _parse_llm_review(self, content: str) -> Dict:
        """Parse LLM response into structured review format"""
        import json
        
        # Try to extract JSON from the response
        try:
            # Find JSON block in response
            json_start = content.find("{")
            json_end = content.rfind("}") + 1
            
            if json_start >= 0 and json_end > json_start:
                json_str = content[json_start:json_end]
                review = json.loads(json_str)
                
                # Validate structure
                return {
                    "summary": review.get("summary", "Review complete"),
                    "issues": review.get("issues", []),
                    "approval": review.get("approval", "comment"),
                    "details": content
                }
        except (json.JSONDecodeError, KeyError):
            pass
        
        # Fallback: treat entire response as the review
        return {
            "summary": content[:100] if content else "Review complete",
            "issues": [],
            "approval": "comment",
            "details": content
        }
    
    def _static_review(self, diff: str, repo_path: str) -> Dict:
        """
        Basic static analysis when LLM is not available.
        Checks for common issues without AI.
        """
        issues = []
        
        lines = diff.split("\n")
        for i, line in enumerate(lines):
            # Only check added lines
            if not line.startswith("+") or line.startswith("+++"):
                continue
            
            content = line[1:]  # Remove the '+' prefix
            
            # Check for hardcoded secrets
            secret_patterns = [
                ("password", "Possible hardcoded password"),
                ("api_key", "Possible hardcoded API key"),
                ("secret", "Possible hardcoded secret"),
                ("token", "Possible hardcoded token"),
                ("private_key", "Possible hardcoded private key"),
            ]
            content_lower = content.lower()
            for pattern, message in secret_patterns:
                if pattern in content_lower and ("=" in content or ":" in content):
                    # Avoid false positives: skip comments, variable declarations without values
                    if not content.strip().startswith("//") and not content.strip().startswith("#"):
                        issues.append({
                            "severity": "warning",
                            "file": "unknown",
                            "message": f"{message} (line contains '{pattern}')"
                        })
                    break
            
            # Check for TODO/FIXME left in code
            if "TODO" in content or "FIXME" in content or "HACK" in content:
                issues.append({
                    "severity": "suggestion",
                    "file": "unknown",
                    "message": f"TODO/FIXME found: {content.strip()[:80]}"
                })
            
            # Check for debug prints
            debug_patterns = ["fmt.Println", "console.log", "print(", "log.Print"]
            for dp in debug_patterns:
                if dp in content and not content.strip().startswith("//"):
                    issues.append({
                        "severity": "suggestion",
                        "file": "unknown",
                        "message": f"Debug statement found: {dp}"
                    })
                    break
        
        # Deduplicate
        seen = set()
        unique_issues = []
        for issue in issues:
            key = issue["message"]
            if key not in seen:
                seen.add(key)
                unique_issues.append(issue)
        
        if unique_issues:
            summary = f"Static review: {len(unique_issues)} issue(s) found"
            approval = "comment"
        else:
            summary = "Static review: no issues found"
            approval = "approve"
        
        return {
            "summary": summary,
            "issues": unique_issues[:20],  # Limit output
            "approval": approval,
            "details": f"Basic static analysis (no LLM configured). Found {len(unique_issues)} potential issues."
        }
