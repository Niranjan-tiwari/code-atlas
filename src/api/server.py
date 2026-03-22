"""
REST API server for Code Atlas
Provides HTTP endpoints for task management
"""

import json
import logging
from typing import Dict, Optional
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import threading
from datetime import datetime

from src.core.worker import ParallelRepoWorker
from src.core.models import Task
from src.security import SecurityManager, AccessControl


class APIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for API"""
    
    def __init__(self, worker: ParallelRepoWorker, security: SecurityManager, 
                 access_control: AccessControl, *args, **kwargs):
        self.worker = worker
        self.security = security
        self.access_control = access_control
        super().__init__(*args, **kwargs)
    
    def log_message(self, format, *args):
        """Override to use our logger"""
        logging.getLogger("api").info(f"{self.address_string()} - {format % args}")
    
    def do_GET(self):
        """Handle GET requests"""
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        
        if path == '/health':
            self.send_health()
        elif path == '/status':
            self.send_status()
        else:
            self.send_error(404, "Not Found")
    
    def do_POST(self):
        """Handle POST requests"""
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        
        # Check authentication
        api_key = self.headers.get('X-API-Key') or self.headers.get('Authorization', '').replace('Bearer ', '')
        is_auth, error = self.access_control.require_auth(api_key)
        if not is_auth:
            self.send_json_response({"error": error}, 401)
            return
        
        # Check rate limit
        client_id = self.client_address[0]
        allowed, error = self.security.check_rate_limit(client_id)
        if not allowed:
            self.send_json_response({"error": error}, 429)
            return
        
        if path == '/tasks':
            self.handle_create_task()
        elif path == '/tasks/execute':
            self.handle_execute_tasks()
        else:
            self.send_error(404, "Not Found")
    
    def handle_create_task(self):
        """Handle task creation"""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            task_data = json.loads(body.decode('utf-8'))
            
            # Validate task
            is_valid, error = self.security.validate_task(task_data)
            if not is_valid:
                self.send_json_response({"error": error}, 400)
                return
            
            # Create task
            task = Task.from_dict(task_data)
            self.worker.add_task(task)
            
            self.send_json_response({
                "success": True,
                "task_id": task.task_id,
                "message": "Task created successfully"
            }, 201)
            
        except json.JSONDecodeError:
            self.send_json_response({"error": "Invalid JSON"}, 400)
        except Exception as e:
            logging.error(f"Error creating task: {e}")
            self.send_json_response({"error": str(e)}, 500)
    
    def handle_execute_tasks(self):
        """Handle task execution"""
        try:
            results = self.worker.execute_parallel()
            self.send_json_response({
                "success": True,
                "results": results
            })
        except Exception as e:
            logging.error(f"Error executing tasks: {e}")
            self.send_json_response({"error": str(e)}, 500)
    
    def send_health(self):
        """Send health check response"""
        self.send_json_response({
            "status": "healthy",
            "service": "code-atlas",
            "timestamp": str(datetime.now())
        })
    
    def send_status(self):
        """Send status response"""
        status = {
            "repos": len(self.worker.repos),
            "tasks": len(self.worker.tasks),
            "pending_tasks": len([t for t in self.worker.tasks if t.status == "pending"]),
            "completed_tasks": len([t for t in self.worker.tasks if t.status == "completed"])
        }
        self.send_json_response(status)
    
    def send_json_response(self, data: Dict, status_code: int = 200):
        """Send JSON response"""
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))


class APIServer:
    """API Server for Code Atlas"""
    
    def __init__(self, worker: ParallelRepoWorker, host: str = "localhost", 
                 port: int = 8080, api_keys: Optional[list] = None):
        self.worker = worker
        self.host = host
        self.port = port
        self.security = SecurityManager()
        self.access_control = AccessControl(api_keys)
        self.server = None
        self.thread = None
        
    def start(self):
        """Start API server"""
        def handler(*args, **kwargs):
            return APIHandler(self.worker, self.security, self.access_control, *args, **kwargs)
        
        self.server = HTTPServer((self.host, self.port), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        logging.info(f"API server started on {self.host}:{self.port}")
    
    def stop(self):
        """Stop API server"""
        if self.server:
            self.server.shutdown()
            logging.info("API server stopped")


def create_app(worker: ParallelRepoWorker, host: str = "localhost", 
               port: int = 8080, api_keys: Optional[list] = None) -> APIServer:
    """Create and return API server instance"""
    return APIServer(worker, host, port, api_keys)
