#!/usr/bin/env python3
"""Start the fast search API server

Usage:
    python3 scripts/start_api.py                   # default 0.0.0.0:8888
    python3 scripts/start_api.py --port 9000
    python3 scripts/start_api.py --host 127.0.0.1 --port 9000
"""
import sys
import argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.api.search_api import start_search_api

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start the search API server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8888, help="Bind port (default: 8888)")
    args = parser.parse_args()
    start_search_api(host=args.host, port=args.port)
