"""
Vercel serverless entry for FastAPI.

Ensures project root is on sys.path and exports ``app`` for @vercel/python.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.main import app  # noqa: E402
