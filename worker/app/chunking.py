from __future__ import annotations

import hashlib


def split_by_heading(text: str, max_chars: int = 1200) -> list[tuple[str | None, str]]:
    lines = text.splitlines()
    current_heading: str | None = None
    current = []
    chunks: list[tuple[str | None, str]] = []

    def flush() -> None:
        nonlocal current
        if current:
            chunks.append((current_heading, '\n'.join(current).strip()))
            current = []

    for line in lines:
        if line.startswith('#'):
            flush()
            current_heading = line.lstrip('#').strip()
            continue
        current.append(line)
        if sum(len(x) for x in current) >= max_chars:
            flush()

    flush()
    return [(h, c) for h, c in chunks if c]


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()
