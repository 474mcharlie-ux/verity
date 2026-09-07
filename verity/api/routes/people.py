from fastapi import APIRouter
from verity.models import Person
from verity.graph import repository as repo

router = APIRouter()


@router.post("/", status_code=201)
async def create_person(person: Person):
    return await repo.upsert_person(person)
