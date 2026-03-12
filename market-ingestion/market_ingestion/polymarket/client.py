from __future__ import annotations

import logging

import httpx

from market_ingestion.config import settings
from market_ingestion.polymarket.normalize import _normalize_polymarket_market

logger = logging.getLogger(__name__)


async def fetch_polymarket_markets() -> list[dict]:
    """Fetch all active Polymarket markets with offset-based pagination."""
    markets: list[dict] = []
    offset = 0
    limit = 100

    async with httpx.AsyncClient(base_url=settings.polymarket_base_url, timeout=30.0) as client:
        while True:
            params = {
                "active": "true",
                "closed": "false",
                "limit": limit,
                "offset": offset,
            }
            response = await client.get("/markets", params=params)
            response.raise_for_status()
            batch = response.json()

            if not isinstance(batch, list):
                batch = batch.get("markets", [])

            markets.extend(_normalize_polymarket_market(m) for m in batch)

            if len(batch) < limit:
                break
            offset += limit

    logger.info("Fetched %d Polymarket markets", len(markets))
    return markets
