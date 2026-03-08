"""Unit tests for the Scout agent — no network, no real DB (uses tmp_path where needed)."""

from __future__ import annotations

import base64
import json
import os
import tempfile
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_kalshi_raw(**overrides) -> dict:
    base = {
        "ticker": "BTCUSD-25DEC-T50000",
        "event_ticker": "BTCUSD-25DEC",
        "yes_sub_title": "Bitcoin above $50,000 on December 31, 2025",
        "rules_primary": "Resolves YES if BTC/USD closing price on Dec 31 2025 >= 50000.",
        "rules_secondary": "Source: CoinGecko final daily close.",
        "yes_bid_dollars": "0.40",
        "yes_ask_dollars": "0.44",
        "no_bid_dollars": "0.56",
        "no_ask_dollars": "0.60",
        "close_time": "2025-12-31T23:59:59Z",
        "volume": 12000,
    }
    base.update(overrides)
    return base


def _make_polymarket_raw(**overrides) -> dict:
    base = {
        "conditionId": "0xabc123",
        "question": "Will Bitcoin be above $50,000 on December 31, 2025?",
        "description": "Resolves YES if BTC/USD >= $50,000 on December 31, 2025 at midnight UTC.",
        "category": "crypto",
        "outcomePrices": '["0.43", "0.57"]',
        "endDate": "2025-12-31T23:59:59Z",
        "volume": "8500",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Auth header tests
# ---------------------------------------------------------------------------


def test_auth_headers_structure():
    """KALSHI-ACCESS-KEY, TIMESTAMP, SIGNATURE must all be present."""
    from alphaagent.agents.scout import _build_kalshi_auth_headers

    headers = _build_kalshi_auth_headers("GET", "/trade-api/v2/markets")

    assert "KALSHI-ACCESS-KEY" in headers
    assert "KALSHI-ACCESS-TIMESTAMP" in headers
    assert "KALSHI-ACCESS-SIGNATURE" in headers

    # Timestamp must be numeric and in milliseconds (13 digits for 2025)
    ts = headers["KALSHI-ACCESS-TIMESTAMP"]
    assert ts.isdigit()
    assert len(ts) == 13, f"Expected 13-digit ms timestamp, got {ts!r}"

    # Signature must be valid base64
    sig = headers["KALSHI-ACCESS-SIGNATURE"]
    decoded = base64.b64decode(sig)
    assert len(decoded) > 0


def test_auth_headers_unique_per_call():
    """Each call should produce a different timestamp (or at least not crash)."""
    from alphaagent.agents.scout import _build_kalshi_auth_headers

    h1 = _build_kalshi_auth_headers("GET", "/trade-api/v2/markets")
    h2 = _build_kalshi_auth_headers("POST", "/trade-api/v2/orders")
    # Different method/path — different message → different signature
    assert h1["KALSHI-ACCESS-SIGNATURE"] != h2["KALSHI-ACCESS-SIGNATURE"]


# ---------------------------------------------------------------------------
# Kalshi price normalisation
# ---------------------------------------------------------------------------


def test_normalize_kalshi_price_midpoint():
    """bid/ask dollar strings should be averaged to float in [0, 1]."""
    from alphaagent.agents.scout import _normalize_kalshi_market

    raw = _make_kalshi_raw(yes_bid_dollars="0.40", yes_ask_dollars="0.44")
    m = _normalize_kalshi_market(raw)
    assert m["yes_price"] == pytest.approx(0.42, abs=1e-6)
    assert 0.0 <= m["yes_price"] <= 1.0


def test_normalize_kalshi_price_fallback():
    """Falls back to last_price_dollars when bid/ask are absent."""
    from alphaagent.agents.scout import _normalize_kalshi_market

    raw = _make_kalshi_raw(
        yes_bid_dollars=None,
        yes_ask_dollars=None,
        no_bid_dollars=None,
        no_ask_dollars=None,
        last_price_dollars="0.55",
    )
    m = _normalize_kalshi_market(raw)
    assert m["yes_price"] == pytest.approx(0.55, abs=1e-6)


# ---------------------------------------------------------------------------
# Polymarket price normalisation
# ---------------------------------------------------------------------------


def test_normalize_polymarket_outcome_prices():
    """outcomePrices JSON string should be parsed; index 0 → yes, 1 → no."""
    from alphaagent.agents.scout import _normalize_polymarket_market

    raw = _make_polymarket_raw(outcomePrices='["0.62", "0.38"]')
    m = _normalize_polymarket_market(raw)
    assert m["yes_price"] == pytest.approx(0.62, abs=1e-6)
    assert m["no_price"] == pytest.approx(0.38, abs=1e-6)


def test_normalize_polymarket_price_fallback():
    """Uses bestAsk/bestBid when outcomePrices is null."""
    from alphaagent.agents.scout import _normalize_polymarket_market

    raw = _make_polymarket_raw(outcomePrices=None, bestAsk="0.65", bestBid="0.35")
    m = _normalize_polymarket_market(raw)
    assert m["yes_price"] == pytest.approx(0.65, abs=1e-6)
    assert m["no_price"] == pytest.approx(0.35, abs=1e-6)


# ---------------------------------------------------------------------------
# Category mapping
# ---------------------------------------------------------------------------


def test_canonical_category_kalshi():
    from alphaagent.agents.scout import canonical_category

    assert canonical_category("BTCUSD", "kalshi") == "crypto"
    assert canonical_category("PRES", "kalshi") == "politics"
    assert canonical_category("INFL", "kalshi") == "economics"
    assert canonical_category("UNKNOWN_XYZ", "kalshi") is None


def test_canonical_category_polymarket():
    from alphaagent.agents.scout import canonical_category

    # Case-insensitive
    assert canonical_category("crypto", "polymarket") == "crypto"
    assert canonical_category("Crypto", "polymarket") == "crypto"
    assert canonical_category("CRYPTO", "polymarket") == "crypto"
    assert canonical_category("politics", "polymarket") == "politics"
    assert canonical_category("random-garbage", "polymarket") is None


def test_canonical_category_none_input():
    from alphaagent.agents.scout import canonical_category

    assert canonical_category(None, "kalshi") is None
    assert canonical_category("", "polymarket") is None


# ---------------------------------------------------------------------------
# Signal extraction
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def nlp():
    spacy = pytest.importorskip("spacy")
    try:
        return spacy.load("en_core_web_sm")
    except OSError:
        pytest.skip("en_core_web_sm not installed")


def test_extract_signals_dates(nlp):
    from alphaagent.agents.scout import extract_signals

    text = "Resolves on 2025-12-31 or December 31, 2025."
    sigs = extract_signals(text, nlp)
    dates_str = " ".join(sigs.dates)
    assert "2025-12-31" in dates_str or "december 31, 2025" in dates_str


def test_extract_signals_thresholds(nlp):
    from alphaagent.agents.scout import extract_signals

    text = "Resolves YES if price exceeds $100,000 at any point."
    sigs = extract_signals(text, nlp)
    # Should detect the $100,000 threshold
    found = any("100000" in t or "100,000" in t or "$" in t for t in sigs.thresholds)
    assert found, f"Expected threshold with 100000, got: {sigs.thresholds}"


def test_count_shared_signals(nlp):
    from alphaagent.agents.scout import extract_signals, count_shared_signals

    text_a = "Bitcoin above $50,000 on 2025-12-31. Source: CoinGecko."
    text_b = "BTC/USD >= $50,000 as of 2025-12-31. Resolves via CoinGecko."
    sigs_a = extract_signals(text_a, nlp)
    sigs_b = extract_signals(text_b, nlp)
    count, basis = count_shared_signals(sigs_a, sigs_b)
    assert count >= 1
    # Basis tokens should be formatted correctly
    for token in basis:
        assert token.startswith(("shared_date:", "shared_threshold:", "shared_entity:"))


# ---------------------------------------------------------------------------
# Embedding tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def embedding_model():
    try:
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer("all-MiniLM-L6-v2")
    except Exception:
        pytest.skip("sentence-transformers not installed or model unavailable")


def test_embedding_identical_texts(embedding_model):
    from alphaagent.agents.scout import embed_markets

    market = {"title": "Bitcoin above 50k", "rules_text": "Resolves YES if BTC >= 50000"}
    embs = embed_markets([market, market], embedding_model)
    sim = float(embs[0] @ embs[1])
    assert sim == pytest.approx(1.0, abs=1e-4)


def test_embedding_different_texts(embedding_model):
    from alphaagent.agents.scout import embed_markets

    m1 = {"title": "Bitcoin price above $50,000", "rules_text": "Crypto market BTC USD"}
    m2 = {"title": "Will it rain in London next week", "rules_text": "UK weather forecast"}
    embs = embed_markets([m1, m2], embedding_model)
    sim = float(embs[0] @ embs[1])
    assert sim < 0.75, f"Expected low similarity for unrelated texts, got {sim:.3f}"


# ---------------------------------------------------------------------------
# Pagination tests (mocked httpx)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_kalshi_pagination():
    """Two-page response should yield markets from both pages."""
    from alphaagent.agents.scout import fetch_kalshi_markets

    page1 = {
        "markets": [_make_kalshi_raw(ticker="TICK-A", event_ticker="BTCUSD-25DEC")],
        "cursor": "cursor_page2",
    }
    page2 = {
        "markets": [_make_kalshi_raw(ticker="TICK-B", event_ticker="ETHUSD-25DEC")],
        "cursor": "",
    }

    responses = [
        MagicMock(status_code=200, json=MagicMock(return_value=page1)),
        MagicMock(status_code=200, json=MagicMock(return_value=page2)),
    ]
    for r in responses:
        r.raise_for_status = MagicMock()

    call_count = 0

    async def fake_send(self, request, **kwargs):
        nonlocal call_count
        resp = responses[call_count]
        call_count += 1
        return resp

    with patch("httpx.AsyncClient.send", new=fake_send):
        markets = await fetch_kalshi_markets()

    assert len(markets) == 2
    venue_ids = {m["venue_id"] for m in markets}
    assert "TICK-A" in venue_ids
    assert "TICK-B" in venue_ids


@pytest.mark.asyncio
async def test_fetch_polymarket_pagination():
    """Offset increments until a short page stops pagination."""
    from alphaagent.agents.scout import fetch_polymarket_markets

    page1 = [_make_polymarket_raw(conditionId=f"0x{i:04x}") for i in range(100)]
    page2 = [_make_polymarket_raw(conditionId=f"0x{i:04x}") for i in range(100, 115)]

    call_count = 0

    async def fake_get(self, url, params=None, **kwargs):
        nonlocal call_count
        offset = params.get("offset", 0) if params else 0
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        if offset == 0:
            resp.json = MagicMock(return_value=page1)
        else:
            resp.json = MagicMock(return_value=page2)
        call_count += 1
        return resp

    with patch("httpx.AsyncClient.get", new=fake_get):
        markets = await fetch_polymarket_markets()

    assert len(markets) == 115
    assert call_count == 2  # stopped after short page


# ---------------------------------------------------------------------------
# DB upsert idempotency
# ---------------------------------------------------------------------------


def test_upsert_markets_idempotent(tmp_path):
    """Inserting the same markets twice should not create duplicates."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import NullPool
    from alphaagent.db.models import Base
    import alphaagent.db.session as sess_mod

    db_path = tmp_path / "test.db"
    test_engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    Base.metadata.create_all(bind=test_engine)
    TestSession = sessionmaker(bind=test_engine)

    # Patch the lazy accessors so upsert_markets uses the test engine
    with (
        patch("alphaagent.db.session._get_engine", return_value=test_engine),
        patch("alphaagent.db.session._get_session_factory", return_value=TestSession),
    ):
        from alphaagent.agents.scout import upsert_markets

        market_data = [
            {
                "venue": "kalshi",
                "venue_id": "TEST-TICKER-1",
                "category": "crypto",
                "title": "Test Market",
                "rules_text": "Test rules",
                "close_time": None,
                "yes_price": 0.5,
                "no_price": 0.5,
                "volume": 100.0,
                "raw_data": {},
            }
        ]

        id_map_1 = upsert_markets(market_data)
        id_map_2 = upsert_markets(market_data)  # duplicate insert

        # Same ID returned both times
        key = ("kalshi", "TEST-TICKER-1")
        assert id_map_1[key] == id_map_2[key]

        # Only one row in the DB
        from alphaagent.db.models import Market
        with TestSession() as s:
            count = s.query(Market).count()
        assert count == 1
