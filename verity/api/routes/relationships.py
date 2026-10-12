from fastapi import APIRouter
from verity.models import Relationship
from verity.graph import repository as repo

router = APIRouter()


@router.post("/", status_code=201)
async def create_relationship(rel: Relationship):
    return await repo.upsert_relationship(rel)


@router.get("/{entity_type}/{entity_id}")
async def entity_relationships(entity_type: str, entity_id: str, active_only: bool = True):
    from uuid import UUID
    return await repo.get_entity_relationships(entity_type, UUID(entity_id), active_only)
