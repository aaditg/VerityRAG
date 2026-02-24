from __future__ import annotations

from urllib.parse import urlencode


def build_oauth_url(base: str, params: dict[str, str]) -> str:
    return f'{base}?{urlencode(params)}'
