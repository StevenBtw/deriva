"""Root conftest to ensure src is on path before test collection."""

import sys
from pathlib import Path

# Add src to Python path IMMEDIATELY when conftest loads
_src_path = str(Path(__file__).parent / "src")
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)


def pytest_configure(config):
    """Ensure src is on path during pytest configuration."""
    if _src_path not in sys.path:
        sys.path.insert(0, _src_path)
