"""Scout Agent — discovers candidate similar markets across Kalshi and Polymarket."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import defaultdict
from typing import NamedTuple, Optional

import numpy as np
import spacy
from sentence_transformers import SentenceTransformer
from sqlalchemy.exc import IntegrityError

from market_ingestion.kalshi.client import fetch_kalshi_markets
from market_ingestion.kalshi.normalize import canonical_category
from market_ingestion.polymarket.client import fetch_polymarket_markets

from alphaagent.config import settings
from alphaagent.db.models import CandidatePair, Market
from alphaagent.db.session import get_db
from alphaagent.schemas import CandidatePairIn

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def upsert_markets(market_dicts: list[dict]) -> dict[tuple[str, str], int]:
    """Insert new markets, skip duplicates. Returns {(venue, venue_id): db_id}."""
    id_map: dict[tuple[str, str], int] = {}

    with get_db() as db:
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


_DATE_RE = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}"
    r"|(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
    r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+\d{1,2}(?:st|nd|rd|th)?,?\s*\d{4}"
    r"|\d{1,2}/\d{1,2}/\d{2,4})\b",
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

    k_embeddings = embed_markets(k_markets, model)
    p_embeddings = embed_markets(p_markets, model)

    sim_matrix = k_embeddings @ p_embeddings.T

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

    model = load_embedding_model()
    try:
        nlp = spacy.load("en_core_web_sm")
    except OSError:
        raise RuntimeError(
            "spaCy model 'en_core_web_sm' not found. "
            "Run: python -m spacy download en_core_web_sm"
        )

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

    id_map = upsert_markets(all_markets)
    logger.info("Upserted %d markets into DB", len(id_map))

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
