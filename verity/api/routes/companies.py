from fastapi import APIRouter, HTTPException, Query
from verity.models import Company
from verity.graph import repository as repo
from verity.sources.companies_house import CompaniesHouseClient

router = APIRouter()


@router.get("/search")
async def search(q: str = Query(..., min_length=2)):
    """Search companies in the local graph."""
    return await repo.search_companies(q)


@router.get("/ch/search")
async def ch_search(q: str = Query(..., min_length=2)):
    """Search Companies House directly (live API call)."""
    async with CompaniesHouseClient() as ch:
        return await ch.search_companies(q)


@router.get("/ch/{company_number}")
async def ch_profile(company_number: str):
    """Fetch full Companies House profile including officers and PSCs."""
    async with CompaniesHouseClient() as ch:
        profile = await ch.get_company(company_number)
        officers = await ch.get_active_officers(company_number)
        pscs = await ch.get_pscs(company_number)
        filings = await ch.get_filing_history(company_number, items_per_page=10)
    return {
        "profile": profile,
        "active_officers": officers,
        "pscs": pscs,
        "recent_filings": filings,
    }


@router.post("/", status_code=201)
async def create_company(company: Company):
    return await repo.upsert_company(company)


@router.get("/{company_id}/network")
async def company_network(company_id: str, depth: int = 2):
    """Return the relationship graph around a company."""
    from uuid import UUID
    return await repo.get_network("company", UUID(company_id), depth=depth)
