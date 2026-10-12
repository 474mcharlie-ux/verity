from fastapi import APIRouter, HTTPException
from typing import Optional
from verity.graph import repository as repo

router = APIRouter()


@router.get("/")
async def list_briefs(reviewed: Optional[bool] = None, limit: int = 50):
    return await repo.list_briefs(reviewed=reviewed, limit=limit)


@router.patch("/{brief_id}/review")
async def mark_reviewed(brief_id: str, notes: Optional[str] = None):
    from uuid import UUID
    p = await repo.pool()
    await p.execute(
        "UPDATE briefs SET reviewed=TRUE, reviewer_notes=$2 WHERE id=$1",
        UUID(brief_id), notes,
    )
    return {"status": "reviewed"}
