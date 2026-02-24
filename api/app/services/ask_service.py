from __future__ import annotations

import hashlib
import math
import json
import fnmatch
import re
from collections import Counter
from dataclasses import dataclass
from statistics import mean
from uuid import UUID

from redis import Redis
from sqlalchemy import String, and_, cast, literal, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import Chunk, Document, DocumentAcl, Fact, GroupMembership, Source, User
from app.config import get_settings
from app.schemas import AskRequest, AskResponse, Citation
from app.services.cache_service import CacheService
from app.services.embedding_service import embed_text
from app.services.llm_service import LlmAnswer, synthesize_grounded_answer
from app.services.policy_engine import get_policy
from app.services.retrieval_service import RetrievedChunk, retrieve_acl_safe


WHITESPACE_RE = re.compile(r'\s+')
ANSWER_VERSION = 'v42'
CANONICAL_LABEL_BY_PERSONA: dict[str, dict[str, str]] = {
    'sales': {
        'Primary AWS regions: us-east-1 and us-west-2': 'Primary cloud regions: us-east-1 and us-west-2',
        'Multi-AZ deployments': 'High-availability deployment zones',
        'cross-region database replicas': 'Cross-region database copies',
        'cross-region S3 backups': 'Cross-region cloud backups',
        'cross-region s3 backup': 'Cross-region cloud backup',
        'disaster recovery drills': 'Regular disaster recovery drills',
        'RTO of 2 hours': 'Recovery target: 2 hours',
        'identity-aware proxy': 'Identity-based access gateway',
        'RBAC': 'Role-based access controls',
        'MFA': 'Multi-factor authentication',
        'MDM compliance': 'Managed-device policy compliance',
        'Kubernetes (EKS)': 'Managed container platform',
        'PostgreSQL': 'Primary relational data store',
        'OpenTelemetry': 'Distributed tracing',
    },
    'exec': {
        'Multi-AZ deployments': 'Multi-zone resiliency',
        'cross-region database replicas': 'Cross-region data replication',
        'cross-region S3 backups': 'Cross-region backup coverage',
        'RTO of 2 hours': 'Recovery objective: 2 hours',
        'identity-aware proxy': 'Identity-based access control',
        'RBAC': 'Role-based controls',
        'MFA': 'Multi-factor authentication',
    },
}
DEPTH_CHOICES = {'low', 'medium', 'high'}
TONE_CHOICES = {'friendly', 'direct', 'critical'}

CANONICAL_FACT_PATTERNS: list[tuple[str, list[str]]] = [
    ('Primary AWS regions: us-east-1 and us-west-2', [r'us-east-1', r'us-west-2', r'primary cloud provider|deployed across']),
    ('Multi-AZ deployments', [r'multi[-\s]*az']),
    ('cross-region database replicas', [r'cross[- ]region.+replica', r'cross[- ]region.+database']),
    ('cross-region S3 backups', [r'cross[- ]region.+s3', r's3 backup']),
    ('disaster recovery drills', [r'disaster recovery drill', r'quarterly failover drill']),
    ('RTO of 2 hours', [r'rto[\s\S]{0,40}2\s*hours?']),
    ('failover between us-east-1 and us-west-2', [r'us-east-1', r'us-west-2', r'failover']),
    ('identity-aware proxy', [r'identity[-\s]*aware\s+prox']),
    ('zero-trust access enforcement', [r'zero[-\s]*trust', r'identity[-\s]*aware']),
    ('private subnets', [r'private subnet']),
    ('VPN required for production access', [r'vpn']),
    ('RBAC', [r'role[-\s]*based\s+access\s+control|\\brbac\\b']),
    ('MFA', [r'multi[-\s]*factor\s+authentication|\\bmfa\\b']),
    ('MDM compliance', [r'\\bmdm\\b']),
    ('P1', [r'\\bp1\\b|priority\\s*1']),
    ('24/7 incident response team', [r'24/7.+incident response']),
    ('postmortem required', [r'postmortem']),
    ('72 hours', [r'72\\s*hours?']),
    ('GDPR procedures', [r'\\bgdpr\\b']),
    ('CDN', [r'\\bcdn\\b']),
    ('WAF', [r'\\bwaf\\b']),
    ('Load balancer', [r'load balancer']),
    ('Kubernetes (EKS)', [r'\\bkubernetes\\b', r'\\beks\\b']),
    ('OAuth 2.0', [r'oauth\\s*2\\.0']),
    ('Okta', [r'okta']),
    ('PostgreSQL', [r'postgresql']),
    ('Redis', [r'\\bredis\\b']),
    ('Prometheus', [r'prometheus']),
    ('Grafana', [r'grafana']),
    ('ELK', [r'\\belk\\b']),
    ('OpenTelemetry', [r'opentelemetry']),
    ('PagerDuty', [r'pagerduty']),
    ('AWS Secrets Manager with automatic rotation', [r'secrets manager', r'automatic rotation']),
    ('Frankfurt data center', [r'frankfurt']),
    ('site-to-site VPN and Direct Connect', [r'site[- ]to[- ]site vpn', r'direct connect']),
    ('Snowflake long-term analytics storage', [r'snowflake']),
    ('Redis caching', [r'redis', r'cach']),
    ('cross-region s3 backup', [r'cross[- ]region[\s\S]{0,40}s3|s3[\s\S]{0,40}cross[- ]region']),
    ('automated backup systems', [r'automated backup|backup system']),
    ('quarterly failover drills', [r'quarterly failover drill']),
    ('Hub-and-spoke VPC model', [r'hub[-\s]*and[-\s]*spoke', r'\\bvpc\\b']),
    ('observability tooling', [r'observability']),
]

INTENT_HINTS: dict[str, list[str]] = {
    'regions': ['cloud region', 'cloud regions', 'primarily use', 'primary region'],
    'dr': ['rto', 'region', 'failover', 'disaster', 'recovery', 'backup', 'offline', 'redundancy'],
    'dr_retention': ['long-term data retention', 'data retention', 'retention'],
    'zero_trust': [
        'zero-trust',
        'zero trust',
        'production access',
        'layered controls',
        'temporary access',
        'public exposure',
        'separate production workloads',
    ],
    'incident': ['incident', 'p1', 'eu', 'customer data', 'gdpr', 'postmortem', '72'],
    'request_path': ['path', 'frontend', 'database', 'request flow', 'full path'],
    'observability': ['observability', 'latency', 'monitoring', 'tracing', 'metrics', 'logging', 'diagnosing'],
    'secrets_auth': ['secrets', 'authentication', 'auth', 'mfa', 'rbac', 'okta', 'oauth'],
    'cost_ops': ['cost', 'operational overhead', 'api cost'],
}

INTENT_CANONICAL_ALLOW: dict[str, set[str]] = {
    'regions': {
        'Primary AWS regions: us-east-1 and us-west-2',
        'failover between us-east-1 and us-west-2',
    },
    'dr': {
        'Multi-AZ deployments',
        'cross-region database replicas',
        'cross-region S3 backups',
        'cross-region s3 backup',
        'disaster recovery drills',
        'quarterly failover drills',
        'RTO of 2 hours',
        'failover between us-east-1 and us-west-2',
        'Frankfurt data center',
        'site-to-site VPN and Direct Connect',
        'automated backup systems',
    },
    'dr_retention': {
        'cross-region S3 backups',
        'cross-region s3 backup',
        'cross-region database replicas',
        'Multi-AZ deployments',
        'automated backup systems',
        'quarterly failover drills',
        'Snowflake long-term analytics storage',
    },
    'zero_trust': {
        'identity-aware proxy',
        'zero-trust access enforcement',
        'private subnets',
        'VPN required for production access',
        'RBAC',
        'MFA',
        'MDM compliance',
        'WAF',
        'Load balancer',
    },
    'incident': {
        'P1',
        '24/7 incident response team',
        'postmortem required',
        '72 hours',
        'GDPR procedures',
    },
    'request_path': {
        'CDN',
        'WAF',
        'Load balancer',
        'Kubernetes (EKS)',
        'OAuth 2.0',
        'Okta',
        'PostgreSQL',
        'Redis',
        'private subnets',
    },
    'observability': {
        'Prometheus',
        'Grafana',
        'ELK',
        'OpenTelemetry',
        'PagerDuty',
        'Load balancer',
        'Kubernetes (EKS)',
    },
    'secrets_auth': {
        'AWS Secrets Manager with automatic rotation',
        'OAuth 2.0',
        'Okta',
        'MFA',
        'RBAC',
        'MDM compliance',
    },
    'cost_ops': {
        'Redis caching',
        'CDN',
        'Hub-and-spoke VPC model',
        'Kubernetes (EKS)',
        'observability tooling',
        'Multi-AZ deployments',
    },
}

INTENT_LEXICAL_TERMS: dict[str, list[str]] = {
    'regions': ['cloud regions', 'us-east-1', 'us-west-2', 'primary cloud provider'],
    'dr': ['multi-az', 'cross-region', 's3', 'backup', 'rto', 'failover', 'us-east-1', 'us-west-2', 'replica'],
    'dr_retention': ['long-term', 'retention', 'snowflake', 's3', 'backup', 'replica', 'multi-az'],
    'zero_trust': ['identity-aware', 'zero-trust', 'private subnet', 'vpn', 'rbac', 'mfa', 'mdm'],
    'incident': ['p1', 'incident', '24/7', 'postmortem', '72 hours', 'gdpr'],
    'request_path': ['cdn', 'waf', 'load balancer', 'kubernetes', 'eks', 'oauth 2.0', 'okta', 'postgresql', 'redis'],
    'observability': ['prometheus', 'grafana', 'elk', 'opentelemetry', 'pagerduty', 'metrics', 'tracing', 'logging'],
    'secrets_auth': ['secrets manager', 'automatic rotation', 'oauth 2.0', 'okta', 'mfa', 'rbac'],
    'cost_ops': ['redis', 'cache', 'cdn', 'hub-and-spoke', 'vpc', 'kubernetes', 'observability', 'multi-az'],
}
INTENT_FACT_KEYS: dict[str, list[str]] = {
    'regions': ['cloud.primary_regions', 'cloud.multi_az', 'cloud.cross_region_replication'],
    'dr': ['cloud.multi_az', 'cloud.cross_region_s3_backup', 'cloud.cross_region_replication', 'dr.rto', 'dr.frankfurt', 'dr.direct_connect'],
    'dr_retention': ['cloud.multi_az', 'cloud.cross_region_s3_backup', 'cloud.cross_region_replication', 'dr.automated_backup', 'dr.quarterly_failover', 'data.snowflake'],
    'zero_trust': ['network.iap', 'network.private_subnets', 'network.vpn', 'auth.rbac', 'auth.mfa', 'auth.mdm', 'network.zero_trust', 'network.waf', 'network.load_balancer'],
    'incident': ['incident.p1', 'incident.24_7', 'incident.postmortem', 'incident.72h', 'incident.gdpr'],
    'request_path': ['network.cdn', 'network.waf', 'network.load_balancer', 'app.kubernetes', 'auth.oauth2', 'auth.okta', 'data.postgresql', 'data.redis'],
    'observability': ['observability.prometheus', 'observability.grafana', 'observability.elk', 'observability.opentelemetry', 'observability.pagerduty'],
    'secrets_auth': ['auth.secrets_manager', 'auth.oauth2', 'auth.okta', 'auth.mfa', 'auth.rbac', 'auth.mdm', 'network.vpn'],
    'cost_ops': ['data.redis', 'network.cdn', 'arch.hub_spoke_vpc', 'app.kubernetes', 'cloud.multi_az', 'observability.prometheus'],
}
INTENT_REQUIRED_FACT_KEYS: dict[str, set[str]] = {
    'regions': {'cloud.primary_regions'},
    'dr': {'cloud.multi_az', 'cloud.cross_region_s3_backup', 'dr.rto'},
    'dr_retention': {'cloud.cross_region_s3_backup', 'cloud.multi_az', 'data.snowflake'},
    'zero_trust': {'network.iap', 'network.private_subnets', 'network.vpn', 'auth.rbac', 'auth.mfa'},
    'incident': {'incident.p1', 'incident.postmortem', 'incident.72h', 'incident.gdpr'},
    'request_path': {'network.cdn', 'network.waf', 'network.load_balancer', 'app.kubernetes', 'data.postgresql'},
    'observability': {'observability.prometheus', 'observability.grafana', 'observability.elk', 'observability.opentelemetry'},
    'secrets_auth': {'auth.secrets_manager', 'auth.oauth2', 'auth.okta', 'auth.mfa'},
    'cost_ops': {'data.redis', 'network.cdn', 'app.kubernetes'},
}
ORG_HINTS = {
    'technova',
    'our company',
    'our org',
    'internal',
    'salesforce',
    'github',
    'notion',
    'drive',
    'looker',
}
CTX_MAX_TURNS = 8
CTX_RECENT_TURNS = 4
CTX_SUMMARY_MAX_CHARS = 1200
CTX_TTL_SECONDS = 7 * 24 * 60 * 60


def _normalize_query(value: str) -> str:
    return WHITESPACE_RE.sub(' ', value.strip().lower())


def _context_key(req: AskRequest, persona: str) -> str:
    sid = (req.session_id or f'{req.user_id}:{persona}').strip()
    return f'ctx:{req.workspace_id}:{req.user_id}:{persona}:{sid}'


def _compact_text(value: str, limit: int) -> str:
    clean = WHITESPACE_RE.sub(' ', value.strip())
    return clean if len(clean) <= limit else clean[: limit - 1] + '…'


def _load_context(redis: Redis, key: str, max_turns: int = CTX_MAX_TURNS) -> dict:
    try:
        raw = redis.get(key)
        if not raw:
            return {'summary': '', 'turns': []}
        data = json.loads(raw)
        # Backward compatibility with old list-only format.
        if isinstance(data, list):
            turns = [d for d in data if isinstance(d, dict)][-max_turns:]
            return {'summary': '', 'turns': turns}
        if not isinstance(data, dict):
            return {'summary': '', 'turns': []}
        turns = data.get('turns', [])
        if not isinstance(turns, list):
            turns = []
        summary = data.get('summary', '')
        if not isinstance(summary, str):
            summary = ''
        return {'summary': _compact_text(summary, CTX_SUMMARY_MAX_CHARS), 'turns': [d for d in turns if isinstance(d, dict)][-max_turns:]}
    except Exception:
        return {'summary': '', 'turns': []}


def _merge_context_summary(existing_summary: str, turns: list[dict]) -> str:
    lines: list[str] = []
    if existing_summary.strip():
        lines.append(_compact_text(existing_summary, 500))
    for t in turns:
        q = _compact_text(str(t.get('q', '')), 120)
        a = _compact_text(str(t.get('a', '')), 180)
        if not q and not a:
            continue
        lines.append(f'Q: {q} A: {a}'.strip())
    merged = ' | '.join(lines)
    return _compact_text(merged, CTX_SUMMARY_MAX_CHARS)


def _compact_context_state(state: dict) -> dict:
    turns = state.get('turns', [])
    if not isinstance(turns, list):
        turns = []
    summary = str(state.get('summary', '') or '')
    if len(turns) <= CTX_MAX_TURNS:
        return {'summary': _compact_text(summary, CTX_SUMMARY_MAX_CHARS), 'turns': turns[-CTX_MAX_TURNS:]}
    older = turns[: -CTX_RECENT_TURNS]
    recent = turns[-CTX_RECENT_TURNS:]
    summary = _merge_context_summary(summary, older)
    return {'summary': summary, 'turns': recent}


def _append_context_turn(state: dict, q: str, a: str) -> dict:
    turns = state.get('turns', [])
    if not isinstance(turns, list):
        turns = []
    turns = turns + [{'q': _compact_text(q, 240), 'a': _compact_text(a, 320)}]
    return _compact_context_state({'summary': state.get('summary', ''), 'turns': turns})


def _save_context(redis: Redis, key: str, state: dict) -> None:
    try:
        compacted = _compact_context_state(state)
        redis.setex(key, CTX_TTL_SECONDS, json.dumps(compacted))
    except Exception:
        pass


def _is_followup_query(query: str) -> bool:
    q = query.lower().strip()
    if not q:
        return False
    followup_markers = (
        'what about',
        'and ',
        'also ',
        'that ',
        'it ',
        'those ',
        'them ',
        'same ',
        'how about',
        'what\'s that',
        'whats that',
    )
    if any(q.startswith(m) for m in followup_markers):
        return True
    return bool(re.search(r'\b(that|it|those|them|same|previous|last)\b', q))


def _rewrite_query_with_context(query: str, state: dict) -> str:
    turns = state.get('turns', [])
    summary = _compact_text(str(state.get('summary', '') or ''), 600)
    if not turns and not summary:
        return query
    if not _is_followup_query(query):
        return query
    recent = turns[-2:] if isinstance(turns, list) else []
    lines: list[str] = []
    if summary:
        lines.append(f'Context summary: {summary}')
    for t in recent:
        user_q = _compact_text(str(t.get('q', '')), 180)
        if user_q:
            lines.append(f'User asked: {user_q}')
        ans = _compact_text(str(t.get('a', '')), 180)
        if ans:
            lines.append(f'Assistant answered: {ans}')
    if not lines:
        return query
    return f"{query}\n\nConversation context (for follow-up resolution):\n" + '\n'.join(lines)


def _context_hash(chunks_text: list[str]) -> str:
    joined = '\n'.join(chunks_text)
    return hashlib.sha256(joined.encode('utf-8')).hexdigest()


def _answer_cache_key(
    persona: str,
    query: str,
    technical_depth: str,
    output_tone: str,
    conciseness_bucket: str,
    conversationalness_bucket: str,
    fast_mode: bool,
    context_hash: str,
) -> str:
    raw = (
        f'{ANSWER_VERSION}:{persona}:{technical_depth}:{output_tone}:'
        f'{conciseness_bucket}:{conversationalness_bucket}:{int(fast_mode)}:'
        f'{_normalize_query(query)}:{context_hash}'
    )
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _fact_cache_key(
    persona: str,
    query: str,
    technical_depth: str,
    output_tone: str,
    conciseness_bucket: str,
    conversationalness_bucket: str,
    use_general_knowledge: bool,
) -> str:
    raw = (
        f'{ANSWER_VERSION}:fact:{persona}:{technical_depth}:{output_tone}:'
        f'{conciseness_bucket}:{conversationalness_bucket}:{int(use_general_knowledge)}:'
        f'{_normalize_query(query)}'
    )
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _normalize_depth(value: str | None, persona: str) -> str:
    if value and value in DEPTH_CHOICES:
        return value
    if persona == 'sales':
        return 'low'
    if persona == 'engineering':
        return 'high'
    return 'medium'


def _conversation_bucket(value: float) -> str:
    if value < 0.34:
        return 'low'
    if value > 0.66:
        return 'high'
    return 'medium'


def _normalize_tone(value: str | None) -> str:
    if value in TONE_CHOICES:
        return value
    return 'direct'


def _conciseness_bucket(value: float) -> str:
    if value >= 0.75:
        return 'high'
    if value >= 0.5:
        return 'medium'
    return 'low'


def _render_canonical_label(label: str, persona: str, technical_depth: str) -> str:
    if technical_depth == 'high':
        return label
    if technical_depth == 'low':
        mapped = CANONICAL_LABEL_BY_PERSONA.get(persona, {}).get(label)
        if mapped:
            return mapped
    if technical_depth == 'low' and persona != 'engineering':
        generic = {
            'Kubernetes (EKS)': 'Managed application platform',
            'PostgreSQL': 'Core application database',
            'OpenTelemetry': 'Tracing system',
        }
        return generic.get(label, label)
    return label


def _max_bullets_from_conciseness(value: float) -> int:
    if value >= 0.75:
        return 3
    if value >= 0.5:
        return 4
    if value >= 0.25:
        return 5
    return 6


def _max_citations_from_conciseness(value: float) -> int:
    if value >= 0.75:
        return 2
    if value >= 0.5:
        return 3
    return 4


def _tone_prefix(tone: str) -> str:
    if tone == 'friendly':
        return 'Here is the short answer:'
    if tone == 'critical':
        return 'Evidence-backed answer (strict):'
    return 'Answer:'


def _token_set(text: str) -> set[str]:
    return set(re.findall(r'[a-zA-Z0-9_-]+', text.lower()))


def _overlap_count(tokens: set[str], terms: set[str]) -> int:
    if not tokens or not terms:
        return 0
    score = 0
    for term in terms:
        if term in tokens:
            score += 1
            continue
        if len(term) < 5:
            continue
        for tok in tokens:
            if len(tok) < 5:
                continue
            if tok.startswith(term[:5]) or term.startswith(tok[:5]):
                score += 1
                break
    return score


def _query_terms(query: str) -> set[str]:
    words = re.findall(r'[a-zA-Z0-9_-]+', query.lower())
    stop = {'what', 'which', 'the', 'is', 'are', 'does', 'do', 'a', 'an', 'to', 'of', 'for', 'in', 'on', 'and', 'technova'}
    return {w for w in words if len(w) > 2 and w not in stop}


def _is_general_query(query: str) -> bool:
    q = query.lower().strip()
    if any(h in q for h in ORG_HINTS):
        return False
    if re.fullmatch(r'[\d\s\+\-\*\/\(\)\.]+', q):
        return True
    general_starts = (
        'what is ',
        'who is ',
        'define ',
        'calculate ',
        'how many ',
        'convert ',
    )
    return q.startswith(general_starts)


def _safe_eval_arithmetic(query: str) -> float | None:
    q = query.lower().strip()
    # Normalize multiplication variants before character filtering.
    q = re.sub(r'(?<=\d)\s*[x×]\s*(?=\d)', '*', q)
    q = re.sub(r'\btimes\b', '*', q)
    q = re.sub(r'\bmultiplied by\b', '*', q)
    # Generic extraction: keep only arithmetic tokens and evaluate if a valid expression remains.
    q = re.sub(r'[^0-9\.\+\-\*\/\(\)\s]', ' ', q)
    q = WHITESPACE_RE.sub(' ', q).strip()
    if not q or not re.search(r'[\+\-\*\/]', q):
        return None
    if not re.fullmatch(r'[\d\s\+\-\*\/\(\)\.]+', q):
        return None
    try:
        # minimal arithmetic parser via eval on strictly validated characters
        val = eval(q, {'__builtins__': {}}, {})  # noqa: S307
        if isinstance(val, (int, float)) and math.isfinite(val):
            return float(val)
    except Exception:
        return None
    return None


def _last_numeric_answer(turns: list[dict]) -> float | None:
    for t in reversed(turns):
        a = str(t.get('a', '')).strip()
        if re.fullmatch(r'[-+]?\d+(\.\d+)?', a):
            try:
                return float(a)
            except Exception:
                continue
    return None


def _resolve_context_arithmetic(query: str, turns: list[dict]) -> float | None:
    base = _last_numeric_answer(turns)
    if base is None:
        return None
    q = query.lower().strip().replace("what's", 'whats').rstrip('?')
    q = re.sub(r'[^a-z0-9\.\+\-\*\/\(\)\s]', ' ', q)
    q = WHITESPACE_RE.sub(' ', q).strip()

    if not re.search(r'\b(that|it|previous|last)\b', q):
        return None

    # Replace context references with the previous numeric result.
    q = re.sub(r'\b(that|it|previous|last)\b', str(base), q)
    # Normalize verbal operators to symbols.
    q = re.sub(r'\bplus\b', '+', q)
    q = re.sub(r'\bminus\b', '-', q)
    q = re.sub(r'\b(times|multiplied by)\b', '*', q)
    q = re.sub(r'\b(divided by|over)\b', '/', q)
    q = re.sub(r'[^0-9\.\+\-\*\/\(\)\s]', ' ', q)
    q = WHITESPACE_RE.sub(' ', q).strip()
    if not q or not re.search(r'[\+\-\*\/]', q):
        return None
    if not re.fullmatch(r'[\d\s\+\-\*\/\(\)\.]+', q):
        return None
    try:
        val = eval(q, {'__builtins__': {}}, {})  # noqa: S307
        if isinstance(val, (int, float)) and math.isfinite(val):
            return float(val)
    except Exception:
        return None
    return None


def _simple_derivative(query: str) -> str | None:
    q = query.lower().strip().rstrip('?')
    m = re.search(r'derivative of\s+(.+)$', q)
    if not m:
        return None
    expr = m.group(1).strip().replace(' ', '')
    # d/dx x = 1
    if expr == 'x':
        return '1'
    # d/dx c = 0
    if re.fullmatch(r'[-+]?\d+(\.\d+)?', expr):
        return '0'
    # d/dx x^n = n*x^(n-1)
    mp = re.fullmatch(r'x\^([-+]?\d+)', expr)
    if mp:
        n = int(mp.group(1))
        if n == 0:
            return '0'
        if n == 1:
            return '1'
        if n - 1 == 1:
            return f'{n}x'
        if n - 1 == 0:
            return f'{n}'
        return f'{n}x^{n-1}'
    # d/dx a*x = a
    ml = re.fullmatch(r'([-+]?\d+(\.\d+)?)x', expr)
    if ml:
        return str(float(ml.group(1))).rstrip('0').rstrip('.')
    return None


def _basic_query_answer(req: AskRequest, prior_turns: list[dict] | None = None) -> AskResponse | None:
    deriv = _simple_derivative(req.query)
    if deriv is not None:
        return AskResponse(
            answer=deriv,
            citations=[],
            confidence=1.0,
            suggested_followups=[],
            cache_hit=False,
            mode='basic',
        )

    val = _safe_eval_arithmetic(req.query)
    if val is None and prior_turns:
        val = _resolve_context_arithmetic(req.query, prior_turns)
    if val is not None:
        out = int(val) if float(val).is_integer() else round(val, 6)
        return AskResponse(
            answer=f'{out}',
            citations=[],
            confidence=1.0,
            suggested_followups=[],
            cache_hit=False,
            mode='basic',
        )
    return None


def _detected_intents(query: str) -> list[str]:
    q = query.lower()
    found: list[str] = []
    for k, hints in INTENT_HINTS.items():
        if any(h in q for h in hints):
            found.append(k)
    return found


def _primary_intent(query: str) -> str | None:
    q = query.lower()
    scored: list[tuple[int, str]] = []
    for intent, hints in INTENT_HINTS.items():
        hits = sum(1 for h in hints if h in q)
        if hits > 0:
            scored.append((hits, intent))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def _intent_lexical_terms(query: str) -> set[str]:
    out: set[str] = set()
    for intent in _detected_intents(query):
        out.update(INTENT_LEXICAL_TERMS.get(intent, []))
    return out


@dataclass
class RetrievedFact:
    fact_key: str
    fact_value: str
    confidence: float
    document_id: UUID
    title: str
    url: str
    chunk_id: UUID


def _fact_keys_for_query(query: str) -> list[str]:
    intents = _detected_intents(query)
    keys: list[str] = []
    primary = _primary_intent(query)
    if primary and primary in intents:
        intents = [primary] + [i for i in intents if i != primary]
    for intent in intents:
        keys.extend(INTENT_FACT_KEYS.get(intent, []))
    seen: set[str] = set()
    out: list[str] = []
    for k in keys:
        if k in seen:
            continue
        seen.add(k)
        out.append(k)
    return out


def _meets_fact_coverage(intent: str | None, seen_keys: set[str]) -> bool:
    if not intent:
        return True
    required = INTENT_REQUIRED_FACT_KEYS.get(intent)
    if not required:
        return True
    hit = len(required & seen_keys)
    need = max(1, int(math.ceil(len(required) * 0.6)))
    return hit >= need


def _retrieve_acl_facts(
    db: Session,
    req: AskRequest,
    user_email: str,
    fact_keys: list[str],
    limit: int,
) -> list[RetrievedFact]:
    if not fact_keys:
        return []
    group_ids_subq = select(cast(GroupMembership.group_id, String)).where(GroupMembership.user_id == req.user_id)
    acl_exists = (
        select(literal(1))
        .where(DocumentAcl.document_id == Document.id)
        .where(
            or_(
                and_(DocumentAcl.principal_type == 'user', DocumentAcl.principal_id == str(req.user_id)),
                and_(DocumentAcl.principal_type == 'email', DocumentAcl.principal_id == user_email),
                and_(DocumentAcl.principal_type == 'group', DocumentAcl.principal_id.in_(group_ids_subq)),
                and_(DocumentAcl.principal_type == 'public', DocumentAcl.principal_id == 'all'),
            )
        )
        .exists()
    )

    stmt = (
        select(
            Fact.fact_key,
            Fact.fact_value,
            Fact.confidence,
            Fact.document_id,
            Fact.chunk_id,
            Document.title,
            Document.canonical_url,
            Source.name.label('source_name'),
        )
        .join(Document, Document.id == Fact.document_id)
        .join(Source, Source.id == Document.source_id)
        .where(Fact.workspace_id == req.workspace_id, Fact.fact_key.in_(fact_keys))
        .where(acl_exists)
        .order_by(Fact.confidence.desc())
        .limit(limit)
    )

    if not req.use_general_knowledge:
        stmt = stmt.where(~Source.name.ilike('gkb:%'))

    try:
        rows = db.execute(stmt).all()
    except SQLAlchemyError:
        db.rollback()
        return []
    out: list[RetrievedFact] = []
    for r in rows:
        if str(r.canonical_url).startswith('https://example.local'):
            continue
        out.append(
            RetrievedFact(
                fact_key=r.fact_key,
                fact_value=r.fact_value,
                confidence=float(r.confidence or 0.0),
                document_id=r.document_id,
                title=r.title,
                url=r.canonical_url,
                chunk_id=r.chunk_id,
            )
        )
    return out


def _fact_first_answer(
    db: Session,
    req: AskRequest,
    user_email: str,
    persona: str,
    technical_depth: str,
    output_tone: str,
    conciseness: float,
) -> AskResponse | None:
    keys = _fact_keys_for_query(req.query)
    if not keys:
        return None
    intent = _primary_intent(req.query)
    facts = _retrieve_acl_facts(db, req, user_email, keys, limit=24)
    if not facts:
        return None

    by_key: dict[str, RetrievedFact] = {}
    for f in facts:
        if f.fact_key in by_key:
            continue
        by_key[f.fact_key] = f

    max_bullets = _max_bullets_from_conciseness(conciseness)
    if intent in {'zero_trust', 'request_path', 'incident', 'dr'}:
        max_bullets = max(max_bullets, 4)
    if intent == 'zero_trust':
        max_bullets = max(max_bullets, 6)
    ordered_vals: list[str] = []
    for k in keys:
        f = by_key.get(k)
        if not f:
            continue
        label = _render_canonical_label(f.fact_value, persona, technical_depth)
        if label in ordered_vals:
            continue
        ordered_vals.append(label)
        if len(ordered_vals) >= max_bullets:
            break
    if not ordered_vals:
        return None
    if not _meets_fact_coverage(intent, set(by_key.keys())):
        return None

    lead = _tone_prefix(output_tone)
    if intent == 'zero_trust':
        lead = 'TechNova enforces zero-trust with layered controls across network and production access:'
    answer = lead + '\n' + '\n'.join(f'- {v}' for v in ordered_vals)

    citations: list[Citation] = []
    seen_doc: set[str] = set()
    max_citations = _max_citations_from_conciseness(conciseness)
    for k in keys:
        f = by_key.get(k)
        if not f:
            continue
        did = str(f.document_id)
        if did in seen_doc:
            continue
        seen_doc.add(did)
        citations.append(
            Citation(
                document_id=f.document_id,
                title=f.title,
                url=f.url,
                heading_path=None,
                chunk_id=f.chunk_id,
            )
        )
        if len(citations) >= max_citations:
            break

    conf = sum(f.confidence for f in by_key.values()) / max(1, len(by_key))
    return AskResponse(
        answer=answer,
        citations=citations,
        confidence=max(0.0, min(1.0, conf)),
        suggested_followups=['Show source excerpts'],
        cache_hit=False,
        mode='fact',
    )


def _max_overlap(chunks: list[RetrievedChunk], terms: set[str]) -> int:
    if not chunks or not terms:
        return 0
    best = 0
    for c in chunks:
        tokens = _token_set(c.text)
        overlap = _overlap_count(tokens, terms)
        if overlap > best:
            best = overlap
    return best


def _hybrid_rerank(chunks: list[RetrievedChunk], terms: set[str], limit: int) -> list[RetrievedChunk]:
    if not chunks:
        return []
    if not terms:
        return chunks[:limit]

    scored: list[tuple[float, RetrievedChunk]] = []
    for c in chunks:
        tokens = _token_set(c.text)
        overlap = _overlap_count(tokens, terms)
        coverage = overlap / max(1, len(terms))
        # lexical + vector hybrid score
        score = (0.55 * c.score) + (0.45 * coverage)
        if overlap >= 2:
            score += 0.1
        scored.append((score, c))
    scored.sort(key=lambda x: x[0], reverse=True)

    out: list[RetrievedChunk] = []
    seen_chunk: set[str] = set()
    seen_doc: dict[str, int] = {}
    for _, c in scored:
        cid = str(c.chunk_id)
        if cid in seen_chunk:
            continue
        doc_key = str(c.document_id)
        if seen_doc.get(doc_key, 0) >= 3:
            continue
        seen_chunk.add(cid)
        seen_doc[doc_key] = seen_doc.get(doc_key, 0) + 1
        out.append(c)
        if len(out) >= limit:
            break
    return out


def _is_noisy_chunk(chunk: RetrievedChunk) -> bool:
    settings = get_settings()
    ignored_patterns = [p.strip().lower() for p in settings.ignored_source_name_patterns.split(',') if p.strip()]
    if (chunk.url or '').startswith('https://example.local'):
        return True
    title = (chunk.title or '').lower()
    return any(fnmatch.fnmatch(title, pat) for pat in ignored_patterns)


def _confidence(chunks: list[RetrievedChunk]) -> float:
    if not chunks:
        return 0.0

    scores = [c.score for c in chunks]
    top1 = scores[0]
    avg_top = mean(scores)

    doc_counts = Counter(str(c.document_id) for c in chunks)
    consensus = max(doc_counts.values()) / len(chunks)

    confidence = 0.6 * top1 + 0.3 * avg_top + 0.1 * consensus
    return max(0.0, min(1.0, confidence))


def _fallback_extractive_answer(
    query: str,
    chunks: list[RetrievedChunk],
    persona: str,
    technical_depth: str,
    output_tone: str,
    conciseness: float,
) -> LlmAnswer:
    terms = _query_terms(query)
    max_bullets = _max_bullets_from_conciseness(conciseness)

    q = query.lower()
    corpus = '\n'.join(c.text for c in chunks).lower()
    canonical_hits: list[str] = []
    for label, patterns in CANONICAL_FACT_PATTERNS:
        if all(re.search(p, corpus) for p in patterns):
            canonical_hits.append(label)

    candidates: list[tuple[float, str, str]] = []
    for c in chunks:
        for sent in re.split(r'(?<=[.!?])\s+|\n+', c.text):
            s = re.sub(r'\s+', ' ', sent).strip(' -\t')
            if len(s) < 20 or len(s) > 220:
                continue
            tokens = _token_set(s)
            overlap = _overlap_count(tokens, terms)
            min_overlap = 1 if len(terms) <= 4 else 2
            if terms and overlap < min_overlap:
                continue
            score = (2.0 * overlap) + c.score
            if re.search(r'\b(aws|okta|oauth|rbac|mfa|waf|cdn|redis|postgres|prometheus|grafana|elk|opentelemetry|pagerduty|gdpr|soc)\b', s.lower()):
                score += 0.8
            if re.search(r'\d', s):
                score += 0.25
            candidates.append((score, s, str(c.chunk_id)))

    candidates.sort(key=lambda x: x[0], reverse=True)
    picked: list[tuple[str, str]] = []
    seen_norm: set[str] = set()
    for _, sentence, cid in candidates:
        norm = re.sub(r'[^a-z0-9]+', ' ', sentence.lower()).strip()
        if not norm or norm in seen_norm:
            continue
        seen_norm.add(norm)
        picked.append((sentence, cid))
        if len(picked) >= max_bullets:
            break

    if not picked:
        return LlmAnswer(
            answer='I do not have enough relevant evidence to answer this precisely.',
            followups=['Rephrase the question', 'Enable general knowledge', 'Ask a narrower question'],
            cited_chunk_ids=[],
            insufficient_evidence=True,
        )

    lead = _tone_prefix(output_tone)
    body = '\n'.join(f'- {line}' for line, _ in picked)
    cited_ids = [cid for _, cid in picked]

    return LlmAnswer(
        answer=f'{lead}\n{body}',
        followups=['Show source excerpts', 'Give a shorter summary'],
        cited_chunk_ids=cited_ids,
        insufficient_evidence=False,
    )


def _intent_canonical_answer(
    query: str,
    chunks: list[RetrievedChunk],
    persona: str,
    technical_depth: str,
    max_bullets: int,
    output_tone: str,
) -> tuple[str, list[str]] | None:
    intent = _primary_intent(query)
    if not intent:
        return None
    allow = INTENT_CANONICAL_ALLOW.get(intent, set())
    if not allow:
        return None
    corpus = '\n'.join(c.text for c in chunks).lower()
    hits: list[str] = []
    for label, patterns in CANONICAL_FACT_PATTERNS:
        if label not in allow:
            continue
        if all(re.search(p, corpus) for p in patterns):
            hits.append(label)
    if not hits:
        return None
    if intent == 'regions':
        q = query.lower()
        if 'primarily use' in q or 'primary region' in q or 'cloud regions' in q:
            preferred = 'Primary AWS regions: us-east-1 and us-west-2'
            hits = [h for h in hits if h == preferred] or [h for h in hits if 'region' in h.lower()]
        else:
            hits = [h for h in hits if 'region' in h.lower() or 'us-east-1' in h.lower()]
    top = hits[:max_bullets]
    top = [_render_canonical_label(item, persona, technical_depth) for item in top]
    lead = _tone_prefix(output_tone)
    body = '\n'.join(f'- {item}' for item in top)
    cited_ids = [str(c.chunk_id) for c in chunks[: min(4, len(chunks))]]
    return f'{lead}\n{body}', cited_ids


def _canonical_hit_count_in_text(query: str, text: str, persona: str, technical_depth: str) -> int:
    intent = _primary_intent(query)
    if not intent:
        return 0
    allow = INTENT_CANONICAL_ALLOW.get(intent, set())
    if not allow:
        return 0
    lower = text.lower()
    count = 0
    for label in allow:
        rendered = _render_canonical_label(label, persona, technical_depth).lower()
        if rendered in lower:
            count += 1
    return count


def _is_weak_llm_answer(answer: str) -> bool:
    text = (answer or '').strip()
    if not text:
        return True
    if text.endswith(':'):
        return True
    words = re.findall(r'[a-zA-Z0-9_-]+', text)
    if len(words) < 10:
        return True
    if not re.search(r'[\n]|[-•]', text):
        generic = (
            'key mechanisms',
            'following mechanisms',
            'in place',
            'complement each other',
        )
        lower = text.lower()
        if any(g in lower for g in generic):
            return True
    return False


def _supported_answer_lines(answer: str, chunks: list[RetrievedChunk], query: str) -> tuple[str, list[str]]:
    lines = [ln.strip() for ln in answer.splitlines() if ln.strip()]
    if not lines:
        return answer, []

    content_lines: list[str] = []
    for ln in lines:
        cleaned = re.sub(r'^\s*[-•]\s*', '', ln).strip()
        if cleaned:
            content_lines.append(cleaned)
    if not content_lines:
        return answer, []

    qterms = _query_terms(query) | _intent_lexical_terms(query)
    qterms = {t for t in qterms if len(t) > 2}
    qlower = query.lower()
    region_focus = 'region' in qlower or 'regions' in qlower

    keep: list[str] = []
    cited_ids: list[str] = []
    seen_ids: set[str] = set()
    chunk_tokens = [(c, _token_set(c.text)) for c in chunks]
    for ln in content_lines:
        lt = _token_set(ln)
        if len(lt) < 5:
            continue
        if re.fullmatch(r'[A-Z][A-Za-z0-9 &/_-]{3,50}', ln):
            continue
        if qterms:
            qoverlap = _overlap_count(lt, qterms)
            if qoverlap < 1:
                continue
        if region_focus:
            lnl = ln.lower()
            if 'region' not in lnl and not re.search(r'\b[a-z]{2}-[a-z]+-\d\b', lnl):
                continue
        best_overlap = 0
        best_chunk_id: str | None = None
        for c, ct in chunk_tokens:
            overlap = _overlap_count(ct, lt)
            if overlap > best_overlap:
                best_overlap = overlap
                best_chunk_id = str(c.chunk_id)
        if best_overlap >= 3:
            keep.append(ln)
            if best_chunk_id and best_chunk_id not in seen_ids:
                seen_ids.add(best_chunk_id)
                cited_ids.append(best_chunk_id)

    if not keep:
        return '', []
    lead = 'Answer:'
    out = lead + '\n' + '\n'.join(f'- {k}' for k in keep)
    return out, cited_ids


def _citations_from_chunk_ids(
    chunks: list[RetrievedChunk],
    chunk_ids: list[str],
    query_terms: set[str],
    max_items: int = 4,
) -> list[Citation]:
    settings = get_settings()
    ignored_patterns = [p.strip().lower() for p in settings.ignored_source_name_patterns.split(',') if p.strip()]

    def trusted(c: RetrievedChunk) -> bool:
        if (c.url or '').startswith('https://example.local'):
            return False
        lower_title = (c.title or '').lower()
        if any(fnmatch.fnmatch(lower_title, pat) for pat in ignored_patterns):
            return False
        return True

    by_chunk = {str(c.chunk_id): c for c in chunks}
    out: list[Citation] = []
    seen_doc_heading: set[tuple[str, str | None]] = set()

    for cid in chunk_ids:
        c = by_chunk.get(cid)
        if not c:
            continue
        if not trusted(c):
            continue
        key = (str(c.document_id), c.heading_path)
        if key in seen_doc_heading:
            continue
        seen_doc_heading.add(key)
        out.append(
            Citation(
                document_id=c.document_id,
                title=c.title,
                url=c.url,
                heading_path=c.heading_path,
                chunk_id=c.chunk_id,
            )
        )
        if len(out) >= max_items:
            return out

    for c in chunks:
        overlap = _overlap_count(_token_set(c.text), query_terms)
        if overlap < 2:
            continue
        if c.score < 0.6:
            continue
        if not trusted(c):
            continue
        key = (str(c.document_id), c.heading_path)
        if key in seen_doc_heading:
            continue
        seen_doc_heading.add(key)
        out.append(
            Citation(
                document_id=c.document_id,
                title=c.title,
                url=c.url,
                heading_path=c.heading_path,
                chunk_id=c.chunk_id,
            )
        )
        if len(out) >= max_items:
            break

    return out[:max_items]


def _workspace_lanes(db: Session, workspace_id: UUID) -> tuple[list[UUID], list[UUID]]:
    settings = get_settings()
    ignored_patterns = [
        p.strip().lower() for p in settings.ignored_source_name_patterns.split(',') if p.strip()
    ]

    def is_ignored(name: str) -> bool:
        n = (name or '').lower()
        return any(fnmatch.fnmatch(n, pat) for pat in ignored_patterns)

    rows = db.execute(select(Source.id, Source.name).where(Source.workspace_id == workspace_id, Source.status == 'active')).all()
    internal: list[UUID] = []
    general: list[UUID] = []
    for r in rows:
        if is_ignored(r.name or ''):
            continue
        if (r.name or '').startswith('gkb:'):
            general.append(r.id)
        else:
            internal.append(r.id)
    return internal, general


def _retrieve_general_lexical(db: Session, general_ids: list[UUID], terms: set[str], limit: int) -> list[RetrievedChunk]:
    if not general_ids or not terms:
        return []

    clauses = [Chunk.text.ilike(f'%{t}%') for t in list(terms)[:8]]
    if not clauses:
        return []

    rows = db.execute(
        select(
            Chunk.id.label('chunk_id'),
            Document.id.label('document_id'),
            Document.source_id.label('source_id'),
            Document.title.label('title'),
            Document.canonical_url.label('canonical_url'),
            Chunk.heading_path.label('heading_path'),
            Chunk.text.label('text'),
        )
        .join(Document, Document.id == Chunk.document_id)
        .where(Document.source_id.in_(general_ids))
        .where(or_(*clauses))
        .limit(limit)
    ).all()

    out: list[RetrievedChunk] = []
    for r in rows:
        tokens = _token_set(r.text)
        overlap = _overlap_count(tokens, terms)
        score = min(0.95, 0.45 + 0.08 * overlap)
        out.append(
            RetrievedChunk(
                chunk_id=r.chunk_id,
                document_id=r.document_id,
                source_id=r.source_id,
                title=r.title,
                url=r.canonical_url,
                heading_path=r.heading_path,
                text=r.text,
                score=score,
            )
        )
    return out


def _retrieve_internal_lexical(db: Session, source_ids: list[UUID], terms: set[str], limit: int) -> list[RetrievedChunk]:
    if not source_ids or not terms:
        return []
    clauses = [Chunk.text.ilike(f'%{t}%') for t in list(terms)[:12]]
    if not clauses:
        return []
    rows = db.execute(
        select(
            Chunk.id.label('chunk_id'),
            Document.id.label('document_id'),
            Document.source_id.label('source_id'),
            Document.title.label('title'),
            Document.canonical_url.label('canonical_url'),
            Chunk.heading_path.label('heading_path'),
            Chunk.text.label('text'),
        )
        .join(Document, Document.id == Chunk.document_id)
        .where(Document.source_id.in_(source_ids))
        .where(or_(*clauses))
        .limit(limit)
    ).all()
    out: list[RetrievedChunk] = []
    for r in rows:
        tokens = _token_set(r.text)
        overlap = _overlap_count(tokens, terms)
        score = min(0.98, 0.52 + 0.07 * overlap)
        out.append(
            RetrievedChunk(
                chunk_id=r.chunk_id,
                document_id=r.document_id,
                source_id=r.source_id,
                title=r.title,
                url=r.canonical_url,
                heading_path=r.heading_path,
                text=r.text,
                score=score,
            )
        )
    return out


def _retrieve_with_lane_fallback(
    db: Session,
    query_vector: list[float],
    req: AskRequest,
    user_email: str,
    top_k: int,
    min_confidence: float,
) -> list[RetrievedChunk]:
    if req.filters and req.filters.get('source_ids'):
        source_ids = [UUID(v) for v in req.filters['source_ids']]
        raw = retrieve_acl_safe(
            db=db,
            query_vector=query_vector,
            user_id=req.user_id,
            user_email=user_email,
            top_k=max(top_k * 4, 20),
            source_ids=source_ids,
        )
        reranked = _hybrid_rerank(raw, _query_terms(req.query), top_k * 2)
        return [c for c in reranked if not _is_noisy_chunk(c)][:top_k]

    internal_ids, general_ids = _workspace_lanes(db, req.workspace_id)
    if not req.use_general_knowledge:
        general_ids = []
    terms = _query_terms(req.query)
    intent_terms = _intent_lexical_terms(req.query)
    combined_terms = terms | intent_terms
    is_general = _is_general_query(req.query)

    if is_general and general_ids:
        general_chunks = _retrieve_general_lexical(db, general_ids, combined_terms or terms, limit=top_k)
        general_chunks = [c for c in general_chunks if not _is_noisy_chunk(c)]
        if not general_chunks:
            general_raw = retrieve_acl_safe(
                db=db,
                query_vector=query_vector,
                user_id=req.user_id,
                user_email=user_email,
                top_k=max(top_k * 2, 12),
                source_ids=general_ids,
            )
            general_chunks = _hybrid_rerank(general_raw, combined_terms or terms, top_k)
            general_chunks = [c for c in general_chunks if not _is_noisy_chunk(c)]
        if general_chunks:
            return general_chunks[:top_k]

    internal_raw = retrieve_acl_safe(
        db=db,
        query_vector=query_vector,
        user_id=req.user_id,
        user_email=user_email,
        top_k=max(top_k * 4, 24),
        source_ids=internal_ids if internal_ids else None,
    )
    lexical_internal = _retrieve_internal_lexical(
        db=db,
        source_ids=internal_ids,
        terms=combined_terms,
        limit=max(8, top_k * 2),
    )
    internal_chunks = _hybrid_rerank(internal_raw + lexical_internal, combined_terms or terms, top_k * 2)
    internal_chunks = [c for c in internal_chunks if not _is_noisy_chunk(c)][:top_k]

    if not general_ids:
        return internal_chunks

    internal_conf = _confidence(internal_chunks)
    internal_overlap = _max_overlap(internal_chunks, terms)
    if internal_chunks and internal_conf >= min_confidence and internal_overlap >= 1:
        return internal_chunks

    general_chunks = _retrieve_general_lexical(db, general_ids, combined_terms or terms, limit=max(3, top_k // 2))
    general_chunks = [c for c in general_chunks if not _is_noisy_chunk(c)]
    if not general_chunks:
        general_raw = retrieve_acl_safe(
            db=db,
            query_vector=query_vector,
            user_id=req.user_id,
            user_email=user_email,
            top_k=max(12, top_k * 2),
            source_ids=general_ids,
        )
        general_chunks = _hybrid_rerank(general_raw, combined_terms or terms, max(6, top_k))
        general_chunks = [c for c in general_chunks if not _is_noisy_chunk(c)][: max(3, top_k // 2)]

    if not general_chunks:
        return internal_chunks[:top_k]
    if not internal_chunks:
        return general_chunks[:top_k]

    general_slots = min(max(2, top_k // 3), len(general_chunks))
    internal_slots = max(0, top_k - general_slots)
    return internal_chunks[:internal_slots] + general_chunks[:general_slots]


def answer_query(db: Session, redis: Redis, req: AskRequest) -> AskResponse:
    policy = get_policy(req.persona)
    technical_depth = _normalize_depth(req.technical_depth, req.persona)
    conversationalness = max(0.0, min(1.0, float(req.conversationalness)))
    conciseness = max(0.0, min(1.0, float(req.conciseness)))
    output_tone = _normalize_tone(req.output_tone)
    fast_mode = bool(req.fast_mode)

    user = db.scalar(select(User).where(User.id == req.user_id, User.tenant_id == req.tenant_id))
    if not user:
        raise ValueError('user not found')
    cache = CacheService(redis_client=redis, db=db)
    context_key = _context_key(req, req.persona)
    context_state = _load_context(redis, context_key) if req.use_context else {'summary': '', 'turns': []}
    prior_turns = context_state.get('turns', [])
    effective_query = _rewrite_query_with_context(req.query, context_state) if req.use_context else req.query
    effective_req = req.model_copy(update={'query': effective_query})

    # Always evaluate deterministic basic queries on raw input (not context-augmented text).
    basic = _basic_query_answer(req, prior_turns=prior_turns)
    if basic is not None:
        if req.use_context:
            _save_context(redis, context_key, _append_context_turn(context_state, req.query, basic.answer))
        return basic

    embed_cache_key = f'query_embed:{hashlib.sha256(_normalize_query(effective_query).encode("utf-8")).hexdigest()}'
    cached_qv = redis.get(embed_cache_key)
    if cached_qv:
        try:
            query_vector = [float(v) for v in json.loads(cached_qv)]
        except Exception:
            query_vector = embed_text(effective_query)
    else:
        query_vector = embed_text(effective_query)
        try:
            redis.setex(embed_cache_key, 3600, json.dumps(query_vector))
        except Exception:
            pass

    retrieval_top_k = policy.retrieval_top_k
    if fast_mode:
        retrieval_top_k = max(4, min(6, policy.retrieval_top_k // 2))
    chunks = _retrieve_with_lane_fallback(
        db=db,
        query_vector=query_vector,
        req=effective_req,
        user_email=user.email,
        top_k=retrieval_top_k,
        min_confidence=policy.min_confidence,
    )

    if not chunks:
        return AskResponse(
            answer='I could not find any accessible sources for this request. Which source or folder should I search?',
            citations=[],
            confidence=0.0,
            suggested_followups=['Specify a source', 'Request access to a document'],
            cache_hit=False,
            mode='followup',
        )

    confidence = _confidence(chunks)
    context_hash = _context_hash([c.text for c in chunks])
    cache_key = _answer_cache_key(
        req.persona,
        effective_query,
        technical_depth,
        output_tone,
        _conciseness_bucket(conciseness),
        _conversation_bucket(conversationalness),
        fast_mode,
        context_hash,
    )

    cached = cache.get_answer(cache_key)
    if cached:
        if req.use_context:
            cached_answer = AskResponse.model_validate({**cached, 'cache_hit': True})
            _save_context(redis, context_key, _append_context_turn(context_state, req.query, cached_answer.answer))
            return cached_answer
        return AskResponse.model_validate({**cached, 'cache_hit': True})

    if confidence >= 0.9 and not req.explain and not fast_mode:
        citations = _citations_from_chunk_ids(
            chunks,
            [str(c.chunk_id) for c in chunks],
            query_terms=_query_terms(req.query),
            max_items=_max_citations_from_conciseness(conciseness),
        )
        payload = AskResponse(
            answer='High-confidence grounded result. Use "explain" for a richer synthesis.',
            citations=citations,
            confidence=confidence,
            suggested_followups=['Explain this in more detail', 'Compare with last quarter'],
            cache_hit=False,
            mode='citations_only',
        )
        cache.set_answer(cache_key, json.loads(payload.model_dump_json()), policy.cache_ttl_seconds)
        if req.use_context:
            _save_context(redis, context_key, _append_context_turn(context_state, req.query, payload.answer))
        return payload

    if fast_mode and not req.explain:
        llm = _fallback_extractive_answer(
            query=effective_query,
            chunks=chunks,
            persona=req.persona,
            technical_depth=technical_depth,
            output_tone=output_tone,
            conciseness=max(0.75, conciseness),
        )
        citations = _citations_from_chunk_ids(
            chunks,
            llm.cited_chunk_ids,
            query_terms=_query_terms(req.query),
            max_items=min(2, _max_citations_from_conciseness(conciseness)),
        )
        payload = AskResponse(
            answer=llm.answer,
            citations=citations,
            confidence=confidence,
            suggested_followups=llm.followups or ['Ask for explain mode'],
            cache_hit=False,
            mode='fast',
        )
        cache.set_answer(cache_key, json.loads(payload.model_dump_json()), policy.cache_ttl_seconds)
        if req.use_context:
            _save_context(redis, context_key, _append_context_turn(context_state, req.query, payload.answer))
        return payload

    try:
        llm = synthesize_grounded_answer(
            query=effective_query,
            persona=req.persona,
            chunks=chunks,
            technical_depth=technical_depth,
            conversationalness=conversationalness,
            output_tone=output_tone,
            conciseness=conciseness,
        )
        if _is_weak_llm_answer(llm.answer):
            llm = _fallback_extractive_answer(
                query=effective_query,
                chunks=chunks,
                persona=req.persona,
                technical_depth=technical_depth,
                output_tone=output_tone,
                conciseness=conciseness,
            )
    except Exception:
        llm = _fallback_extractive_answer(
            query=effective_query,
            chunks=chunks,
            persona=req.persona,
            technical_depth=technical_depth,
            output_tone=output_tone,
            conciseness=conciseness,
        )

    supported_answer, supported_chunk_ids = _supported_answer_lines(llm.answer, chunks, req.query)
    if supported_answer:
        llm = LlmAnswer(
            answer=supported_answer,
            followups=llm.followups,
            cited_chunk_ids=supported_chunk_ids or llm.cited_chunk_ids,
            insufficient_evidence=False,
        )
    elif not llm.insufficient_evidence and confidence >= policy.min_confidence:
        pass
    elif not llm.insufficient_evidence:
        llm = _fallback_extractive_answer(
            query=effective_query,
            chunks=chunks,
            persona=req.persona,
            technical_depth=technical_depth,
            output_tone=output_tone,
            conciseness=conciseness,
        )
    elif confidence >= policy.min_confidence:
        candidate = _fallback_extractive_answer(
            query=effective_query,
            chunks=chunks,
            persona=req.persona,
            technical_depth=technical_depth,
            output_tone=output_tone,
            conciseness=conciseness,
        )
        if not candidate.insufficient_evidence:
            llm = candidate

    citations = _citations_from_chunk_ids(
        chunks,
        llm.cited_chunk_ids,
        query_terms=_query_terms(req.query),
        max_items=_max_citations_from_conciseness(conciseness),
    )

    if llm.insufficient_evidence or confidence < max(0.25, policy.min_confidence - 0.2):
        payload = AskResponse(
            answer='I found partial evidence but not enough to answer with high confidence. Please narrow scope (account, system, or date range).',
            citations=citations,
            confidence=confidence,
            suggested_followups=llm.followups or ['Narrow time window', 'Specify target system or document'],
            cache_hit=False,
            mode='followup',
        )
    else:
        payload = AskResponse(
            answer=llm.answer,
            citations=citations,
            confidence=confidence,
            suggested_followups=llm.followups or ['Show sources', 'Provide a deeper technical explanation'],
            cache_hit=False,
            mode='grounded',
        )

    cache.set_answer(cache_key, json.loads(payload.model_dump_json()), policy.cache_ttl_seconds)
    if req.use_context:
        _save_context(redis, context_key, _append_context_turn(context_state, req.query, payload.answer))
    return payload
