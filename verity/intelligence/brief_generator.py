"""
Brief generator — uses Hermes (via Ollama) + instructor to produce structured
OpportunityBriefs from a ChangeEvent and its surrounding graph context.

Hermes runs locally inside the firm's Docker environment — no data leaves.
Ollama exposes an OpenAI-compatible API at http://ollama:11434/v1.

Fallback to Anthropic available via LLM_BACKEND=anthropic in .env.
"""
from __future__ import annotations

import json
import logging
from typing import Optional
from uuid import UUID

import instructor
from openai import OpenAI

from verity.config import get_settings
from verity.graph import repository as repo
from verity.models import ChangeEvent, OpportunityBrief
from verity.models.briefs import CommercialTrigger, SuggestedApproach, ConflictFlag

logger = logging.getLogger(__name__)


def _make_client() -> instructor.Instructor:
    settings = get_settings()

    if settings.llm_backend == "anthropic":
        import anthropic as _anthropic
        raw = _anthropic.Anthropic(api_key=settings.anthropic_api_key)
        return instructor.from_anthropic(raw)

    # Default: Hermes via Ollama (fully local, no external calls)
    raw = OpenAI(
        base_url=settings.ollama_base_url,
        api_key="ollama",   # required by the OpenAI client but not used by Ollama
    )
    return instructor.from_openai(raw, mode=instructor.Mode.JSON)


def _model_name() -> str:
    settings = get_settings()
    if settings.llm_backend == "anthropic":
        return settings.anthropic_model
    return settings.ollama_model


async def _build_context(event: ChangeEvent, entity_id: Optional[UUID]) -> str:
    """
    Assemble a context block for the LLM from:
    - The change event itself
    - Related clients (if the company is a known client)
    - Network relationships (who else is connected)
    - Firm criteria
    """
    sections: list[str] = []

    sections.append(f"""## What Changed
Entity: {event.entity_name}
Change type: {event.change_type.value}
Description: {event.description}
Detected: {event.detected_at.isoformat()}
Raw data: {json.dumps(event.raw_payload or {}, indent=2)[:2000]}
""")

    if entity_id:
        try:
            relationships = await repo.get_entity_relationships("company", entity_id)
            if relationships:
                rel_lines = [
                    f"  - {r['source_type']}:{r['source_id']} "
                    f"--[{r['relationship_type']}]--> "
                    f"{r['target_type']}:{r['target_id']}"
                    for r in relationships[:20]
                ]
                sections.append("## Known Relationships\n" + "\n".join(rel_lines))
        except Exception as e:
            logger.warning("Could not fetch relationships: %s", e)

    try:
        p = await repo.pool()
        criteria_rows = await p.fetch(
            "SELECT * FROM firm_criteria WHERE active=TRUE LIMIT 1"
        )
        if criteria_rows:
            c = dict(criteria_rows[0])
            sections.append(f"""## Firm Criteria
Name: {c['name']}
Criteria: {json.dumps(c['criteria'], indent=2)}
""")
    except Exception as e:
        logger.warning("Could not fetch firm criteria: %s", e)

    return "\n".join(sections)


SYSTEM_PROMPT = """You are Verity's intelligence engine for a professional law firm.

Your job is to analyse a detected change and produce a structured Opportunity Brief.

Rules — non-negotiable:
1. NEVER make a claim without evidence. If you lack evidence, say so explicitly.
2. NEVER provide conflicts clearance. Conflict flags are for review only.
3. NEVER invent financial figures. Estimate only where evidence supports it; state all assumptions.
4. Confidence: HIGH = 3+ corroborating sources, MEDIUM = 2 or 1 strong, LOW = 1 weak or inferred.
5. Answer: What happened? Why does it matter now? What can the firm do?
6. Language: precise and professional — you are writing for partners, not consumers.

If the change is routine with no apparent opportunity or risk, say so clearly."""


async def generate_brief(
    event: ChangeEvent, entity_id: Optional[UUID] = None
) -> OpportunityBrief:
    """
    Generate a structured OpportunityBrief for a ChangeEvent.
    instructor enforces the Pydantic schema — the LLM cannot return unstructured output.
    """
    client = _make_client()
    model = _model_name()
    context = await _build_context(event, entity_id)

    user_message = f"""Analyse this change and produce an Opportunity Brief.

{context}

Produce a complete OpportunityBrief. Be precise. Cite the evidence you have.
If the change is low-significance (e.g. a routine confirmation statement),
reflect that honestly — do not inflate importance."""

    logger.info(
        "Generating brief via %s/%s for event %s (%s)",
        get_settings().llm_backend, model, event.id, event.entity_name,
    )

    brief: OpportunityBrief = client.chat.completions.create(
        model=model,
        max_tokens=4096,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        response_model=OpportunityBrief,
    )

    brief.change_event_id = event.id
    if entity_id:
        brief.entity_id = entity_id

    logger.info("Brief generated: %s (confidence: %s)", brief.title, brief.confidence)
    return brief
