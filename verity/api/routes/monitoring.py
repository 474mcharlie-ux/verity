from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from verity.graph import repository as repo

router = APIRouter()


class MonitorRequest(BaseModel):
    company_number: str
    company_name: str
    poll_interval_seconds: int = 3600


@router.get("/targets")
async def list_targets():
    return await repo.get_monitoring_targets()


@router.post("/targets", status_code=201)
async def add_target(req: MonitorRequest):
    """Add a company to the monitoring list."""
    p = await repo.pool()
    await p.execute(
        """
        INSERT INTO monitoring_targets (company_number, company_name, poll_interval_seconds)
        VALUES ($1, $2, $3)
        ON CONFLICT (company_number) DO UPDATE SET
            company_name=EXCLUDED.company_name,
            poll_interval_seconds=EXCLUDED.poll_interval_seconds,
            active=TRUE
        """,
        req.company_number, req.company_name, req.poll_interval_seconds,
    )
    return {"status": "monitoring", "company_number": req.company_number}


@router.delete("/targets/{company_number}")
async def remove_target(company_number: str):
    p = await repo.pool()
    await p.execute(
        "UPDATE monitoring_targets SET active=FALSE WHERE company_number=$1",
        company_number,
    )
    return {"status": "removed"}


@router.post("/targets/{company_number}/poll-now")
async def poll_now(company_number: str):
    """Trigger an immediate poll for one company (runs synchronously)."""
    from verity.sources.companies_house import CompaniesHouseClient
    from verity.intelligence.change_detector import diff_snapshots
    import json

    p = await repo.pool()
    row = await p.fetchrow(
        "SELECT * FROM monitoring_targets WHERE company_number=$1", company_number
    )
    if not row:
        raise HTTPException(404, "Not a monitoring target")

    async with CompaniesHouseClient() as ch:
        snapshot = await ch.full_snapshot(company_number)

    previous = json.loads(row["last_snapshot"]) if row.get("last_snapshot") else None
    events = diff_snapshots(company_number, row["company_name"], previous, snapshot)

    company_row = await repo.get_company_by_number(company_number)
    entity_id = company_row["id"] if company_row else None

    for event in events:
        if entity_id:
            from uuid import UUID
            event.entity_id = UUID(str(entity_id))
        await repo.save_change_event(event)

    await repo.update_monitoring_snapshot(company_number, snapshot)
    return {"events_detected": len(events), "company_number": company_number}
