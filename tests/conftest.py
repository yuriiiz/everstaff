"""Shared test fixtures."""

import sys
from pathlib import Path

# Ensure src/ is on sys.path so that `everstaff.*` imports resolve.
_src_dir = str(Path(__file__).parent.parent / "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

# Ensure src/everstaff/ is on sys.path so that bare module imports (e.g. `from api import create_app`)
# resolve to the same module objects as `everstaff.api`.
_src_root = str(Path(__file__).parent.parent / "src" / "everstaff")
if _src_root not in sys.path:
    sys.path.insert(1, _src_root)

# Also ensure project root is on sys.path.
_project_root = str(Path(__file__).parent.parent)
if _project_root not in sys.path:
    sys.path.insert(2, _project_root)

import pytest
