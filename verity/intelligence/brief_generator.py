"""
Brief generator — uses Anthropic + instructor to produce structured OpportunityBriefs
from a ChangeEvent and its surrounding graph context.

Every brief must be evidence-backed. No unsupported claims. Flag → Explain → Support.
"""
from __future__ import annotations

import json
import logging
from typing import Optional
from uuid import UUID

import anthropic
import instructor

from verity.config import get_settings
from verity.graph import repository as repo
from verity.models import ChangeEvent, OpportunityBrief, ConfidenceLevel
from verity.models.briefs import CommercialTrigger, SuggestedApproach, ConflictFlag

logger = logging.getLogger(__name__)


def _make_client() -> instructor.Instructor:
    settings = get_settings()
    raw = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return instructor.from_anthropic(raw)


async def _build_context(event: ChangeEvent, entity_id: Optional[UUID]) -> str:
    """
    Assemble a context block for the LLM from:
    - The change event itself
    - Related clients (if the company is a known client)
    - Network relationships (who else is connected)
    - Firm criteria
    """
    sections: list[str] = []

    # 1. The change
    sections.append(f"""## What Changed
Entity: {event.entity_name}
Change type: {event.change_type.value}
Description: {event.description}
Detected: {event.detected_at.isoformat()}
Raw data: {json.dumps(event.raw_payload or {}, indent=2)[:2000]}
""")

    # 2. Network context
    if entity_id:
        try:
            relationships = await repo.get_entity_relationships("company", entity_id)
            if relationships:
                rel_lines = []
                for r in relationships[:20]:
                    rel_lines.append(
                        f"  - {r['source_type']}:{r['source_id']} "
                        f"--[{r['relationship_type']}]--> "
                        f"{r['target_type']}:{r['target_id']}"
                    )
                sections.append("## Known Relationships\n" + "\n".join(rel_lines))
        except Exception as e:
            logger.warning("Could not fetch relationships: %s", e)

    # 3. Firm criteria
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


SYSTEM_PROMPT = """You are Verity's intelligence engine.

Your job is to analyse a change detected about a company and produce a structured 
Opportunity Brief for a professional law firm.

Rules — non-negotiable:
1. NEVER make a claim without evidence. If you don't have evidence, say so explicitly.
2. NEVER provide conflicts clearance. Conflict flags are for review only.
3. NEVER invent financial figures. Estimate only where the evidence supports it, 
   and state all assumptions.
4. Confidence levels: HIGH = 3+ corroborating sources, MEDIUM = 2 or 1 strong source, 
   LOW = 1 weak source or inferred, UNCERTAIN = unverifiable.
5. The brief must answer: What happened? Why does it matter now? What can the firm do?
6. Keep language precise and professional — you are writing for partners, not consumers.

If the change is routine and no opportunity or risk is apparent, say so clearly in 
what_happened and leave suggested_approaches empty."""


async def generate_brief(event: ChangeEvent, entity_id: Optional[UUID] = None) -> OpportunityBrief:
    """
    Generate a structured OpportunityBrief for a ChangeEvent.
    Uses instructor to enforce the Pydantic schema — the LLM cannot return 
    unstructured output.
    """
    settings = get_settings()
    client = _make_client()

    context = await _build_context(event, entity_id)

    user_message = f"""Analyse this change and produce an Opportunity Brief.

{context}

Produce a complete OpportunityBrief. Be precise. Cite the evidence you have.
If the change is low-significance (e.g. a routine confirmation statement), 
reflect that honestly — don't inflate importance."""

    logger.info("Generating brief for event %s (%s)", event.id, event.entity_name)

    brief: OpportunityBrief = client.chat.completions.create(
        model=settings.anthropic_model,
        max_tokens=4096,
        messages=[
            {"role": "user", "content": user_message},
        ],
        system=SYSTEM_PROMPT,
        response_model=OpportunityBrief,
    )

    # Attach the change event id
    brief.change_event_id = event.id
    if entity_id:
        brief.entity_id = entity_id

    logger.info("Brief generated: %s (confidence: %s)", brief.title, brief.confidence)
    return brief
