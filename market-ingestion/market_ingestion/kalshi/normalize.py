from __future__ import annotations

from typing import Optional

# ---------------------------------------------------------------------------
# Category mappings: venue-specific → canonical bucket
# ---------------------------------------------------------------------------

KALSHI_CATEGORY_MAP: dict[str, str] = {
    # Crypto (KX-prefixed live codes + legacy codes)
    "KXBTC": "crypto",
    "KXBTCD": "crypto",
    "KXETH": "crypto",
    "KXETHD": "crypto",
    "KXXRP": "crypto",
    "KXXRPD": "crypto",
    "KXSOL": "crypto",
    "KXSOLD": "crypto",
    "KXSOLE": "crypto",
    "KXDOGE": "crypto",
    "KXDOGED": "crypto",
    "KXCRYPTO": "crypto",
    "BTCUSD": "crypto",
    "ETHUSD": "crypto",
    "CRYPTO": "crypto",
    # Politics / Elections
    "KXHOUSERACE": "politics",
    "KXSENATE": "politics",
    "KXGOV": "politics",
    "KXPRES": "politics",
    "KXTXPRIMARY": "politics",
    "KXAOCSENATE": "politics",
    "KXGOVAKPRIMARY": "politics",
    "KXSENATEFLORIDA": "politics",
    "KXELECTION": "politics",
    "PRES": "politics",
    "PRES24": "politics",
    "SENATE": "politics",
    "HOUSE": "politics",
    "GOV": "politics",
    "POLITICS": "politics",
    "ELECTION": "politics",
    "SENATEFLORIDA": "politics",
    # Economics / Finance
    "KXNASDAQ100U": "economics",
    "KXINXU": "economics",
    "KXGDPNOM": "economics",
    "KXECONSTATU3": "economics",
    "KXFED": "economics",
    "KXFEDRATES": "economics",
    "KXCPI": "economics",
    "KXPCE": "economics",
    "KXNONFARM": "economics",
    "KXUNEMP": "economics",
    "KXRATECUTCOUNT": "economics",
    "INFL": "economics",
    "FED": "economics",
    "FEDRATES": "economics",
    "GDP": "economics",
    "ECON": "economics",
    "UNEMP": "economics",
    # Sports
    "KXNBAWINS": "sports",
    "KXNBAPTS": "sports",
    "KXNBAREB": "sports",
    "KXNBAMVP": "sports",
    "KXNBAMIMVP": "sports",
    "KXMLBWINS": "sports",
    "KXMLBAO": "sports",
    "KXNHLTOTAL": "sports",
    "KXNHLWINS": "sports",
    "KXNFLDRAFTPICK": "sports",
    "KXNEXTTEAMNFL": "sports",
    "KXNFLSUPERBOWL": "sports",
    "KXPGATOUR": "sports",
    "KXPGATOP5": "sports",
    "KXPGATOP10": "sports",
    "KXPGATOP20": "sports",
    "KXPGAR1LEAD": "sports",
    "KXPGAR2LEAD": "sports",
    "KXPGAR3LEAD": "sports",
    "KXPGAMAKECUT": "sports",
    "KXNCAAMB": "sports",
    "KXNCAAMBGAME": "sports",
    "KXNCAAMBSPREAD": "sports",
    "KXNCAAMBTOTAL": "sports",
    "KXNCAAMB1HSPREAD": "sports",
    "KXNCAAMB1HTOTAL": "sports",
    "KXMARMADROUND": "sports",
    "KXWCGAME": "sports",
    "KXWCROUND": "sports",
    "KXMVESPORTSMULTIGAMEEXTENDED": "sports",
    "NBA": "sports",
    "NFL": "sports",
    "MLB": "sports",
    "NHL": "sports",
    "SPORTS": "sports",
    # Weather / Climate
    "TEMP": "weather",
    "WEATHER": "weather",
    # Tech
    "TECH": "tech",
    "AI": "tech",
    "KXOAIHARDWARE": "tech",
}

POLYMARKET_CATEGORY_MAP: dict[str, str] = {
    "crypto": "crypto",
    "cryptocurrency": "crypto",
    "bitcoin": "crypto",
    "ethereum": "crypto",
    "politics": "politics",
    "elections": "politics",
    "election": "politics",
    "us politics": "politics",
    "us elections": "politics",
    "economics": "economics",
    "economy": "economics",
    "finance": "economics",
    "federal reserve": "economics",
    "inflation": "economics",
    "sports": "sports",
    "nba": "sports",
    "nfl": "sports",
    "mlb": "sports",
    "soccer": "sports",
    "weather": "weather",
    "climate": "weather",
    "tech": "tech",
    "technology": "tech",
    "ai": "tech",
    "artificial intelligence": "tech",
}

_POLYMARKET_KEYWORD_BUCKETS: list[tuple[str, list[str]]] = [
    ("crypto", ["bitcoin", "btc", "ethereum", "eth", "crypto", "solana", "sol",
                "xrp", "ripple", "doge", "dogecoin", "coinbase", "binance",
                "blockchain", "defi", "nft", "stablecoin"]),
    ("politics", ["president", "election", "senate", "congress", "house of rep",
                  "democrat", "republican", "vote", "ballot", "primary",
                  "governor", "minister", "parliament", "trump", "biden",
                  "harris", "kennedy", "political", "legislation", "bill passes",
                  "impeach", "veto", "tariff", "sanction"]),
    ("economics", ["gdp", "inflation", "fed ", "federal reserve", "interest rate",
                   "unemployment", "cpi", "pce", "jobs report", "nonfarm",
                   "recession", "dow jones", "s&p 500", "nasdaq", "stock market",
                   "rate cut", "rate hike", "treasury", "debt ceiling"]),
    ("sports", ["nba", "nfl", "mlb", "nhl", "soccer", "football", "basketball",
                "baseball", "hockey", "tennis", "golf", "pga", "ufc", "mma",
                "championship", "super bowl", "world series", "stanley cup",
                "finals", "playoffs", "world cup", "olympic", "f1", "formula 1"]),
    ("weather", ["hurricane", "earthquake", "temperature", "rainfall", "storm",
                 "typhoon", "tornado", "drought", "flood", "wildfire", "climate"]),
    ("tech", ["openai", "anthropic", "google", "microsoft", "apple", "meta",
              "nvidia", "chatgpt", "gpt", "ai model", "artificial intelligence",
              "spacex", "elon musk", "starship", "tesla"]),
]


def _infer_polymarket_category(title: str) -> Optional[str]:
    """Infer a canonical category from a Polymarket market title by keyword matching."""
    lower = (title or "").lower()
    for bucket, keywords in _POLYMARKET_KEYWORD_BUCKETS:
        if any(kw in lower for kw in keywords):
            return bucket
    return None


def canonical_category(raw_category: Optional[str], venue: str,
                       title: Optional[str] = None) -> Optional[str]:
    """Map a venue-specific category string to a canonical bucket.

    Returns None if the category is unknown — markets with no canonical bucket
    are still stored in the DB but excluded from matching.
    """
    if venue == "kalshi":
        if not raw_category:
            return None
        key = raw_category.strip()
        return KALSHI_CATEGORY_MAP.get(key.upper()) or KALSHI_CATEGORY_MAP.get(key.lower())
    elif venue == "polymarket":
        if raw_category:
            key = raw_category.strip().lower()
            result = POLYMARKET_CATEGORY_MAP.get(key)
            if result:
                return result
        return _infer_polymarket_category(title)
    return None


def _midpoint(bid: Optional[str], ask: Optional[str]) -> Optional[float]:
    """Average two dollar-string prices into a float in [0, 1]."""
    try:
        b = float(bid) if bid not in (None, "", "0") else None
        a = float(ask) if ask not in (None, "", "0") else None
        if b is not None and a is not None:
            return (b + a) / 2.0
        return b or a
    except (TypeError, ValueError):
        return None


def _normalize_kalshi_market(raw: dict) -> dict:
    """Convert a raw Kalshi API market dict into our normalised schema."""
    ticker = raw.get("ticker", "")
    event_ticker = raw.get("event_ticker", "")
    category_raw = event_ticker.split("-")[0] if event_ticker else ""

    title = raw.get("yes_sub_title") or raw.get("title") or ticker

    rules_parts = [
        raw.get("rules_primary", "") or "",
        raw.get("rules_secondary", "") or "",
    ]
    rules_text = " ".join(p.strip() for p in rules_parts if p.strip())

    yes_price = _midpoint(raw.get("yes_bid_dollars"), raw.get("yes_ask_dollars"))
    if yes_price is None:
        try:
            yes_price = float(raw["last_price_dollars"]) if raw.get("last_price_dollars") else None
        except (TypeError, ValueError):
            yes_price = None

    no_price = _midpoint(raw.get("no_bid_dollars"), raw.get("no_ask_dollars"))
    if no_price is None:
        try:
            lp = raw.get("last_price_dollars")
            no_price = 1.0 - float(lp) if lp is not None else None
        except (TypeError, ValueError):
            no_price = None

    volume = None
    try:
        v = raw.get("volume") or raw.get("volume_24h")
        volume = float(v) if v is not None else None
    except (TypeError, ValueError):
        pass

    return {
        "venue": "kalshi",
        "venue_id": ticker,
        "category": category_raw or None,
        "title": title,
        "rules_text": rules_text or None,
        "close_time": raw.get("close_time"),
        "yes_price": yes_price,
        "no_price": no_price,
        "volume": volume,
        "raw_data": raw,
    }
