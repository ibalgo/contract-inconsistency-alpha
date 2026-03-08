"""Scout Agent — discovers candidate similar markets across Kalshi and Polymarket."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
from typing import NamedTuple, Optional

import httpx
import numpy as np
import spacy
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from sentence_transformers import SentenceTransformer
from sqlalchemy.exc import IntegrityError

from alphaagent.config import settings
from alphaagent.db.models import CandidatePair, Market
from alphaagent.db.session import get_db
from alphaagent.schemas import CandidatePairIn

logger = logging.getLogger(__name__)

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


# Keyword patterns for inferring Polymarket category from title text
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
        # Try the explicit category field first, then keyword inference
        if raw_category:
            key = raw_category.strip().lower()
            result = POLYMARKET_CATEGORY_MAP.get(key)
            if result:
                return result
        return _infer_polymarket_category(title)
    return None


# ---------------------------------------------------------------------------
# Kalshi authentication
# ---------------------------------------------------------------------------


def _build_kalshi_auth_headers(method: str, path: str) -> dict[str, str]:
    """Generate fresh RSA-PSS signed headers for a Kalshi API request."""
    ts_ms = str(int(time.time() * 1000))
    message = f"{ts_ms}{method.upper()}{path}".encode()

    signature = settings.kalshi_private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    sig_b64 = base64.b64encode(signature).decode()

    return {
        "KALSHI-ACCESS-KEY": settings.kalshi_api_id,
        "KALSHI-ACCESS-TIMESTAMP": ts_ms,
        "KALSHI-ACCESS-SIGNATURE": sig_b64,
    }


# ---------------------------------------------------------------------------
# Price helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Market normalisation
# ---------------------------------------------------------------------------


def _normalize_kalshi_market(raw: dict) -> dict:
    """Convert a raw Kalshi API market dict into our normalised schema."""
    ticker = raw.get("ticker", "")
    event_ticker = raw.get("event_ticker", "")
    # Category: first segment of event_ticker (e.g. "BTCUSD-25DEC" → "BTCUSD")
    category_raw = event_ticker.split("-")[0] if event_ticker else ""

    # Title: prefer yes_sub_title, fall back to ticker
    title = raw.get("yes_sub_title") or raw.get("title") or ticker

    # Rules text: join primary + secondary
    rules_parts = [
        raw.get("rules_primary", "") or "",
        raw.get("rules_secondary", "") or "",
    ]
    rules_text = " ".join(p.strip() for p in rules_parts if p.strip())

    # Prices: use dollar fields; average bid/ask as midpoint
    yes_price = _midpoint(
        raw.get("yes_bid_dollars"), raw.get("yes_ask_dollars")
    )
    if yes_price is None:
        # Fallback to last_price_dollars
        try:
            yes_price = float(raw["last_price_dollars"]) if raw.get("last_price_dollars") else None
        except (TypeError, ValueError):
            yes_price = None

    no_price = _midpoint(
        raw.get("no_bid_dollars"), raw.get("no_ask_dollars")
    )
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


def _normalize_polymarket_market(raw: dict) -> dict:
    """Convert a raw Polymarket API market dict into our normalised schema."""
    title = raw.get("question") or raw.get("title") or ""
    rules_text = raw.get("description") or None
    category_raw = raw.get("category") or None
    venue_id = raw.get("conditionId") or raw.get("id") or ""

    # outcomePrices is a JSON-encoded string like '["0.62", "0.38"]'
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

    # Fallback to bestAsk/bestBid if outcomePrices is missing
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


# ---------------------------------------------------------------------------
# API fetchers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def upsert_markets(market_dicts: list[dict]) -> dict[tuple[str, str], int]:
    """Insert new markets, skip duplicates. Returns {(venue, venue_id): db_id}."""
    id_map: dict[tuple[str, str], int] = {}

    with get_db() as db:
        # Load existing market IDs
        existing = db.query(Market.venue, Market.venue_id, Market.id).all()
        for row in existing:
            id_map[(row.venue, row.venue_id)] = row.id

        for m in market_dicts:
            key = (m["venue"], m["venue_id"])
            if key in id_map:
                continue
            try:
                market = Market(**{k: v for k, v in m.items() if k != "canonical_category"})
                db.add(market)
                db.flush()
                id_map[key] = market.id
            except IntegrityError:
                db.rollback()
                # Another process inserted concurrently; look up the id
                row = (
                    db.query(Market.id)
                    .filter(Market.venue == m["venue"], Market.venue_id == m["venue_id"])
                    .first()
                )
                if row:
                    id_map[key] = row.id

    return id_map


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

_embedding_model: Optional[SentenceTransformer] = None


def load_embedding_model() -> SentenceTransformer:
    global _embedding_model
    if _embedding_model is None:
        t0 = time.time()
        _embedding_model = SentenceTransformer(settings.embedding_model)
        logger.info("Loaded embedding model in %.1fs", time.time() - t0)
    return _embedding_model


def embed_markets(markets: list[dict], model: SentenceTransformer) -> np.ndarray:
    """Return L2-normalised embeddings for each market (shape: n × 384)."""
    texts = [
        f"{m.get('title', '')} {m.get('rules_text', '') or ''}".strip()
        for m in markets
    ]
    embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return np.array(embeddings, dtype=np.float32)


# ---------------------------------------------------------------------------
# Structured signal extraction
# ---------------------------------------------------------------------------


class Signals(NamedTuple):
    dates: frozenset
    thresholds: frozenset
    entities: frozenset


# Regex patterns
_DATE_RE = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}"           # ISO date: 2025-12-31
    r"|(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
    r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+\d{1,2}(?:st|nd|rd|th)?,?\s*\d{4}"  # Written: December 31, 2025
    r"|\d{1,2}/\d{1,2}/\d{2,4})\b",           # US format: 12/31/2025
    re.IGNORECASE,
)

_THRESHOLD_RE = re.compile(
    r"\b(\$\s*[\d,]+(?:\.\d+)?(?:\s*(?:billion|million|trillion|thousand|k|b|m|t))?"
    r"|[\d,]+(?:\.\d+)?\s*(?:billion|million|trillion|thousand|k|b|m|t|%|bps|percent|basis points)"
    r"|[\d,]+(?:\.\d+)?)\b",
    re.IGNORECASE,
)


def extract_signals(text: str, nlp) -> Signals:
    """Extract dates, thresholds, and named entities from text."""
    text = text or ""
    dates = frozenset(m.group(0).lower() for m in _DATE_RE.finditer(text))
    thresholds = frozenset(m.group(0).lower().replace(",", "") for m in _THRESHOLD_RE.finditer(text))

    doc = nlp(text)
    entities = frozenset(
        ent.text.lower()
        for ent in doc.ents
        if ent.label_ in ("ORG", "GPE", "PERSON", "PRODUCT", "EVENT")
    )
    return Signals(dates=dates, thresholds=thresholds, entities=entities)


def count_shared_signals(a: Signals, b: Signals) -> tuple[int, list[str]]:
    """Return (count, basis_tokens) for shared signals between two markets."""
    basis: list[str] = []

    shared_dates = a.dates & b.dates
    for d in shared_dates:
        basis.append(f"shared_date:{d}")

    shared_thresholds = a.thresholds & b.thresholds
    for t in shared_thresholds:
        basis.append(f"shared_threshold:{t}")

    shared_entities = a.entities & b.entities
    for e in shared_entities:
        basis.append(f"shared_entity:{e}")

    return len(basis), basis


# ---------------------------------------------------------------------------
# Pair matching
# ---------------------------------------------------------------------------


def _find_pairs_in_category(
    k_markets: list[dict],
    p_markets: list[dict],
    model: SentenceTransformer,
    nlp,
) -> list[CandidatePairIn]:
    """Find candidate pairs within a single canonical category."""
    if not k_markets or not p_markets:
        return []

    k_embeddings = embed_markets(k_markets, model)  # (nk, d)
    p_embeddings = embed_markets(p_markets, model)  # (np, d)

    # Cosine similarity matrix (since embeddings are L2-normalised, dot = cosine)
    sim_matrix = k_embeddings @ p_embeddings.T  # (nk, np)

    # Pre-extract signals for all markets
    k_signals = [
        extract_signals(f"{m.get('title', '')} {m.get('rules_text', '') or ''}", nlp)
        for m in k_markets
    ]
    p_signals = [
        extract_signals(f"{m.get('title', '')} {m.get('rules_text', '') or ''}", nlp)
        for m in p_markets
    ]

    pairs: dict[tuple[int, int], CandidatePairIn] = {}

    for i, km in enumerate(k_markets):
        for j, pm in enumerate(p_markets):
            sim = float(sim_matrix[i, j])
            shared_count, basis = count_shared_signals(k_signals[i], p_signals[j])

            embedding_match = sim >= settings.cosine_similarity_threshold
            signal_match = shared_count >= settings.min_shared_signals

            if not (embedding_match or signal_match):
                continue

            a_id: int = km["db_id"]
            b_id: int = pm["db_id"]
            key = (a_id, b_id)

            full_basis = list(basis)
            if embedding_match:
                full_basis.insert(0, f"cosine:{sim:.3f}")

            if key not in pairs:
                pairs[key] = CandidatePairIn(
                    market_a_id=a_id,
                    market_b_id=b_id,
                    similarity_score=sim,
                    matching_basis=full_basis,
                )
            else:
                # Merge basis lists; keep higher similarity score
                existing = pairs[key]
                merged = list(dict.fromkeys(existing.matching_basis + full_basis))
                pairs[key] = CandidatePairIn(
                    market_a_id=a_id,
                    market_b_id=b_id,
                    similarity_score=max(existing.similarity_score or 0.0, sim),
                    matching_basis=merged,
                )

    return list(pairs.values())


def _persist_pairs(pairs: list[CandidatePairIn]) -> None:
    """Insert candidate pairs, skip on duplicate (a_id, b_id)."""
    if not pairs:
        return
    with get_db() as db:
        for pair in pairs:
            try:
                row = CandidatePair(
                    market_a_id=pair.market_a_id,
                    market_b_id=pair.market_b_id,
                    similarity_score=pair.similarity_score,
                    matching_basis=pair.matching_basis,
                )
                db.add(row)
                db.flush()
            except IntegrityError:
                db.rollback()

    logger.info("Persisted %d candidate pairs", len(pairs))


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def run_scout() -> None:
    """Full scout pipeline: fetch → upsert → embed → match → persist pairs."""
    logger.info("Scout agent starting")

    # Load heavy models once
    model = load_embedding_model()
    try:
        nlp = spacy.load("en_core_web_sm")
    except OSError:
        raise RuntimeError(
            "spaCy model 'en_core_web_sm' not found. "
            "Run: python -m spacy download en_core_web_sm"
        )

    # Fetch markets concurrently
    k_markets, p_markets = await asyncio.gather(
        fetch_kalshi_markets(),
        fetch_polymarket_markets(),
    )
    all_markets = k_markets + p_markets
    logger.info(
        "Fetched %d Kalshi + %d Polymarket = %d total markets",
        len(k_markets),
        len(p_markets),
        len(all_markets),
    )

    # Upsert to DB
    id_map = upsert_markets(all_markets)
    logger.info("Upserted %d markets into DB", len(id_map))

    # Annotate each market dict with db_id and canonical_category
    active: list[dict] = []
    for m in all_markets:
        key = (m["venue"], m["venue_id"])
        db_id = id_map.get(key)
        if db_id is None:
            continue
        cat = canonical_category(m.get("category"), m["venue"], title=m.get("title"))
        if cat is None:
            continue
        m["db_id"] = db_id
        m["canonical_category"] = cat
        active.append(m)

    logger.info("%d markets have a canonical category", len(active))

    # Group by canonical category
    from collections import defaultdict

    k_by_cat: dict[str, list[dict]] = defaultdict(list)
    p_by_cat: dict[str, list[dict]] = defaultdict(list)

    for m in active:
        if m["venue"] == "kalshi":
            k_by_cat[m["canonical_category"]].append(m)
        else:
            p_by_cat[m["canonical_category"]].append(m)

    shared_cats = set(k_by_cat.keys()) & set(p_by_cat.keys())
    logger.info("Matching across %d shared categories: %s", len(shared_cats), shared_cats)

    all_pairs: list[CandidatePairIn] = []
    for cat in shared_cats:
        pairs = _find_pairs_in_category(k_by_cat[cat], p_by_cat[cat], model, nlp)
        logger.info("  [%s] found %d pairs", cat, len(pairs))
        all_pairs.extend(pairs)

    _persist_pairs(all_pairs)
    logger.info("Scout agent complete. Total pairs: %d", len(all_pairs))
