#!/usr/bin/env python3
"""Entry point used by the shell functions: python3 run.py codex|claude [args...]"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pangu.cli import main  # noqa: E402

if __name__ == '__main__':
    sys.exit(main())
