"""Thin wrapper: run the in-package demo walk."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fertilizer_intelligence.demo import main

if __name__ == "__main__":
    raise SystemExit(main())
