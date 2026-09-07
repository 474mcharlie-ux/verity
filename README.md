# Verity

Private intelligence system for professional law firms.
Relationships. Evidence. Opportunities.

---

## What it does

Verity monitors your firm's clients and their commercial environment, continuously
detects changes (new filings, officer changes, ownership shifts, financing events),
and generates structured Opportunity Briefs — each one traceable to evidence.

**Flag → Explain → Support.** Every claim has a source. No unsupported claims, ever.

---

## Architecture

```
[Celery Beat]
    └─ poll_all_companies (hourly)
            │
    [Companies House API]
            │
    [Change Detector] ─── diffs snapshots ──→ [ChangeEvents saved to Postgres]
            
[Celery Worker]
    └─ process_change_events (every 60s)
            │
    [Brief Generator] ─── Anthropic + instructor ──→ [OpportunityBrief (structured)]
            │
    [Postgres] ←── [FastAPI] ←── your UI / dashboard
```

---

## Quickstart

### 1. Prerequisites

- Docker + Docker Compose
- Companies House API key (free): https://developer.company-information.service.gov.uk/
- Anthropic API key: https://console.anthropic.com/

### 2. Configure

```bash
cp .env.example .env
# Edit .env — add your Companies House and Anthropic API keys
```

### 3. Run

```bash
docker compose up --build
```

This starts:
- `db` — Postgres 16 with pgvector + schema applied automatically
- `redis` — message broker
- `api` — FastAPI on http://localhost:8000
- `worker` — Celery worker processing change events
- `beat` — Celery Beat scheduler (hourly polls + per-minute event processing)

### 4. Explore the API

Interactive docs: http://localhost:8000/docs

---

## Key API endpoints

### Clients
```
GET  /clients/                    List active clients
POST /clients/                    Add a client
GET  /clients/{id}                Get one client
```

### Companies House (live)
```
GET  /companies/ch/search?q=...   Search CH directly
GET  /companies/ch/{number}       Full CH profile (officers, PSCs, filings)
```

### Monitoring
```
GET  /monitoring/targets                    List monitored companies
POST /monitoring/targets                    Add a company to monitoring
POST /monitoring/targets/{number}/poll-now  Trigger immediate poll
```

### Briefs
```
GET  /briefs/              List generated Opportunity Briefs
PATCH /briefs/{id}/review  Mark a brief as reviewed
```

---

## Seeding your first client

```bash
# 1. Look up a company on Companies House
curl "http://localhost:8000/companies/ch/search?q=Ashfield+Capital"

# 2. Add it to monitoring (use the company_number from search results)
curl -X POST http://localhost:8000/monitoring/targets \
  -H "Content-Type: application/json" \
  -d '{"company_number": "12345678", "company_name": "Ashfield Capital Ltd"}'

# 3. Trigger an immediate first poll (builds the baseline snapshot)
curl -X POST http://localhost:8000/monitoring/targets/12345678/poll-now

# 4. On the next change detected, a Brief will appear here:
curl http://localhost:8000/briefs/
```

---

## Project structure

```
verity/
├── verity/
│   ├── config.py              Settings (reads .env)
│   ├── models/
│   │   ├── entities.py        Client, Person, Company, Relationship
│   │   ├── evidence.py        Evidence, ChangeEvent
│   │   └── briefs.py          OpportunityBrief (structured LLM output schema)
│   ├── sources/
│   │   └── companies_house.py Companies House API client
│   ├── graph/
│   │   ├── schema.sql         Postgres schema (auto-applied by Docker)
│   │   └── repository.py      All DB queries
│   ├── intelligence/
│   │   ├── change_detector.py Diffs CH snapshots → ChangeEvents
│   │   └── brief_generator.py Anthropic + instructor → OpportunityBrief
│   ├── workers/
│   │   └── tasks.py           Celery tasks (polling loop + brief generation)
│   └── api/
│       ├── main.py            FastAPI app
│       └── routes/            Endpoint handlers
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── .env.example
```

---

## Adding more data sources

The `sources/` directory is where new data sources live. Each source should:

1. Implement an async client that can be used as a context manager
2. Return normalised Python dicts (not source-specific objects)
3. Produce `Evidence` objects with a source label, URL, and date

Next sources to add:
- **OpenCorporates** — global company data, useful for cross-border matters
- **NewsAPI / GDELT** — news monitoring for client mentions
- **PACER** — US federal court records (if expanding to US firms)

---

## Entity resolution

The hardest problem. Currently Verity uses Companies House registration numbers
as stable anchors (most reliable identifier available). Name-based matching
(for people and unregistered entities) uses Postgres full-text search.

Next step: add embedding-based similarity (`pgvector`) so "James Morrison,
director at Acme Capital" matches the James Morrison already in your graph.

---

## Deployment (to a firm)

Each firm gets their own private install:

```bash
# On the firm's server / private cloud:
git clone <this repo>
cp .env.example .env  # configure with firm's keys
docker compose up -d
```

No data leaves the firm's environment. The only external calls are:
- Companies House API (read-only, public data)
- Anthropic API (for brief generation — review data handling with firm first)

For firms that can't send any data externally, swap the Anthropic calls for
a locally-hosted model via Ollama.
