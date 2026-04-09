#!/usr/bin/env python3
"""Start the fast search API server

Usage:
    python3 scripts/start_api.py                   # default 0.0.0.0:8765 (or next free if busy)
    python3 scripts/start_api.py --port 9000
    python3 scripts/start_api.py --host 127.0.0.1 --port 9000
    python3 scripts/start_api.py --strict-port     # exit if preferred port is busy (no auto bump)
"""
import sys
import argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.api.search_api import start_search_api

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start the search API server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8765, help="Bind port (default: 8765)")
    parser.add_argument(
        "--strict-port",
        action="store_true",
        help="Fail if PORT is busy instead of trying the next free port (8889, …).",
    )
    args = parser.parse_args()
    start_search_api(host=args.host, port=args.port, strict_port=args.strict_port)
