"""
Fast REST API for code search, query, and repo management.
Uses the optimized unified RAG retriever.

Start: python3 -m src.api.search_api
Or:    python3 scripts/start_api.py
"""

import json
import time
import logging
import os
import signal
import socket
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import threading
from typing import Optional

logger = logging.getLogger("search_api")


class SearchAPIHandler(BaseHTTPRequestHandler):
    """Fast search API handler"""
    
    retriever = None  # Set by server
    llm = None
    _query_engine = None  # Lazy singleton (shares retriever's Qdrant handle)
    _query_lock = threading.Lock()  # Serialized queries for embedded Qdrant safety
    
    def log_message(self, format, *args):
        logger.debug(f"{self.address_string()} {format % args}")
    
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)
        
        # Serve dashboard at root
        if path in ("/", "/dashboard"):
            from src.api.dashboard import DASHBOARD_HTML
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode())
            return
        
        routes = {
            "/health": self._health,
            "/api/explain/ready": lambda: self._json({"status": "ok", "message": "Explain endpoint ready. POST to /api/explain with {\"query\":\"...\", \"repo\":\"...\", \"diagram\":true}"}),
            "/api/search": lambda: self._search(params),
            "/api/search/stream": lambda: self._stream_search(params),
            "/api/repos": self._repos,
            "/api/repo": lambda: self._repo_info(params),
            "/api/duplicates": lambda: self._duplicates(params),
            "/api/deps": lambda: self._deps(params),
            "/api/impact": lambda: self._impact_get(params),
            "/api/workflows": self._list_workflows,
            "/api/cache/stats": self._cache_stats,
            "/api/metrics": self._rag_metrics,
        }
        
        handler = routes.get(path)
        if handler:
            try:
                handler()
            except Exception as e:
                self._json({"error": str(e)}, 500)
        else:
            self._json({"error": "Not found", "routes": list(routes.keys())}, 404)
    
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        body = self._read_body()
        
        routes = {
            "/api/query": lambda: self._query(body),
            "/api/explain": lambda: self._explain(body),
            "/api/review": lambda: self._review(body),
            "/api/migrate": lambda: self._migrate(body),
            "/api/generate-docs": lambda: self._gen_docs(body),
            "/api/generate-tests": lambda: self._gen_tests(body),
            "/api/debug-error": lambda: self._debug_error(body),
            "/api/refactor": lambda: self._refactor(body),
            "/api/impact": lambda: self._impact_post(body),
            "/api/workflow/run": lambda: self._run_workflow(body),
            "/api/reindex": lambda: self._reindex(body),
            "/api/feedback": lambda: self._record_feedback(body),
            "/api/webhook/gitlab": lambda: self._gitlab_webhook(body),
            "/api/webhook/slack": lambda: self._slack_webhook(body),
        }
        
        handler = routes.get(path)
        if handler:
            try:
                handler()
            except Exception as e:
                self._json({"error": str(e)}, 500)
        else:
            self._json({"error": "Not found"}, 404)
    
    # === GET endpoints ===
    
    def _health(self):
        self._json({
            "status": "ok",
            "unified": self.retriever._unified is not None if self.retriever else False,
            "repos": len(self.retriever._collections) if self.retriever else 0
        })
    
    def _search(self, params):
        q = params.get("q", [""])[0]
        n = int(params.get("n", ["10"])[0])
        repo = params.get("repo", [None])[0]
        lang = params.get("lang", [None])[0]
        
        if not q:
            self._json({"error": "Missing ?q= parameter"}, 400)
            return
        
        t = time.time()
        results = self.retriever.search_code(q, n_results=n, repo_filter=repo, language_filter=lang)
        elapsed = time.time() - t
        
        self._json({
            "query": q,
            "results": [{
                "repo": r["repo"], "file": r["file"],
                "language": r.get("language", "?"),
                "score": round(r.get("hybrid_score", 0), 4),
                "code_preview": r.get("code", "")[:200]
            } for r in results],
            "count": len(results),
            "time_ms": round(elapsed * 1000)
        })
    
    def _repos(self):
        repos = self.retriever.get_available_repos()
        self._json({"repos": repos, "count": len(repos)})
    
    def _repo_info(self, params):
        name = params.get("name", [""])[0]
        if not name:
            self._json({"error": "Missing ?name= parameter"}, 400)
            return
        info = self.retriever.get_repo_summary(name)
        self._json(info)
    
    def _duplicates(self, params):
        """Find code duplicates across repos using embedding similarity"""
        repo = params.get("repo", [None])[0]
        threshold = float(params.get("threshold", ["0.15"])[0])
        n = int(params.get("n", ["20"])[0])
        
        from src.tools.duplication_finder import find_duplicates
        results = find_duplicates(self.retriever, repo_filter=repo, threshold=threshold, max_results=n)
        self._json(results)
    
    def _deps(self, params):
        """Scan dependencies across repos"""
        base_path = params.get("path", [None])[0]
        from src.tools.dependency_scanner import scan_all
        results = scan_all(base_path)
        self._json(results)
    
    def _stream_search(self, params):
        """
        SSE streaming search endpoint.
        Streams results as each pipeline stage completes.
        
        GET /api/search/stream?q=query&n=10&repo=name
        
        Returns: text/event-stream with progressive results
        """
        q = params.get("q", [""])[0]
        n = int(params.get("n", ["10"])[0])
        repo = params.get("repo", [None])[0]
        lang = params.get("lang", [None])[0]
        
        if not q:
            self._json({"error": "Missing ?q= parameter"}, 400)
            return
        
        try:
            from src.ai.streaming import StreamingRAGSearch, generate_sse_response
            from src.ai.rag_enhanced import EnhancedRAGRetriever
            
            # Use enhanced retriever if available
            if hasattr(self, '_enhanced_retriever') and self._enhanced_retriever:
                streaming = StreamingRAGSearch(self._enhanced_retriever)
            else:
                enhanced = EnhancedRAGRetriever(
                    vector_db_path="./data/qdrant_db",
                    use_hyde=False,
                    use_deep_context=False
                )
                streaming = StreamingRAGSearch(enhanced)
            
            # Send SSE headers
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            
            # Stream events
            events = streaming.stream_search(
                query=q,
                n_results=n,
                repo_filter=repo,
                language_filter=lang
            )
            
            for sse_string in generate_sse_response(events):
                self.wfile.write(sse_string.encode())
                self.wfile.flush()
                
        except Exception as e:
            logger.error(f"Stream search error: {e}")
            self._json({"error": str(e)}, 500)
    
    def _cache_stats(self):
        """Get cache hit/miss statistics"""
        try:
            from src.ai.cache import get_rag_cache
            cache = get_rag_cache(enable_redis=True)
            self._json({"cache": cache.stats()})
        except Exception as e:
            self._json({"cache": {"error": str(e)}})
    
    def _rag_metrics(self):
        """Get RAG pipeline metrics"""
        try:
            from src.ai.rag_monitoring import get_metrics_collector
            collector = get_metrics_collector()
            self._json(collector.get_summary())
        except Exception as e:
            self._json({"metrics": {"error": str(e)}})
    
    # === POST endpoints ===
    
    def _query(self, body):
        """RAG + LLM query (one shared QueryEngine; lock for embedded Qdrant)."""
        q = body.get("query", "")
        repo = body.get("repo")
        if not q:
            self._json({"error": "Missing 'query' field"}, 400)
            return
        if self.retriever is None:
            self._json({"error": "Retriever not initialized"}, 503)
            return

        from src.ai.query_engine import QueryEngine
        from src.ai.vector_backend import vector_db_path

        # Default false: shared API process must not mix users in engine.history
        include_history = body.get("include_history", False)
        if not isinstance(include_history, bool):
            include_history = False

        with SearchAPIHandler._query_lock:
            if SearchAPIHandler._query_engine is None:
                SearchAPIHandler._query_engine = QueryEngine(
                    vector_db_path=vector_db_path(),
                    retriever=self.retriever,
                )
            engine = SearchAPIHandler._query_engine
            result = engine.query(
                q,
                repo_filter=repo,
                include_history=include_history,
            )
        self._json({
            "answer": result.answer,
            "sources": result.sources,
            "model": result.model,
            "provider": result.provider,
            "tokens": result.tokens_used,
            "cache_hit": result.cache_hit,
            "latency_seconds": result.latency_seconds,
        })
    
    def _explain(self, body):
        """Explain function/repo/logic with optional Mermaid diagram"""
        try:
            q = body.get("query", body.get("question", ""))
            repo = body.get("repo")
            diagram = body.get("diagram", False)
            if not q:
                self._json({"error": "Missing 'query' or 'question' field"}, 400)
                return
            from src.tools.repo_explainer import explain
            result = explain(self.retriever, q, repo_filter=repo, include_diagram=diagram)
            if result.get("error"):
                err = {"error": result["error"]}
                if "LLM" in str(result.get("error", "")):
                    err["hint"] = "Run: ollama serve && ollama pull codellama"
                self._json(err, 400)
            else:
                self._json({
                    "explanation": result["explanation"],
                    "diagram": result.get("diagram"),
                    "sources": result.get("sources", []),
                    "model": result.get("model", ""),
                    "provider": result.get("provider", "")
                })
        except Exception as e:
            logger.exception("Explain failed")
            self._json({"error": str(e), "type": "ExplainError"}, 500)
    
    def _review(self, body):
        """AI code review"""
        diff = body.get("diff", "")
        repo = body.get("repo", "")
        if not diff:
            self._json({"error": "Missing 'diff' field"}, 400)
            return
        from src.tools.pr_reviewer import review_diff
        result = review_diff(self.retriever, diff, repo)
        self._json(result)
    
    def _migrate(self, body):
        """Migration automator"""
        from src.tools.migration_automator import run_migration
        result = run_migration(body)
        self._json(result)
    
    def _gen_docs(self, body):
        """Generate documentation"""
        repo = body.get("repo", "")
        from src.tools.doc_generator import generate_docs
        result = generate_docs(self.retriever, repo)
        self._json(result)
    
    def _gen_tests(self, body):
        """Generate tests"""
        repo = body.get("repo", "")
        file_path = body.get("file", "")
        from src.tools.test_generator import generate_tests
        result = generate_tests(self.retriever, repo, file_path)
        self._json(result)
    
    def _debug_error(self, body):
        """Debug an error"""
        error_text = body.get("error", "")
        if not error_text:
            self._json({"error": "Missing 'error' field"}, 400)
            return
        from src.tools.incident_debugger import debug_error
        result = debug_error(self.retriever, error_text)
        self._json(result)
    
    def _refactor(self, body):
        """Cross-repo refactoring"""
        from src.tools.refactoring_engine import run_refactor
        result = run_refactor(body)
        self._json(result)
    
    def _impact_get(self, params):
        """GET /api/impact?symbol=Foo&repo=bar&n=50 — trace callers/dependents"""
        symbol = params.get("symbol", [""])[0]
        if not symbol:
            self._json({"error": "Missing ?symbol= parameter"}, 400)
            return
        repo = params.get("repo", [None])[0]
        n = int(params.get("n", ["50"])[0])
        from src.tools.impact_analyzer import analyze_impact
        result = analyze_impact(self.retriever, symbol, repo_filter=repo, max_results=n)
        self._json(result)

    def _impact_post(self, body):
        """
        POST /api/impact — two modes:

        Symbol mode:  {"symbol": "ProcessPayment", "repo": "optional"}
        Diff mode:    {"diff": "unified diff text",  "repo": "optional"}
        """
        symbol = body.get("symbol", "")
        diff = body.get("diff", "")
        repo = body.get("repo") or None
        n = int(body.get("max_results", 50))

        if not symbol and not diff:
            self._json({"error": "Provide 'symbol' or 'diff' in request body"}, 400)
            return

        if diff:
            from src.tools.impact_analyzer import analyze_diff_impact
            result = analyze_diff_impact(self.retriever, diff, repo_name=repo, max_results=n)
        else:
            from src.tools.impact_analyzer import analyze_impact
            result = analyze_impact(self.retriever, symbol, repo_filter=repo, max_results=n)
        self._json(result)

    def _list_workflows(self):
        """GET /api/workflows — list all available workflow pipelines"""
        from src.workflows.builtin import list_workflows
        self._json({"workflows": list_workflows()})

    def _run_workflow(self, body):
        """
        POST /api/workflow/run — execute a multi-step workflow pipeline.

        {
            "workflow": "pre_mr_review",
            "params": {"diff": "...", "repo": "..."}
        }

        Or define a custom workflow inline:
        {
            "workflow": "custom",
            "steps": [
                {"id": "s1", "tool": "search", "params": {"query": "foo"}},
                {"id": "s2", "tool": "impact_analysis", "params": {"symbol": "bar"}}
            ],
            "params": {}
        }
        """
        workflow_name = body.get("workflow", "")
        user_params = body.get("params", {})

        if not workflow_name:
            self._json({"error": "Missing 'workflow' field"}, 400)
            return

        from src.workflows.engine import WorkflowEngine, WorkflowStep
        from src.workflows.builtin import get_workflow

        engine = WorkflowEngine(self.retriever)

        # Built-in workflow
        wf_def = get_workflow(workflow_name)
        if wf_def:
            missing = [p for p in wf_def["required"] if not user_params.get(p)]
            if missing:
                self._json({
                    "error": f"Missing required params: {missing}",
                    "required": wf_def["required"],
                    "optional": wf_def.get("optional", []),
                }, 400)
                return
            steps = wf_def["steps"]
        elif body.get("steps"):
            steps = [
                WorkflowStep(
                    id=s["id"],
                    tool=s["tool"],
                    params=s.get("params", {}),
                    label=s.get("label", ""),
                    condition=s.get("condition"),
                    on_error=s.get("on_error", "continue"),
                )
                for s in body["steps"]
            ]
        else:
            from src.workflows.builtin import list_workflows
            self._json({
                "error": f"Unknown workflow: {workflow_name}",
                "available": list_workflows(),
            }, 400)
            return

        result = engine.run(workflow_name, steps, user_params)
        self._json(result.to_dict())

    def _reindex(self, body):
        """Re-index a repo"""
        repo_path = body.get("repo_path", "")
        if not repo_path:
            self._json({"error": "Missing 'repo_path'"}, 400)
            return
        from src.tools.auto_reindexer import reindex_repo
        result = reindex_repo(repo_path)
        self._json(result)
    
    def _record_feedback(self, body):
        """
        Record user feedback for search results.
        
        POST /api/feedback
        {
            "query": "search query",
            "result_file": "path/to/file.go",
            "result_repo": "repo-name",
            "action": "thumbs_up|thumbs_down|click|skip|reformulate",
            "session_id": "optional-session-id",
            "original_rank": 1,
            "score": 0.95
        }
        """
        from src.ai.rag_monitoring import FeedbackEntry, get_metrics_collector
        
        action = body.get("action", "")
        if action not in ("thumbs_up", "thumbs_down", "click", "skip", "reformulate"):
            self._json({
                "error": "Invalid action. Use: thumbs_up, thumbs_down, click, skip, reformulate"
            }, 400)
            return
        
        feedback = FeedbackEntry(
            query=body.get("query", ""),
            result_file=body.get("result_file", ""),
            result_repo=body.get("result_repo", ""),
            action=action,
            session_id=body.get("session_id", ""),
            original_rank=body.get("original_rank", 0),
            score=body.get("score", 0.0)
        )
        
        collector = get_metrics_collector()
        collector.record_feedback(feedback)
        
        self._json({
            "status": "ok",
            "satisfaction_score": collector.feedback.get_satisfaction_score()
        })
    
    def _gitlab_webhook(self, body):
        """Handle GitLab push/MR webhooks"""
        event_type = self.headers.get("X-Gitlab-Event", "")
        
        if event_type == "Push Hook":
            from src.tools.auto_reindexer import handle_gitlab_webhook
            result = handle_gitlab_webhook(body)
            self._json(result)
        elif event_type == "Merge Request Hook":
            from src.tools.pr_reviewer import handle_gitlab_mr_webhook
            result = handle_gitlab_mr_webhook(body, self.retriever)
            self._json(result)
        else:
            self._json({"received": event_type, "note": "Unhandled event type"})
    
    def _slack_webhook(self, body):
        """Handle Slack events"""
        from src.tools.slack_bot import SlackBot
        bot = SlackBot(self.retriever)
        result = bot.handle_event(body)
        self._json(result or {"ok": True})
    
    # === Helpers ===
    
    def _read_body(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length)) if length > 0 else {}
        except Exception:
            return {}
    
    def _json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode())


class ReusableHTTPServer(HTTPServer):
    """HTTPServer with SO_REUSEADDR so the port is released immediately on shutdown."""
    allow_reuse_address = True

    def server_close(self):
        """Ensure socket is fully shut down."""
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        super().server_close()


def _pids_listening_on_port(port: int) -> list[int]:
    """PIDs with a TCP listener on *port* (best effort via lsof)."""
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        out = []
        for p in result.stdout.strip().split():
            try:
                pid = int(p)
            except ValueError:
                continue
            if pid != os.getpid():
                out.append(pid)
        return out
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []


def _kill_process_on_port(port: int, *, force: bool = False) -> bool:
    """
    Stop processes listening on *port*.
    Tries SIGTERM first; with force=True or a second call, uses SIGKILL.
    """
    pids = _pids_listening_on_port(port)
    if not pids:
        return False
    sig = signal.SIGKILL if force else signal.SIGTERM
    for pid in pids:
        try:
            logger.info("Stopping process %s on port %s (%s)", pid, port, "SIGKILL" if force else "SIGTERM")
            os.kill(pid, sig)
        except ProcessLookupError:
            pass
        except PermissionError as exc:
            logger.warning("Cannot signal pid %s (try: fuser -k %s/tcp or sudo): %s", pid, port, exc)
    # Give the kernel time to release the socket (especially after SIGKILL)
    time.sleep(1.2 if force else 0.8)
    return True


def start_search_api(host="0.0.0.0", port=8888):
    """Start the fast search API server with graceful shutdown."""
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent.parent))

    from src.ai.rag import RAGRetriever

    print(f"Loading RAG retriever...", flush=True)
    retriever = RAGRetriever(persist_directory="./data/qdrant_db")
    SearchAPIHandler.retriever = retriever

    # Try to bind; if port is busy, stop stale listeners and retry (TERM then KILL)
    server = None
    for attempt in range(5):
        try:
            server = ReusableHTTPServer((host, port), SearchAPIHandler)
            break
        except OSError as e:
            if e.errno != 98:  # Address already in use
                raise
            if attempt >= 4:
                print(
                    f"\nPort {port} is still in use after cleanup attempts.\n"
                    f"  Run:  fuser -k {port}/tcp   or   lsof -i :{port}\n"
                    f"  Or start on another port:  python3 scripts/start_api.py --port 8890\n",
                    flush=True,
                )
                raise
            force = attempt >= 2
            print(
                f"Port {port} is in use — {'force-killing' if force else 'stopping'} stale listener(s)...",
                flush=True,
            )
            _kill_process_on_port(port, force=force)
            if not _pids_listening_on_port(port):
                time.sleep(0.3)

    assert server is not None

    # Graceful shutdown on SIGINT / SIGTERM
    def _shutdown(signum, frame):
        sig_name = signal.Signals(signum).name
        print(f"\n{sig_name} received — shutting down gracefully...", flush=True)
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    print(f"API server running on http://{host}:{port}", flush=True)
    print(f"  GET  /api/search?q=reporting", flush=True)
    print(f"  GET  /api/repos", flush=True)
    print(f"  POST /api/query  {{\"query\": \"...\"}}", flush=True)
    print(f"  POST /api/explain {{\"query\": \"how X works\", \"diagram\": true}}", flush=True)
    print(f"  POST /api/reindex {{\"repo_path\": \"...\"}}", flush=True)

    try:
        server.serve_forever()
    finally:
        server.server_close()
        print("Server stopped.", flush=True)


if __name__ == "__main__":
    start_search_api()
