"""
Change detector — diffs Companies House snapshots to emit ChangeEvents.
Runs as part of the Celery polling worker.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional
from uuid import uuid4

from verity.models import ChangeEvent, ChangeType, Evidence, EvidenceSource
from verity.graph import repository as repo

logger = logging.getLogger(__name__)


def _officer_key(officer: dict) -> str:
    """Stable identity key for a CH officer record."""
    return officer.get("links", {}).get("officer", {}).get("appointments", "") or officer.get("name", "")


def _psc_key(psc: dict) -> str:
    return psc.get("links", {}).get("self", "") or psc.get("name", "")


def _filing_key(filing: dict) -> str:
    return filing.get("transaction_id", "") or filing.get("description", "") + filing.get("date", "")


def diff_snapshots(
    company_number: str,
    company_name: str,
    previous: Optional[dict],
    current: dict,
) -> list[ChangeEvent]:
    """
    Compare two CH snapshots and return ChangeEvents for everything that changed.
    Returns an empty list if this is the first snapshot (nothing to diff against).
    """
    if previous is None:
        logger.info("First snapshot for %s — no diff", company_number)
        return []

    events: list[ChangeEvent] = []
    now = datetime.utcnow()

    # ── Company status ────────────────────────────────────────────────────────
    prev_status = previous.get("profile", {}).get("company_status")
    curr_status = current.get("profile", {}).get("company_status")
    if prev_status and curr_status and prev_status != curr_status:
        events.append(ChangeEvent(
            id=uuid4(),
            change_type=ChangeType.STATUS_CHANGED,
            entity_type="company",
            entity_id=uuid4(),  # will be resolved to real ID by caller
            entity_name=company_name,
            description=f"Company status changed from '{prev_status}' to '{curr_status}'",
            raw_payload={"previous_status": prev_status, "current_status": curr_status},
            detected_at=now,
        ))

    # ── Officers ──────────────────────────────────────────────────────────────
    prev_officers = {_officer_key(o): o for o in previous.get("active_officers", [])}
    curr_officers = {_officer_key(o): o for o in current.get("active_officers", [])}

    for key, officer in curr_officers.items():
        if key not in prev_officers:
            name = officer.get("name", "Unknown")
            role = officer.get("officer_role", "officer")
            events.append(ChangeEvent(
                id=uuid4(),
                change_type=ChangeType.OFFICER_APPOINTED,
                entity_type="company",
                entity_id=uuid4(),
                entity_name=company_name,
                description=f"New {role} appointed: {name}",
                raw_payload={"officer": officer},
                detected_at=now,
            ))

    for key, officer in prev_officers.items():
        if key not in curr_officers:
            name = officer.get("name", "Unknown")
            role = officer.get("officer_role", "officer")
            events.append(ChangeEvent(
                id=uuid4(),
                change_type=ChangeType.OFFICER_RESIGNED,
                entity_type="company",
                entity_id=uuid4(),
                entity_name=company_name,
                description=f"{role.capitalize()} resigned: {name}",
                raw_payload={"officer": officer},
                detected_at=now,
            ))

    # ── PSC (significant control) ─────────────────────────────────────────────
    prev_pscs = {_psc_key(p): p for p in previous.get("pscs", [])}
    curr_pscs = {_psc_key(p): p for p in current.get("pscs", [])}

    for key, psc in curr_pscs.items():
        if key not in prev_pscs:
            name = psc.get("name", "Unknown")
            nature = ", ".join(psc.get("natures_of_control", []))
            events.append(ChangeEvent(
                id=uuid4(),
                change_type=ChangeType.PSC_REGISTERED,
                entity_type="company",
                entity_id=uuid4(),
                entity_name=company_name,
                description=f"New person with significant control: {name} ({nature})",
                raw_payload={"psc": psc},
                detected_at=now,
            ))

    for key, psc in prev_pscs.items():
        if key not in curr_pscs:
            name = psc.get("name", "Unknown")
            events.append(ChangeEvent(
                id=uuid4(),
                change_type=ChangeType.PSC_CEASED,
                entity_type="company",
                entity_id=uuid4(),
                entity_name=company_name,
                description=f"Person with significant control ceased: {name}",
                raw_payload={"psc": psc},
                detected_at=now,
            ))

    # ── New filings ───────────────────────────────────────────────────────────
    prev_filings = {_filing_key(f) for f in previous.get("recent_filings", [])}
    for filing in current.get("recent_filings", []):
        if _filing_key(filing) not in prev_filings:
            desc = filing.get("description_values", {}) or {}
            category = filing.get("category", "")
            filing_desc = filing.get("description", "new filing")
            events.append(ChangeEvent(
                id=uuid4(),
                change_type=ChangeType.NEW_FILING,
                entity_type="company",
                entity_id=uuid4(),
                entity_name=company_name,
                description=f"New {category} filing: {filing_desc}",
                raw_payload={"filing": filing},
                detected_at=now,
            ))

    # ── Charges ───────────────────────────────────────────────────────────────
    prev_charge_ids = {
        c.get("charge_number") for c in previous.get("charges", [])
    }
    for charge in current.get("charges", []):
        charge_num = charge.get("charge_number")
        if charge_num and charge_num not in prev_charge_ids:
            amount = charge.get("particulars", {}).get("description", "")
            events.append(ChangeEvent(
                id=uuid4(),
                change_type=ChangeType.CHARGE_REGISTERED,
                entity_type="company",
                entity_id=uuid4(),
                entity_name=company_name,
                description=f"New charge registered: {amount or charge_num}",
                raw_payload={"charge": charge},
                detected_at=now,
            ))

    if events:
        logger.info(
            "Detected %d change(s) for %s (%s)",
            len(events), company_name, company_number,
        )
    return events
