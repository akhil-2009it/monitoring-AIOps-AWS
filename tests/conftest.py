"""Shared pytest fixtures."""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Auth disabled in tests
os.environ.setdefault("MLOPS_AUTH_DISABLED", "1")
