from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Optional, Any
from uuid import UUID, uuid4
from pydantic import BaseModel, Field


class EvidenceSource(str, Enum):
    COMPANIES_HOUSE = "companies_house"
    SEC_EDGAR = "sec_edgar"
    NEWS = "news"
    BLOOMBERG = "bloomberg"
    MANUAL = "manual"
    OPENCORPORATES = "opencorporates"


class Evidence(BaseModel):
    """A single piece of traceable evidence supporting a claim."""
    id: UUID = Field(default_factory=uuid4)
    source: EvidenceSource
    source_url: Optional[str] = None
    source_date: Optional[datetime] = None
    source_label: str                           # Human-readable: "Companies House filing · 14 Aug 2026"
    headline: str                               # One-line summary of what this evidence shows
    raw_data: Optional[dict[str, Any]] = None  # Full raw payload from source
    entity_type: Optional[str] = None
    entity_id: Optional[UUID] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ChangeType(str, Enum):
    # Companies House events
    NEW_FILING = "new_filing"
    OFFICER_APPOINTED = "officer_appointed"
    OFFICER_RESIGNED = "officer_resigned"
    PSC_REGISTERED = "psc_registered"           # Person with significant control
    PSC_CEASED = "psc_ceased"
    ADDRESS_CHANGED = "address_changed"
    STATUS_CHANGED = "status_changed"           # e.g. active → dissolved
    CHARGE_REGISTERED = "charge_registered"     # Mortgage/charge
    CHARGE_SATISFIED = "charge_satisfied"

    # Market / news events
    ACQUISITION_SIGNAL = "acquisition_signal"
    FINANCING_EVENT = "financing_event"
    REGULATORY_DEVELOPMENT = "regulatory_development"
    NEWS_MENTION = "news_mention"

    # Manual
    MANUAL_NOTE = "manual_note"


class ChangeEvent(BaseModel):
    """Emitted when Verity detects something new about an entity."""
    id: UUID = Field(default_factory=uuid4)
    change_type: ChangeType
    entity_type: str
    entity_id: UUID
    entity_name: str                            # Denormalised for logging
    description: str                            # What changed
    evidence_ids: list[UUID] = Field(default_factory=list)
    raw_payload: Optional[dict[str, Any]] = None
    processed: bool = False                     # Has the intelligence loop handled this?
    brief_id: Optional[UUID] = None            # If a brief was generated
    detected_at: datetime = Field(default_factory=datetime.utcnow)
