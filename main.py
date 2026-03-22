#!/usr/bin/env python3
"""
Main entry point for Code Atlas
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from cli.main import main

if __name__ == "__main__":
    sys.exit(main())
