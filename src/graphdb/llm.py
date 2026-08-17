"""Thin OpenAI-compatible client for the narrow LLM roles in CLAUDE.md
"5단계" (edge_type disambiguation for a small closed set of candidates,
entity typing/alias augmentation for context-dependent mentions).

This is deliberately NOT a general "extract entities/relations from text"
client — every call site constrains the model's output to a fixed set of
already-known candidates (structured output / JSON schema), never free-form
extraction. See CLAUDE.md "5단계 > 규칙 기반 vs LLM 역할 경계".
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any

from openai import OpenAI

from graphdb.config import get_llm_settings

logger = logging.getLogger(__name__)


@lru_cache
def get_llm_client() -> OpenAI:
    settings = get_llm_settings()
    return OpenAI(base_url=settings.base_url, api_key=settings.api_key)


@lru_cache
def get_model_id() -> str:
    """Ask the server what it actually has loaded rather than trusting
    VLLM_MODEL_NAME in .env.dev (CLAUDE.md 2026-08-15: that value drifted
    from the real served model id and 404s if hardcoded)."""
    client = get_llm_client()
    models = client.models.list()
    data = list(models.data)
    if not data:
        raise RuntimeError("vLLM server returned no models from /v1/models")
    model_id = data[0].id
    logger.info("LLM model discovered: %s", model_id)
    return model_id


def chat_json(
    system: str,
    user: str,
    schema: dict[str, Any],
    *,
    schema_name: str = "response",
    temperature: float = 0.0,
    max_tokens: int = 4096,
) -> Any:
    """One structured-output chat call, response constrained to `schema`
    (JSON Schema). Returns the parsed JSON value (dict or list depending on
    schema). Raises on transport/parse errors — callers decide how to
    degrade (e.g. fall back to the rule-based default, mark the record
    accordingly for the extraction_method audit trail)."""
    client = get_llm_client()
    model = get_model_id()
    response = client.chat.completions.create(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": schema_name, "schema": schema, "strict": True},
        },
    )
    content = response.choices[0].message.content
    return json.loads(content)


def chat_text(
    system: str,
    user: str,
    *,
    temperature: float = 0.2,
    max_tokens: int = 1024,
) -> str:
    """Plain free-text completion — used only by the RAG query API's answer
    generation (`graphdb.query.rag`), a genuinely different LLM role from
    the narrow closed-candidate classification calls above: it summarizes
    already-extracted graph facts into a natural-language answer for a user
    question, rather than deciding/reinterpreting any relation. Kept in this
    module anyway since it's the same vLLM endpoint/client plumbing."""
    client = get_llm_client()
    model = get_model_id()
    response = client.chat.completions.create(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return response.choices[0].message.content or ""
