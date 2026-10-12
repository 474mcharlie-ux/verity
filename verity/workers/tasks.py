"""
Celery workers — the intelligence loop.

Two tasks:
1. poll_company   — fetch a fresh CH snapshot, diff it, emit change events
2. process_events — pick up unprocessed events and generate briefs
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from celery import Celery

from verity.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

app = Celery("verity")
app.config_from_object({
    "broker_url": settings.celery_broker_url,
    "result_backend": settings.celery_result_backend,
    "task_serializer": "json",
    "accept_content": ["json"],
    "timezone": "UTC",
    "enable_utc": True,
    "beat_schedule": {
        "poll-all-companies": {
            "task": "verity.workers.tasks.poll_all_companies",
            "schedule": settings.poll_interval_seconds,
        },
        "process-change-events": {
            "task": "verity.workers.tasks.process_change_events",
            "schedule": 60,   # run every minute
        },
    },
})


def _run(coro):
    """Run a coroutine synchronously inside a Celery task."""
    return asyncio.get_event_loop().run_until_complete(coro)


@app.task(name="verity.workers.tasks.poll_all_companies", bind=True, max_retries=3)
def poll_all_companies(self):
    """
    For every active monitoring target:
    1. Pull a fresh Companies House snapshot
    2. Diff against previous snapshot
    3. Save any ChangeEvents
    4. Store the new snapshot
    """
    from verity.sources.companies_house import CompaniesHouseClient
    from verity.intelligence.change_detector import diff_snapshots
    from verity.graph import repository as repo

    async def _poll():
        targets = await repo.get_monitoring_targets(active_only=True)
        logger.info("Polling %d monitoring targets", len(targets))

        async with CompaniesHouseClient() as ch:
            for target in targets:
                company_number = target["company_number"]
                company_name = target["company_name"]
                try:
                    snapshot = await ch.full_snapshot(company_number)
                    previous = json.loads(target["last_snapshot"]) if target.get("last_snapshot") else None

                    events = diff_snapshots(company_number, company_name, previous, snapshot)

                    # Resolve entity_id from DB
                    company_row = await repo.get_company_by_number(company_number)
                    entity_id = company_row["id"] if company_row else None

                    for event in events:
                        if entity_id:
                            from uuid import UUID
                            event.entity_id = UUID(str(entity_id))
                        await repo.save_change_event(event)

                    await repo.update_monitoring_snapshot(company_number, snapshot)
                    logger.info("Polled %s — %d new events", company_name, len(events))

                except Exception as exc:
                    logger.error("Failed to poll %s: %s", company_name, exc)

    _run(_poll())


@app.task(name="verity.workers.tasks.process_change_events", bind=True, max_retries=3)
def process_change_events(self):
    """
    Pick up unprocessed ChangeEvents and generate OpportunityBriefs.
    Runs every 60 seconds. Processes up to 10 events per run to stay responsive.
    """
    from verity.intelligence.brief_generator import generate_brief
    from verity.graph import repository as repo

    async def _process():
        events = await repo.get_unprocessed_events(limit=10)
        if not events:
            return

        logger.info("Processing %d change event(s)", len(events))
        for event_row in events:
            from verity.models import ChangeEvent, ChangeType
            from uuid import UUID

            try:
                event = ChangeEvent(
                    id=event_row["id"],
                    change_type=ChangeType(event_row["change_type"]),
                    entity_type=event_row["entity_type"],
                    entity_id=event_row["entity_id"],
                    entity_name=event_row["entity_name"],
                    description=event_row["description"],
                    detected_at=event_row["detected_at"],
                )
                entity_id = event_row.get("entity_id")

                brief = await generate_brief(event, entity_id)
                await repo.save_brief(brief)
                await repo.mark_event_processed(event.id, brief.id)

                logger.info("Brief saved: %s", brief.title)

            except Exception as exc:
                logger.error("Failed to process event %s: %s", event_row["id"], exc)
                # Mark as processed anyway to avoid infinite retry loop
                await repo.mark_event_processed(event_row["id"])

    _run(_process())
