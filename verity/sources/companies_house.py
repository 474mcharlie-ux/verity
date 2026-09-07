"""
Companies House API client.
Free API — register at https://developer.company-information.service.gov.uk/
Auth: Basic auth with API key as username, empty password.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional, AsyncIterator
import httpx

from verity.config import get_settings

logger = logging.getLogger(__name__)

CH_BASE = "https://api.company-information.service.gov.uk"


class CompaniesHouseClient:
    def __init__(self, api_key: Optional[str] = None):
        settings = get_settings()
        self._api_key = api_key or settings.companies_house_api_key
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "CompaniesHouseClient":
        self._client = httpx.AsyncClient(
            base_url=CH_BASE,
            auth=(self._api_key, ""),
            timeout=30.0,
            headers={"Accept": "application/json"},
        )
        return self

    async def __aexit__(self, *args) -> None:
        if self._client:
            await self._client.aclose()

    async def _get(self, path: str, params: dict | None = None) -> dict:
        assert self._client, "Use as async context manager"
        response = await self._client.get(path, params=params or {})
        response.raise_for_status()
        return response.json()

    # ── Company profile ──────────────────────────────────────────────────────

    async def get_company(self, company_number: str) -> dict:
        """Full company profile."""
        return await self._get(f"/company/{company_number}")

    async def search_companies(self, query: str, items_per_page: int = 10) -> list[dict]:
        """Search for companies by name."""
        data = await self._get(
            "/search/companies",
            params={"q": query, "items_per_page": items_per_page},
        )
        return data.get("items", [])

    # ── Officers ─────────────────────────────────────────────────────────────

    async def get_officers(self, company_number: str) -> list[dict]:
        """All current and resigned officers."""
        items: list[dict] = []
        start_index = 0
        while True:
            data = await self._get(
                f"/company/{company_number}/officers",
                params={"start_index": start_index, "items_per_page": 100},
            )
            batch = data.get("items", [])
            items.extend(batch)
            if len(items) >= data.get("total_results", 0):
                break
            start_index += len(batch)
            await asyncio.sleep(0.2)   # Be polite to the API
        return items

    async def get_active_officers(self, company_number: str) -> list[dict]:
        """Current officers only (no resignation date)."""
        all_officers = await self.get_officers(company_number)
        return [o for o in all_officers if not o.get("resigned_on")]

    # ── Persons with Significant Control ─────────────────────────────────────

    async def get_pscs(self, company_number: str) -> list[dict]:
        """Persons (or entities) with significant control."""
        data = await self._get(
            f"/company/{company_number}/persons-with-significant-control"
        )
        return data.get("items", [])

    # ── Filing history ────────────────────────────────────────────────────────

    async def get_filing_history(
        self,
        company_number: str,
        category: Optional[str] = None,
        items_per_page: int = 25,
    ) -> list[dict]:
        """Recent filings. category: accounts | confirmation-statement | officers | etc."""
        params: dict = {"items_per_page": items_per_page}
        if category:
            params["category"] = category
        data = await self._get(
            f"/company/{company_number}/filing-history", params=params
        )
        return data.get("items", [])

    async def get_recent_filings(
        self, company_number: str, since: Optional[datetime] = None
    ) -> list[dict]:
        """Filings since a given date (or last 25 if no date given)."""
        filings = await self.get_filing_history(company_number, items_per_page=50)
        if since:
            filings = [
                f for f in filings
                if f.get("date") and datetime.fromisoformat(f["date"]) >= since
            ]
        return filings

    # ── Charges (mortgages) ───────────────────────────────────────────────────

    async def get_charges(self, company_number: str) -> list[dict]:
        """All registered charges."""
        data = await self._get(f"/company/{company_number}/charges")
        return data.get("items", [])

    # ── Insolvency ────────────────────────────────────────────────────────────

    async def get_insolvency(self, company_number: str) -> Optional[dict]:
        """Insolvency information if any."""
        try:
            return await self._get(f"/company/{company_number}/insolvency")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    # ── Snapshot helper ───────────────────────────────────────────────────────

    async def full_snapshot(self, company_number: str) -> dict:
        """
        Pull everything we monitor for a company in one call.
        Returns a dict suitable for diff-based change detection.
        """
        profile = await self.get_company(company_number)
        officers = await self.get_active_officers(company_number)
        pscs = await self.get_pscs(company_number)
        filings = await self.get_filing_history(company_number, items_per_page=5)
        charges = await self.get_charges(company_number)

        return {
            "company_number": company_number,
            "snapshotted_at": datetime.utcnow().isoformat(),
            "profile": profile,
            "active_officers": officers,
            "pscs": pscs,
            "recent_filings": filings,
            "charges": charges,
        }
