"""
Database repository — async Postgres via asyncpg.
All graph queries live here; nothing else touches the DB directly.
"""
from __future__ import annotations

import json
from typing import Optional
from uuid import UUID

import asyncpg

from verity.config import get_settings
from verity.models import (
    Client, Person, Company, Relationship,
    Evidence, ChangeEvent, OpportunityBrief,
)


async def get_pool() -> asyncpg.Pool:
    settings = get_settings()
    # asyncpg uses standard postgres:// URL
    url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    return await asyncpg.create_pool(url, min_size=2, max_size=10)


_pool: Optional[asyncpg.Pool] = None


async def pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await get_pool()
    return _pool


# ── Clients ───────────────────────────────────────────────────────────────────

async def upsert_client(client: Client) -> Client:
    p = await pool()
    await p.execute(
        """
        INSERT INTO clients (id, name, matter_ref, practice_area,
            relationship_partner, status, company_number, notes)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
        ON CONFLICT (id) DO UPDATE SET
            name=EXCLUDED.name, matter_ref=EXCLUDED.matter_ref,
            practice_area=EXCLUDED.practice_area,
            relationship_partner=EXCLUDED.relationship_partner,
            status=EXCLUDED.status, company_number=EXCLUDED.company_number,
            notes=EXCLUDED.notes
        """,
        client.id, client.name, client.matter_ref, client.practice_area,
        client.relationship_partner, client.status,
        client.company_number, client.notes,
    )
    return client


async def get_client(client_id: UUID) -> Optional[dict]:
    p = await pool()
    row = await p.fetchrow("SELECT * FROM clients WHERE id=$1", client_id)
    return dict(row) if row else None


async def list_clients(status: str = "active") -> list[dict]:
    p = await pool()
    rows = await p.fetch("SELECT * FROM clients WHERE status=$1 ORDER BY name", status)
    return [dict(r) for r in rows]


# ── Companies ─────────────────────────────────────────────────────────────────

async def upsert_company(company: Company) -> Company:
    p = await pool()
    await p.execute(
        """
        INSERT INTO companies (id, name, company_number, company_type,
            jurisdiction, registered_address, incorporation_date, status,
            sic_codes, industry, ch_snapshot, ch_snapshot_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
        ON CONFLICT (company_number) DO UPDATE SET
            name=EXCLUDED.name, company_type=EXCLUDED.company_type,
            registered_address=EXCLUDED.registered_address,
            status=EXCLUDED.status, sic_codes=EXCLUDED.sic_codes,
            ch_snapshot=EXCLUDED.ch_snapshot, ch_snapshot_at=EXCLUDED.ch_snapshot_at
        """,
        company.id, company.name, company.company_number, company.company_type,
        company.jurisdiction, company.registered_address,
        company.incorporation_date, company.status,
        company.sic_codes,
        company.industry,
        json.dumps(company.ch_snapshot) if company.ch_snapshot else None,
        company.ch_snapshot_at,
    )
    return company


async def get_company_by_number(company_number: str) -> Optional[dict]:
    p = await pool()
    row = await p.fetchrow(
        "SELECT * FROM companies WHERE company_number=$1", company_number
    )
    return dict(row) if row else None


async def search_companies(query: str, limit: int = 20) -> list[dict]:
    p = await pool()
    rows = await p.fetch(
        """
        SELECT *, ts_rank(to_tsvector('english', name), plainto_tsquery('english', $1)) AS rank
        FROM companies
        WHERE to_tsvector('english', name) @@ plainto_tsquery('english', $1)
        ORDER BY rank DESC LIMIT $2
        """,
        query, limit,
    )
    return [dict(r) for r in rows]


# ── People ────────────────────────────────────────────────────────────────────

async def upsert_person(person: Person) -> Person:
    p = await pool()
    await p.execute(
        """
        INSERT INTO people (id, full_name, date_of_birth_month, date_of_birth_year,
            nationality, country_of_residence, occupation, companies_house_id, notes)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
        ON CONFLICT (companies_house_id) DO UPDATE SET
            full_name=EXCLUDED.full_name,
            nationality=EXCLUDED.nationality,
            country_of_residence=EXCLUDED.country_of_residence,
            occupation=EXCLUDED.occupation
        """,
        person.id, person.full_name, person.date_of_birth_month,
        person.date_of_birth_year, person.nationality,
        person.country_of_residence, person.occupation,
        person.companies_house_id, person.notes,
    )
    return person


# ── Relationships ─────────────────────────────────────────────────────────────

async def upsert_relationship(rel: Relationship) -> Relationship:
    p = await pool()
    await p.execute(
        """
        INSERT INTO relationships (id, source_type, source_id, target_type, target_id,
            relationship_type, description, valid_from, valid_to, evidence_ids)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
        ON CONFLICT (source_type, source_id, target_type, target_id, relationship_type)
        DO UPDATE SET description=EXCLUDED.description, valid_to=EXCLUDED.valid_to,
            evidence_ids=EXCLUDED.evidence_ids
        """,
        rel.id, rel.source_type.value, rel.source_id,
        rel.target_type.value, rel.target_id,
        rel.relationship_type.value, rel.description,
        rel.valid_from, rel.valid_to, rel.evidence_ids,
    )
    return rel


async def get_entity_relationships(
    entity_type: str, entity_id: UUID, active_only: bool = True
) -> list[dict]:
    """All relationships touching an entity (as source or target)."""
    p = await pool()
    clause = "AND valid_to IS NULL" if active_only else ""
    rows = await p.fetch(
        f"""
        SELECT * FROM relationships
        WHERE (source_type=$1 AND source_id=$2)
           OR (target_type=$1 AND target_id=$2)
        {clause}
        ORDER BY created_at DESC
        """,
        entity_type, entity_id,
    )
    return [dict(r) for r in rows]


async def get_network(entity_type: str, entity_id: UUID, depth: int = 2) -> list[dict]:
    """
    Walk the graph up to `depth` hops from an entity.
    Uses a recursive CTE — no separate graph DB needed.
    """
    p = await pool()
    rows = await p.fetch(
        """
        WITH RECURSIVE network AS (
            -- Seed
            SELECT source_type, source_id, target_type, target_id,
                   relationship_type, 1 AS depth
            FROM relationships
            WHERE (source_type=$1 AND source_id=$2)
               OR (target_type=$1 AND target_id=$2)
               AND valid_to IS NULL

            UNION ALL

            -- Walk outward
            SELECT r.source_type, r.source_id, r.target_type, r.target_id,
                   r.relationship_type, n.depth + 1
            FROM relationships r
            JOIN network n ON (
                (r.source_type=n.target_type AND r.source_id=n.target_id)
             OR (r.target_type=n.source_type AND r.target_id=n.source_id)
            )
            WHERE n.depth < $3 AND r.valid_to IS NULL
        )
        SELECT DISTINCT * FROM network
        """,
        entity_type, entity_id, depth,
    )
    return [dict(r) for r in rows]


# ── Evidence ──────────────────────────────────────────────────────────────────

async def save_evidence(ev: Evidence) -> Evidence:
    p = await pool()
    await p.execute(
        """
        INSERT INTO evidence (id, source, source_url, source_date, source_label,
            headline, raw_data, entity_type, entity_id)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
        ON CONFLICT (id) DO NOTHING
        """,
        ev.id, ev.source.value, ev.source_url, ev.source_date,
        ev.source_label, ev.headline,
        json.dumps(ev.raw_data) if ev.raw_data else None,
        ev.entity_type, ev.entity_id,
    )
    return ev


# ── Change events ─────────────────────────────────────────────────────────────

async def save_change_event(event: ChangeEvent) -> ChangeEvent:
    p = await pool()
    await p.execute(
        """
        INSERT INTO change_events (id, change_type, entity_type, entity_id,
            entity_name, description, evidence_ids, raw_payload, processed, detected_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
        ON CONFLICT (id) DO NOTHING
        """,
        event.id, event.change_type.value, event.entity_type,
        event.entity_id, event.entity_name, event.description,
        event.evidence_ids,
        json.dumps(event.raw_payload) if event.raw_payload else None,
        event.processed, event.detected_at,
    )
    return event


async def get_unprocessed_events(limit: int = 50) -> list[dict]:
    p = await pool()
    rows = await p.fetch(
        """
        SELECT * FROM change_events
        WHERE processed = FALSE
        ORDER BY detected_at ASC
        LIMIT $1
        """,
        limit,
    )
    return [dict(r) for r in rows]


async def mark_event_processed(event_id: UUID, brief_id: Optional[UUID] = None) -> None:
    p = await pool()
    await p.execute(
        "UPDATE change_events SET processed=TRUE, brief_id=$2 WHERE id=$1",
        event_id, brief_id,
    )


# ── Briefs ────────────────────────────────────────────────────────────────────

async def save_brief(brief: OpportunityBrief) -> OpportunityBrief:
    p = await pool()
    conflict_flags_json = json.dumps(
        [cf.model_dump() for cf in brief.conflict_flags]
    )
    commercial_trigger_json = json.dumps(brief.commercial_trigger.model_dump())
    suggested_approaches_json = json.dumps(
        [sa.model_dump() for sa in brief.suggested_approaches]
    )
    await p.execute(
        """
        INSERT INTO briefs (id, title, entity_name, entity_id, what_happened,
            evidence_summary, confidence, conflict_flags, commercial_trigger,
            suggested_approaches, financial_analysis, financial_assumptions,
            meets_firm_criteria, criteria_assessment, change_event_id, generated_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
        ON CONFLICT (id) DO NOTHING
        """,
        brief.id, brief.title, brief.entity_name, brief.entity_id,
        brief.what_happened, brief.evidence_summary,
        brief.confidence.value,
        conflict_flags_json,
        commercial_trigger_json,
        suggested_approaches_json,
        brief.financial_analysis, brief.financial_assumptions,
        brief.meets_firm_criteria, brief.criteria_assessment,
        brief.change_event_id, brief.generated_at,
    )
    return brief


async def list_briefs(reviewed: Optional[bool] = None, limit: int = 50) -> list[dict]:
    p = await pool()
    clause = "" if reviewed is None else f"WHERE reviewed={str(reviewed).upper()}"
    rows = await p.fetch(
        f"SELECT * FROM briefs {clause} ORDER BY generated_at DESC LIMIT $1", limit
    )
    return [dict(r) for r in rows]


# ── Monitoring ────────────────────────────────────────────────────────────────

async def get_monitoring_targets(active_only: bool = True) -> list[dict]:
    p = await pool()
    clause = "WHERE active=TRUE" if active_only else ""
    rows = await p.fetch(f"SELECT * FROM monitoring_targets {clause}")
    return [dict(r) for r in rows]


async def update_monitoring_snapshot(
    company_number: str, snapshot: dict
) -> None:
    p = await pool()
    await p.execute(
        """
        UPDATE monitoring_targets
        SET last_polled_at=NOW(), last_snapshot=$2
        WHERE company_number=$1
        """,
        company_number, json.dumps(snapshot),
    )
