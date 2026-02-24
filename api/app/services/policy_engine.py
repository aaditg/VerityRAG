from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PersonaPolicy:
    persona: str
    retrieval_top_k: int
    min_confidence: float
    output_template: str
    cache_ttl_seconds: int
    tool_allowlist: list[str]


POLICIES = {
    'sales': PersonaPolicy(
        persona='sales',
        retrieval_top_k=10,
        min_confidence=0.42,
        output_template='Client-safe business answer with concise bullets.',
        cache_ttl_seconds=600,
        tool_allowlist=['salesforce_summary', 'looker_metric_catalog'],
    ),
    'exec': PersonaPolicy(
        persona='exec',
        retrieval_top_k=8,
        min_confidence=0.45,
        output_template='Executive summary: outcomes, risk, recommendation.',
        cache_ttl_seconds=300,
        tool_allowlist=['looker_metric_catalog'],
    ),
    'engineering': PersonaPolicy(
        persona='engineering',
        retrieval_top_k=10,
        min_confidence=0.4,
        output_template='Technical response with implementation detail and caveats.',
        cache_ttl_seconds=300,
        tool_allowlist=['github_docs_lookup'],
    ),
}


def get_policy(persona: str) -> PersonaPolicy:
    return POLICIES.get(persona, POLICIES['engineering'])
