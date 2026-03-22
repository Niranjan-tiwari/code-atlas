"""
Slack Bot: Ask code questions from Slack.

Usage:
  @codebot search reporting
  @codebot how does error handling work?
  @codebot repos
  @codebot help

Requires: SLACK_BOT_TOKEN and SLACK_SIGNING_SECRET env vars.
For webhook mode, expose the API and set the Slack Events URL.
"""

import os
import json
import logging
import hmac
import hashlib
from typing import Optional

logger = logging.getLogger("slack_bot")


class SlackBot:
    """Simple Slack bot for code search and queries"""
    
    def __init__(self, retriever, llm_manager=None):
        self.retriever = retriever
        self.llm = llm_manager
        self.token = os.environ.get("SLACK_BOT_TOKEN", "")
        self.signing_secret = os.environ.get("SLACK_SIGNING_SECRET", "")
    
    def handle_event(self, payload: dict) -> Optional[dict]:
        """Handle a Slack event (from Events API)"""
        event_type = payload.get("type", "")
        
        # URL verification challenge
        if event_type == "url_verification":
            return {"challenge": payload.get("challenge", "")}
        
        # Message event
        event = payload.get("event", {})
        if event.get("type") == "app_mention" or event.get("type") == "message":
            text = event.get("text", "")
            channel = event.get("channel", "")
            user = event.get("user", "")
            
            # Remove bot mention
            text = text.split(">", 1)[-1].strip() if ">" in text else text
            
            response = self.process_command(text)
            
            if self.token and channel:
                self._send_message(channel, response)
            
            return {"response": response}
        
        return None
    
    def process_command(self, text: str) -> str:
        """Process a command and return response text"""
        text = text.strip()
        
        if not text:
            return self._help()
        
        parts = text.split(maxsplit=1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        
        commands = {
            "search": lambda: self._search(args),
            "find": lambda: self._search(args),
            "repos": lambda: self._repos(),
            "help": lambda: self._help(),
            "deps": lambda: self._deps(args),
            "duplicates": lambda: self._duplicates(),
        }
        
        handler = commands.get(command)
        if handler:
            return handler()
        
        # Default: treat as a search query
        return self._search(text)
    
    def _search(self, query: str) -> str:
        """Search code"""
        if not query:
            return "Usage: `search <query>`\nExample: `search error handling`"
        
        results = self.retriever.search_code(query, n_results=5)
        
        if not results:
            return f"No results for `{query}`"
        
        lines = [f"*{len(results)} results for `{query}`*\n"]
        for i, r in enumerate(results, 1):
            score = round(r.get("hybrid_score", 0), 3)
            lines.append(f"{i}. `{r['repo']}/{r['file']}` (score: {score})")
        
        return "\n".join(lines)
    
    def _repos(self) -> str:
        """List repos"""
        repos = self.retriever.get_available_repos()
        if not repos:
            return "No indexed repos found"
        
        lines = [f"*{len(repos)} indexed repositories*\n"]
        for r in repos[:20]:
            lines.append(f"• `{r['name']}` ({r.get('chunks', '?')} chunks)")
        if len(repos) > 20:
            lines.append(f"...and {len(repos) - 20} more")
        return "\n".join(lines)
    
    def _deps(self, repo: str = "") -> str:
        """Scan dependencies"""
        try:
            from src.tools.dependency_scanner import scan_repo, scan_all
            if repo:
                # Find repo path
                for base in ["/path/to/your/repos"]:
                    from pathlib import Path
                    rp = Path(base) / repo
                    if rp.exists():
                        result = scan_repo(str(rp))
                        total = result["total_deps"]
                        return f"*{repo}*: {total} dependencies ({result['language']})"
                return f"Repo `{repo}` not found locally"
            else:
                result = scan_all()
                lines = [f"*Scanned {result['repos_scanned']} repos, {result['total_unique_deps']} unique deps*\n"]
                for dep in result["most_common_deps"][:10]:
                    lines.append(f"• `{dep['name']}` used by {dep['count']} repos")
                return "\n".join(lines)
        except Exception as e:
            return f"Error scanning deps: {e}"
    
    def _duplicates(self) -> str:
        """Find duplicates"""
        try:
            from src.tools.duplication_finder import find_duplicates
            result = find_duplicates(self.retriever, max_results=5)
            dups = result.get("duplicates", [])
            if not dups:
                return "No duplicates found"
            lines = [f"*{result['count']} potential duplicates found*\n"]
            for d in dups:
                lines.append(f"• {d['similarity']}% similar: `{d['file_a']}` ↔ `{d['file_b']}`")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"
    
    def _help(self) -> str:
        return """*Code Search Bot Commands*

• `search <query>` - Search code across all repos
• `repos` - List indexed repositories
• `deps [repo]` - Scan dependencies
• `duplicates` - Find code duplicates
• `help` - Show this help

Or just type any question to search!"""
    
    def _send_message(self, channel: str, text: str):
        """Send a message to Slack (requires SLACK_BOT_TOKEN)"""
        if not self.token:
            return
        
        import urllib.request
        data = json.dumps({"channel": channel, "text": text}).encode()
        req = urllib.request.Request(
            "https://slack.com/api/chat.postMessage",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}"
            }
        )
        try:
            urllib.request.urlopen(req)
        except Exception as e:
            logger.error(f"Slack send error: {e}")
