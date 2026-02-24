from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from app.config import get_settings
from app.services.retrieval_service import RetrievedChunk


@dataclass
class LlmAnswer:
    answer: str
    followups: list[str]
    cited_chunk_ids: list[str]
    insufficient_evidence: bool


def _build_evidence(chunks: list[RetrievedChunk]) -> list[dict]:
    out: list[dict] = []
    for c in chunks:
        out.append(
            {
                'chunk_id': str(c.chunk_id),
                'document_title': c.title,
                'document_url': c.url,
                'heading_path': c.heading_path,
                'text': c.text[:900],
            }
        )
    return out


def synthesize_grounded_answer(
    query: str,
    persona: str,
    chunks: list[RetrievedChunk],
    technical_depth: str = 'medium',
    conversationalness: float = 0.5,
    output_tone: str = 'direct',
    conciseness: float = 0.6,
) -> LlmAnswer:
    settings = get_settings()

    evidence = _build_evidence(chunks)
    system = (
        'You are a retrieval-grounded assistant. Use only the provided evidence. '
        'Return concise direct answers. No speculation. '
        'If evidence is insufficient, set insufficient_evidence=true and provide a short clarifying question.'
    )

    depth_instructions = {
        'low': 'Use client-safe language. Minimize jargon and infrastructure acronyms unless necessary.',
        'medium': 'Balance clarity with technical precision.',
        'high': 'Use precise technical terminology and architecture details.',
    }
    convo_instructions = {
        'low': 'Keep tone direct and formal. Avoid conversational fillers.',
        'medium': 'Use clear, plain language with moderate conversational tone.',
        'high': 'Use friendly conversational wording while staying concise and factual.',
    }
    if conversationalness < 0.34:
        convo_key = 'low'
    elif conversationalness > 0.66:
        convo_key = 'high'
    else:
        convo_key = 'medium'
    tone_instructions = {
        'friendly': 'Tone: warm and helpful.',
        'direct': 'Tone: direct and efficient.',
        'critical': 'Tone: skeptical and strict; prioritize precision and caveats.',
    }
    conciseness = max(0.0, min(1.0, float(conciseness)))
    if conciseness >= 0.75:
        length_instruction = 'Very concise: 1 sentence or max 2 bullets.'
    elif conciseness >= 0.5:
        length_instruction = 'Concise: short lead + max 3 bullets.'
    else:
        length_instruction = 'Detailed but focused: short lead + max 5 bullets.'

    user_payload = {
        'persona': persona,
        'technical_depth': technical_depth,
        'output_tone': output_tone,
        'conciseness': conciseness,
        'query': query,
        'instructions': [
            'Answer with a direct lead sentence, then up to 5 compact bullets for key mechanisms.',
            'Cite only chunk_ids that directly support the answer.',
            'Prefer precise facts over broad summaries.',
            'Do not include unsupported claims.',
            'Synthesize across multiple evidence chunks when the question asks for mechanisms, stack components, or process flow.',
            depth_instructions.get(technical_depth, depth_instructions['medium']),
            convo_instructions[convo_key],
            tone_instructions.get(output_tone, tone_instructions['direct']),
            length_instruction,
        ],
        'evidence': evidence,
        'output_schema': {
            'answer': 'string',
            'followups': ['string'],
            'cited_chunk_ids': ['string'],
            'insufficient_evidence': 'boolean',
        },
    }

    body = {
        'model': settings.ollama_model,
        'stream': False,
        'format': 'json',
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': json.dumps(user_payload)},
        ],
        'options': {
            'temperature': 0,
        },
    }

    with httpx.Client(timeout=settings.ollama_timeout_seconds) as client:
        resp = client.post(f"{settings.ollama_base_url.rstrip('/')}/api/chat", json=body)
        resp.raise_for_status()
        data = resp.json()

    content = data.get('message', {}).get('content', '{}')
    parsed = json.loads(content)

    answer = str(parsed.get('answer', '')).strip()
    followups = [str(x) for x in parsed.get('followups', [])][:3]
    cited_chunk_ids = [str(x) for x in parsed.get('cited_chunk_ids', [])]
    insufficient = bool(parsed.get('insufficient_evidence', False))

    if not answer:
        answer = 'I could not produce a grounded answer from the available evidence.'

    return LlmAnswer(
        answer=answer,
        followups=followups,
        cited_chunk_ids=cited_chunk_ids,
        insufficient_evidence=insufficient,
    )
