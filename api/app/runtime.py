from __future__ import annotations

import sys


def ensure_supported_python() -> None:
    if sys.version_info < (3, 12):
        version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        raise RuntimeError(f'Python 3.12+ is required. Current: {version}')
