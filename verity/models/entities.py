from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4
from pydantic import BaseModel, Field


class EntityType(str, Enum):
    CLIENT = "client"
    PERSON = "person"
    COMPANY = "company"


class RelationshipType(str, Enum):
    # Person → Company
    DIRECTOR_OF = "director_of"
    OFFICER_OF = "officer_of"
    SHAREHOLDER_OF = "shareholder_of"
    ADVISER_TO = "adviser_to"
    EMPLOYEE_OF = "employee_of"

    # Company → Company
    SUBSIDIARY_OF = "subsidiary_of"
    INVESTOR_IN = "investor_in"
    ACQUIRER_OF = "acquirer_of"
    COMPETITOR_OF = "competitor_of"
    PARTNER_OF = "partner_of"

    # Client links
    CLIENT_IS = "client_is"           # Client → Company (the legal entity)
    KEY_CONTACT = "key_contact"       # Client → Person

    # Generic
    CONNECTED_TO = "connected_to"


class Client(BaseModel):
    """A firm's client — the top-level commercial relationship."""
    id: UUID = Field(default_factory=uuid4)
    name: str
    matter_ref: Optional[str] = None          # Internal matter/file reference
    practice_area: Optional[str] = None       # e.g. M&A, Dispute Resolution
    relationship_partner: Optional[str] = None
    status: str = "active"                    # active | dormant | closed
    company_number: Optional[str] = None      # Companies House number if known
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Person(BaseModel):
    """A natural person — director, officer, investor, adviser, partner."""
    id: UUID = Field(default_factory=uuid4)
    full_name: str
    date_of_birth_month: Optional[int] = None   # CH only gives month/year
    date_of_birth_year: Optional[int] = None
    nationality: Optional[str] = None
    country_of_residence: Optional[str] = None
    occupation: Optional[str] = None
    companies_house_id: Optional[str] = None    # CH internal person id
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Company(BaseModel):
    """A company or organisation — client entity, counterparty, investor, etc."""
    id: UUID = Field(default_factory=uuid4)
    name: str
    company_number: Optional[str] = None        # Companies House number
    company_type: Optional[str] = None          # ltd, plc, llp, etc.
    jurisdiction: str = "GB"
    registered_address: Optional[str] = None
    incorporation_date: Optional[datetime] = None
    status: Optional[str] = None               # active | dissolved | etc.
    sic_codes: list[str] = Field(default_factory=list)
    industry: Optional[str] = None
    revenue_estimate: Optional[str] = None
    employee_count: Optional[int] = None

    # Firm criteria match
    meets_firm_criteria: Optional[bool] = None
    criteria_notes: Optional[str] = None

    # CH snapshot — last raw data from Companies House
    ch_snapshot: Optional[dict] = None
    ch_snapshot_at: Optional[datetime] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Relationship(BaseModel):
    """An edge in the graph — connects any two entities with evidence."""
    id: UUID = Field(default_factory=uuid4)
    source_type: EntityType
    source_id: UUID
    target_type: EntityType
    target_id: UUID
    relationship_type: RelationshipType
    description: Optional[str] = None
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None         # None = currently active
    evidence_ids: list[UUID] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
