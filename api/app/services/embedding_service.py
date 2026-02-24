from __future__ import annotations

import hashlib
import math
from collections import deque

import httpx

from app.config import get_settings


EMBED_DIM = 256
EMBED_VERSION = 'ollama-v1'
_embed_cache: dict[str, list[float]] = {}
_embed_order: deque[str] = deque()
_EMBED_CACHE_MAX = 1024


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm <= 1e-12:
        return vec
    return [v / norm for v in vec]


def _fit_dim(vec: list[float], target_dim: int) -> list[float]:
    if not vec:
        return [0.0] * target_dim
    if len(vec) == target_dim:
        return vec
    out = [0.0] * target_dim
    for i, v in enumerate(vec):
        out[i % target_dim] += float(v)
    scale = max(1, len(vec) // target_dim)
    out = [v / scale for v in out]
    return out


def _fallback_hash_embedding(text: str) -> list[float]:
    digest = hashlib.sha256(text.encode('utf-8')).digest()
    out: list[float] = []
    for i in range(EMBED_DIM):
        b = digest[i % len(digest)]
        out.append((b / 255.0) * 2.0 - 1.0)
    return _normalize(out)


def _cache_get(key: str) -> list[float] | None:
    return _embed_cache.get(key)


def _cache_set(key: str, value: list[float]) -> None:
    if key in _embed_cache:
        _embed_cache[key] = value
        return
    _embed_cache[key] = value
    _embed_order.append(key)
    while len(_embed_order) > _EMBED_CACHE_MAX:
        old = _embed_order.popleft()
        _embed_cache.pop(old, None)


def embed_text(text: str) -> list[float]:
    key = hashlib.sha256(text.encode('utf-8')).hexdigest()
    cached = _cache_get(key)
    if cached is not None:
        return cached

    settings = get_settings()
    model = getattr(settings, 'ollama_embed_model', 'nomic-embed-text')
    base_url = settings.ollama_base_url.rstrip('/')
    timeout = max(5, int(getattr(settings, 'ollama_timeout_seconds', 45)))

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                f'{base_url}/api/embeddings',
                json={'model': model, 'prompt': text[:8000]},
            )
            resp.raise_for_status()
            data = resp.json()
            raw_vec = data.get('embedding') or []
        vec = _normalize(_fit_dim([float(v) for v in raw_vec], EMBED_DIM))
        if not any(abs(v) > 1e-12 for v in vec):
            vec = _fallback_hash_embedding(text)
    except Exception:
        vec = _fallback_hash_embedding(text)

    _cache_set(key, vec)
    return vec
