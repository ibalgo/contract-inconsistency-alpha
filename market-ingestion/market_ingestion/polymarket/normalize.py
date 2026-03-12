from __future__ import annotations

import json
from typing import Optional


def _normalize_polymarket_market(raw: dict) -> dict:
    """Convert a raw Polymarket API market dict into our normalised schema."""
    title = raw.get("question") or raw.get("title") or ""
    rules_text = raw.get("description") or None
    category_raw = raw.get("category") or None
    venue_id = raw.get("conditionId") or raw.get("id") or ""

    yes_price: Optional[float] = None
    no_price: Optional[float] = None
    outcome_prices_raw = raw.get("outcomePrices")
    if outcome_prices_raw:
        try:
            prices = json.loads(outcome_prices_raw)
            yes_price = float(prices[0]) if len(prices) > 0 else None
            no_price = float(prices[1]) if len(prices) > 1 else None
        except (json.JSONDecodeError, IndexError, TypeError, ValueError):
            pass

    if yes_price is None:
        try:
            best_ask = raw.get("bestAsk")
            yes_price = float(best_ask) if best_ask is not None else None
        except (TypeError, ValueError):
            pass
    if no_price is None:
        try:
            best_bid = raw.get("bestBid")
            no_price = float(best_bid) if best_bid is not None else None
        except (TypeError, ValueError):
            pass

    volume = None
    try:
        v = raw.get("volume") or raw.get("volumeNum")
        volume = float(v) if v is not None else None
    except (TypeError, ValueError):
        pass

    return {
        "venue": "polymarket",
        "venue_id": venue_id,
        "category": category_raw,
        "title": title,
        "rules_text": rules_text,
        "close_time": raw.get("endDate") or raw.get("end_date_iso"),
        "yes_price": yes_price,
        "no_price": no_price,
        "volume": volume,
        "raw_data": raw,
    }
