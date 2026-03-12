from __future__ import annotations

import logging

import httpx

from market_ingestion.config import settings
from market_ingestion.kalshi.auth import _build_kalshi_auth_headers
from market_ingestion.kalshi.normalize import _normalize_kalshi_market

logger = logging.getLogger(__name__)


async def fetch_kalshi_markets() -> list[dict]:
    """Fetch all active Kalshi markets with pagination."""
    markets: list[dict] = []
    cursor = ""
    path_base = "/trade-api/v2/markets"

    async with httpx.AsyncClient(base_url=settings.kalshi_base_url, timeout=30.0) as client:
        while True:
            params: dict = {"limit": 200, "status": "open"}
            if cursor:
                params["cursor"] = cursor

            headers = _build_kalshi_auth_headers("GET", path_base)
            resp = client.build_request("GET", "/markets", params=params, headers=headers)
            response = await client.send(resp)
            response.raise_for_status()
            data = response.json()

            batch = data.get("markets", [])
            markets.extend(_normalize_kalshi_market(m) for m in batch)

            cursor = data.get("cursor", "")
            if not batch or not cursor:
                break

    logger.info("Fetched %d Kalshi markets", len(markets))
    return markets
