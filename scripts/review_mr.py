#!/usr/bin/env python3
"""
Review a GitLab Merge Request using RAG context + LLM.

Usage:
    python3 scripts/review_mr.py https://gitlab.com/group/project/-/merge_requests/123
    python3 scripts/review_mr.py https://gitlab.com/group/project/-/merge_requests/123 --verbose
    python3 scripts/review_mr.py https://gitlab.com/group/project/-/merge_requests/123 --no-llm

Requires:
    GITLAB_TOKEN env var (Personal Access Token with api + read_api scope)
"""

import sys
import os
import re
import json
import logging
import argparse
import urllib.request
import urllib.parse
import urllib.error
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


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


def parse_mr_url(url: str) -> dict:
    """
    Parse GitLab MR URL into components.

    Supports:
        https://gitlab.com/group/project/-/merge_requests/123
        https://gitlab.company.com/group/subgroup/project/-/merge_requests/456
    """
    # Strip trailing /diffs, /commits, /pipelines etc.
    clean_url = re.sub(r'/-/merge_requests/(\d+)/.*', r'/-/merge_requests/\1', url.strip())
    pattern = r'(https?://[^/]+)/(.+?)/-/merge_requests/(\d+)'
    match = re.match(pattern, clean_url)
    if not match:
        return {}
    return {
        "base_url": match.group(1),
        "project_path": match.group(2),
        "mr_iid": int(match.group(3)),
        "encoded_project": urllib.parse.quote(match.group(2), safe=""),
    }


def gitlab_api_get(base_url: str, endpoint: str, token: str) -> dict:
    """Make authenticated GET to GitLab API."""
    url = f"{base_url}/api/v4{endpoint}"
    req = urllib.request.Request(url, headers={
        "PRIVATE-TOKEN": token,
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        raise RuntimeError(f"GitLab API {e.code}: {body[:300]}")


def fetch_mr_info(parsed: dict, token: str) -> dict:
    """Fetch MR metadata (title, description, branches, author)."""
    endpoint = f"/projects/{parsed['encoded_project']}/merge_requests/{parsed['mr_iid']}"
    return gitlab_api_get(parsed["base_url"], endpoint, token)


def fetch_mr_changes(parsed: dict, token: str) -> list:
    """Fetch MR file changes (diffs)."""
    endpoint = f"/projects/{parsed['encoded_project']}/merge_requests/{parsed['mr_iid']}/changes"
    data = gitlab_api_get(parsed["base_url"], endpoint, token)
    return data.get("changes", [])


def fetch_mr_diff_versions(parsed: dict, token: str) -> str:
    """Fetch raw diff text from MR diffs endpoint."""
    endpoint = f"/projects/{parsed['encoded_project']}/merge_requests/{parsed['mr_iid']}/diffs"
    diffs = gitlab_api_get(parsed["base_url"], endpoint, token)
    combined = []
    for d in diffs:
        header = f"--- a/{d.get('old_path', '')}\n+++ b/{d.get('new_path', '')}"
        combined.append(f"{header}\n{d.get('diff', '')}")
    return "\n".join(combined)


def build_unified_diff(changes: list) -> str:
    """Build unified diff text from MR changes."""
    parts = []
    for change in changes:
        old_path = change.get("old_path", "")
        new_path = change.get("new_path", "")
        diff = change.get("diff", "")
        if diff:
            header = f"--- a/{old_path}\n+++ b/{new_path}"
            parts.append(f"{header}\n{diff}")
    return "\n".join(parts)


def detect_repo_name(project_path: str) -> str:
    """Extract repo name from project path (last segment)."""
    return project_path.rstrip("/").split("/")[-1]


def print_mr_summary(mr_info: dict, changes: list):
    """Print MR overview."""
    title = mr_info.get("title", "")
    author = mr_info.get("author", {}).get("name", "unknown")
    source = mr_info.get("source_branch", "")
    target = mr_info.get("target_branch", "")
    state = mr_info.get("state", "")
    description = mr_info.get("description", "") or ""
    labels = mr_info.get("labels", [])
    web_url = mr_info.get("web_url", "")

    files_changed = len(changes)
    additions = sum(c.get("diff", "").count("\n+") for c in changes)
    deletions = sum(c.get("diff", "").count("\n-") for c in changes)

    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.RESET}")
    print(f"{Colors.BOLD}  Merge Request Review{Colors.RESET}")
    print(f"{Colors.CYAN}{'='*60}{Colors.RESET}")
    print(f"\n  {Colors.BOLD}Title:{Colors.RESET}   {title}")
    print(f"  {Colors.BOLD}Author:{Colors.RESET}  {author}")
    print(f"  {Colors.BOLD}Branch:{Colors.RESET}  {source} -> {target}")
    print(f"  {Colors.BOLD}State:{Colors.RESET}   {state}")
    if labels:
        print(f"  {Colors.BOLD}Labels:{Colors.RESET}  {', '.join(labels)}")
    print(f"  {Colors.BOLD}Link:{Colors.RESET}    {Colors.UNDERLINE}{web_url}{Colors.RESET}")
    print(f"\n  {Colors.BOLD}Changes:{Colors.RESET} {files_changed} files | "
          f"{Colors.GREEN}+{additions}{Colors.RESET} / {Colors.RED}-{deletions}{Colors.RESET}")

    if description:
        desc_short = description[:200] + ("..." if len(description) > 200 else "")
        print(f"\n  {Colors.BOLD}Description:{Colors.RESET}")
        for line in desc_short.split("\n"):
            print(f"    {Colors.DIM}{line}{Colors.RESET}")

    print(f"\n  {Colors.BOLD}Changed files:{Colors.RESET}")
    for c in changes:
        new_file = c.get("new_file", False)
        deleted = c.get("deleted_file", False)
        renamed = c.get("renamed_file", False)
        path = c.get("new_path", c.get("old_path", "?"))

        if new_file:
            tag = f"{Colors.GREEN}[NEW]{Colors.RESET}"
        elif deleted:
            tag = f"{Colors.RED}[DEL]{Colors.RESET}"
        elif renamed:
            tag = f"{Colors.YELLOW}[REN]{Colors.RESET}"
        else:
            tag = f"{Colors.BLUE}[MOD]{Colors.RESET}"
        print(f"    {tag} {path}")


def print_review_results(review: dict):
    """Print formatted review results."""
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.RESET}")
    print(f"{Colors.BOLD}  Review Results{Colors.RESET}")
    print(f"{Colors.CYAN}{'='*60}{Colors.RESET}")

    # Summary
    print(f"\n  {Colors.BOLD}Summary:{Colors.RESET} {review.get('summary', 'N/A')}")

    # Approval
    approval = review.get("approval", "UNKNOWN")
    if approval == "APPROVE":
        color = Colors.GREEN
        icon = "APPROVED"
    elif approval == "REQUEST_CHANGES":
        color = Colors.RED
        icon = "CHANGES REQUESTED"
    else:
        color = Colors.YELLOW
        icon = approval
    print(f"  {Colors.BOLD}Verdict:{Colors.RESET} {color}{Colors.BOLD}{icon}{Colors.RESET}")

    # Issues
    issues = review.get("issues", [])
    if issues:
        print(f"\n  {Colors.BOLD}{Colors.RED}Issues ({len(issues)}):{Colors.RESET}")
        for issue in issues:
            sev = issue.get("severity", "?")
            if sev == "high":
                sev_color = Colors.RED
            elif sev == "medium":
                sev_color = Colors.YELLOW
            else:
                sev_color = Colors.DIM
            print(f"    {sev_color}[{sev.upper()}]{Colors.RESET} {issue.get('msg', '')}"
                  f" {Colors.DIM}(line ~{issue.get('line', '?')}){Colors.RESET}")
    else:
        print(f"\n  {Colors.GREEN}No static issues found.{Colors.RESET}")

    # Suggestions
    suggestions = review.get("suggestions", [])
    if suggestions:
        print(f"\n  {Colors.BOLD}Suggestions:{Colors.RESET}")
        for s in suggestions:
            print(f"    {Colors.YELLOW}*{Colors.RESET} {s}")

    # Similar patterns in codebase
    patterns = review.get("similar_patterns", [])
    if patterns:
        print(f"\n  {Colors.BOLD}Similar code in codebase:{Colors.RESET}")
        for p in patterns:
            print(f"    {Colors.CYAN}{p['repo']}{Colors.RESET}/{p['file']} "
                  f"(relevance: {p.get('relevance', 0):.0%})")

    # LLM review
    llm_review = review.get("llm_review")
    if llm_review:
        provider = review.get("provider", "?")
        model = review.get("model", "?")
        print(f"\n  {Colors.BOLD}{Colors.MAGENTA}AI Review ({provider}/{model}):{Colors.RESET}")
        print(f"  {Colors.DIM}{'─'*56}{Colors.RESET}")
        for line in llm_review.split("\n"):
            print(f"  {line}")
        print(f"  {Colors.DIM}{'─'*56}{Colors.RESET}")
    elif review.get("llm_note"):
        print(f"\n  {Colors.DIM}{review['llm_note']}{Colors.RESET}")

    # Timing
    print(f"\n  {Colors.DIM}Review completed in {review.get('time_ms', 0)}ms{Colors.RESET}")


def main():
    parser = argparse.ArgumentParser(description="Review a GitLab MR using RAG + LLM")
    parser.add_argument("url", help="GitLab MR URL (e.g. https://gitlab.com/group/project/-/merge_requests/123)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM review (static + RAG only)")
    parser.add_argument("--token", help="GitLab token (default: GITLAB_TOKEN env var)")
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    # Get GitLab token
    token = args.token or os.environ.get("GITLAB_TOKEN")
    if not token:
        try:
            config_path = Path(__file__).parent.parent / "config" / "config.json"
            if config_path.exists():
                with open(config_path) as f:
                    token = json.load(f).get("gitlab_token")
        except Exception:
            pass

    if not token:
        print(f"{Colors.RED}Error: No GitLab token found.{Colors.RESET}")
        print(f"Set it via: export GITLAB_TOKEN=glpat-xxxxxxxxxxxx")
        print(f"Or pass: --token glpat-xxxxxxxxxxxx")
        sys.exit(1)

    # Parse MR URL
    parsed = parse_mr_url(args.url)
    if not parsed:
        print(f"{Colors.RED}Error: Could not parse MR URL.{Colors.RESET}")
        print(f"Expected format: https://gitlab.com/group/project/-/merge_requests/123")
        sys.exit(1)

    repo_name = detect_repo_name(parsed["project_path"])

    # Fetch MR info
    print(f"\n{Colors.DIM}Fetching MR #{parsed['mr_iid']} from {parsed['project_path']}...{Colors.RESET}")

    try:
        mr_info = fetch_mr_info(parsed, token)
    except RuntimeError as e:
        print(f"{Colors.RED}Error fetching MR info: {e}{Colors.RESET}")
        sys.exit(1)

    # Fetch changes
    try:
        changes = fetch_mr_changes(parsed, token)
    except RuntimeError as e:
        print(f"{Colors.RED}Error fetching MR changes: {e}{Colors.RESET}")
        sys.exit(1)

    if not changes:
        print(f"{Colors.YELLOW}No file changes found in this MR.{Colors.RESET}")
        sys.exit(0)

    # Print MR summary
    print_mr_summary(mr_info, changes)

    # Build diff
    diff_text = build_unified_diff(changes)
    if not diff_text.strip():
        print(f"\n{Colors.YELLOW}No diff content to review.{Colors.RESET}")
        sys.exit(0)

    # Skip LLM if requested
    if args.no_llm:
        os.environ["SKIP_LLM"] = "1"

    # Run the review using RAG context
    print(f"\n{Colors.DIM}Running RAG-powered code review...{Colors.RESET}")

    from src.ai.rag import RAGRetriever
    from src.tools.pr_reviewer import review_diff

    retriever = RAGRetriever(persist_directory="./data/qdrant_db")
    review = review_diff(retriever, diff_text, repo_name)

    # Print results
    print_review_results(review)

    print(f"\n{Colors.GREEN}Done.{Colors.RESET}\n")


if __name__ == "__main__":
    main()
