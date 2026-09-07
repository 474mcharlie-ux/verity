-- Verity — PostgreSQL schema
-- Run with: psql $DATABASE_URL -f schema.sql

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";   -- pgvector for semantic search

-- ── Clients ──────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS clients (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            TEXT NOT NULL,
    matter_ref      TEXT,
    practice_area   TEXT,
    relationship_partner TEXT,
    status          TEXT NOT NULL DEFAULT 'active',
    company_number  TEXT,                   -- CH number if known
    notes           TEXT,
    embedding       vector(1536),           -- for semantic search
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── People ────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS people (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    full_name               TEXT NOT NULL,
    date_of_birth_month     INT,
    date_of_birth_year      INT,
    nationality             TEXT,
    country_of_residence    TEXT,
    occupation              TEXT,
    companies_house_id      TEXT UNIQUE,
    notes                   TEXT,
    embedding               vector(1536),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS people_name_idx ON people USING gin(to_tsvector('english', full_name));
CREATE INDEX IF NOT EXISTS people_ch_id_idx ON people (companies_house_id) WHERE companies_house_id IS NOT NULL;

-- ── Companies ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS companies (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name                TEXT NOT NULL,
    company_number      TEXT UNIQUE,
    company_type        TEXT,
    jurisdiction        TEXT NOT NULL DEFAULT 'GB',
    registered_address  TEXT,
    incorporation_date  DATE,
    status              TEXT,
    sic_codes           TEXT[],
    industry            TEXT,
    revenue_estimate    TEXT,
    employee_count      INT,
    meets_firm_criteria BOOLEAN,
    criteria_notes      TEXT,
    ch_snapshot         JSONB,              -- raw CH snapshot
    ch_snapshot_at      TIMESTAMPTZ,
    embedding           vector(1536),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS companies_name_idx ON companies USING gin(to_tsvector('english', name));
CREATE INDEX IF NOT EXISTS companies_ch_number_idx ON companies (company_number) WHERE company_number IS NOT NULL;
CREATE INDEX IF NOT EXISTS companies_status_idx ON companies (status);

-- ── Relationships ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS relationships (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_type         TEXT NOT NULL,      -- client | person | company
    source_id           UUID NOT NULL,
    target_type         TEXT NOT NULL,
    target_id           UUID NOT NULL,
    relationship_type   TEXT NOT NULL,
    description         TEXT,
    valid_from          TIMESTAMPTZ,
    valid_to            TIMESTAMPTZ,        -- NULL = currently active
    evidence_ids        UUID[],
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_type, source_id, target_type, target_id, relationship_type)
);

CREATE INDEX IF NOT EXISTS rel_source_idx ON relationships (source_type, source_id);
CREATE INDEX IF NOT EXISTS rel_target_idx ON relationships (target_type, target_id);
CREATE INDEX IF NOT EXISTS rel_type_idx ON relationships (relationship_type);
CREATE INDEX IF NOT EXISTS rel_active_idx ON relationships (valid_to) WHERE valid_to IS NULL;

-- ── Evidence ──────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS evidence (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source      TEXT NOT NULL,
    source_url  TEXT,
    source_date TIMESTAMPTZ,
    source_label TEXT NOT NULL,
    headline    TEXT NOT NULL,
    raw_data    JSONB,
    entity_type TEXT,
    entity_id   UUID,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS evidence_entity_idx ON evidence (entity_type, entity_id);
CREATE INDEX IF NOT EXISTS evidence_source_idx ON evidence (source);
CREATE INDEX IF NOT EXISTS evidence_date_idx ON evidence (source_date DESC);

-- ── Change events ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS change_events (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    change_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id   UUID NOT NULL,
    entity_name TEXT NOT NULL,
    description TEXT NOT NULL,
    evidence_ids UUID[],
    raw_payload JSONB,
    processed   BOOLEAN NOT NULL DEFAULT FALSE,
    brief_id    UUID,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS events_entity_idx ON change_events (entity_type, entity_id);
CREATE INDEX IF NOT EXISTS events_unprocessed_idx ON change_events (processed, detected_at) WHERE processed = FALSE;
CREATE INDEX IF NOT EXISTS events_type_idx ON change_events (change_type);

-- ── Opportunity briefs ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS briefs (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title               TEXT NOT NULL,
    entity_name         TEXT NOT NULL,
    entity_id           UUID,
    what_happened       TEXT NOT NULL,
    evidence_summary    TEXT[],
    confidence          TEXT NOT NULL,
    conflict_flags      JSONB DEFAULT '[]',
    commercial_trigger  JSONB NOT NULL,
    suggested_approaches JSONB DEFAULT '[]',
    financial_analysis  TEXT,
    financial_assumptions TEXT[],
    meets_firm_criteria BOOLEAN,
    criteria_assessment TEXT,
    change_event_id     UUID REFERENCES change_events(id),
    generated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed            BOOLEAN NOT NULL DEFAULT FALSE,
    reviewer_notes      TEXT
);

CREATE INDEX IF NOT EXISTS briefs_entity_idx ON briefs (entity_id);
CREATE INDEX IF NOT EXISTS briefs_reviewed_idx ON briefs (reviewed, generated_at DESC);
CREATE INDEX IF NOT EXISTS briefs_criteria_idx ON briefs (meets_firm_criteria);

-- ── Monitoring targets ────────────────────────────────────────────────────────
-- Which companies are being actively monitored by the intelligence loop

CREATE TABLE IF NOT EXISTS monitoring_targets (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_number  TEXT NOT NULL UNIQUE,
    company_name    TEXT NOT NULL,
    last_polled_at  TIMESTAMPTZ,
    last_snapshot   JSONB,
    poll_interval_seconds INT NOT NULL DEFAULT 3600,
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Firm criteria ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS firm_criteria (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name        TEXT NOT NULL,
    description TEXT,
    criteria    JSONB NOT NULL,   -- structured criteria definition
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed with a default criteria profile
INSERT INTO firm_criteria (name, description, criteria) VALUES (
    'Default Profile',
    'Default firm criteria — edit to match your target profile',
    '{
        "preferred_sectors": [],
        "min_revenue": null,
        "min_growth_rate": null,
        "min_operating_history_years": null,
        "geographies": ["GB"],
        "ownership_characteristics": [],
        "transaction_size_min": null,
        "strategic_notes": ""
    }'
) ON CONFLICT DO NOTHING;

-- ── Updated_at triggers ───────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE tbl TEXT;
BEGIN
  FOREACH tbl IN ARRAY ARRAY['clients','people','companies','relationships','firm_criteria']
  LOOP
    EXECUTE format(
      'DROP TRIGGER IF EXISTS trg_updated_at ON %I;
       CREATE TRIGGER trg_updated_at BEFORE UPDATE ON %I
       FOR EACH ROW EXECUTE FUNCTION update_updated_at();',
      tbl, tbl
    );
  END LOOP;
END $$;
