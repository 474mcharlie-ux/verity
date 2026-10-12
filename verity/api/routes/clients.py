from fastapi import APIRouter, HTTPException
from verity.models import Client
from verity.graph import repository as repo

router = APIRouter()


@router.get("/")
async def list_clients(status: str = "active"):
    return await repo.list_clients(status=status)


@router.get("/{client_id}")
async def get_client(client_id: str):
    from uuid import UUID
    result = await repo.get_client(UUID(client_id))
    if not result:
        raise HTTPException(status_code=404, detail="Client not found")
    return result


@router.post("/", status_code=201)
async def create_client(client: Client):
    return await repo.upsert_client(client)
