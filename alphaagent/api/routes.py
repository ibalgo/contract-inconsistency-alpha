"""API routes — read-only interface to the alpha_flags database."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from alphaagent.db.models import AlphaFlag, CandidatePair, Market
from alphaagent.db.session import get_db

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/alpha_flags")
def get_alpha_flags() -> list[dict[str, Any]]:
    """Return all alpha flags with market info and scores."""
    results = []
    with get_db() as db:
        flags = db.query(AlphaFlag).all()
        for flag in flags:
            pair = db.query(CandidatePair).filter(CandidatePair.id == flag.pair_id).first()
            if pair is None:
                continue
            market_a = db.query(Market).filter(Market.id == pair.market_a_id).first()
            market_b = db.query(Market).filter(Market.id == pair.market_b_id).first()
            results.append(
                {
                    "market_a": market_a.title if market_a else None,
                    "market_b": market_b.title if market_b else None,
                    "alpha_score": flag.score,
                    "severity": None,  # populated in Phase 4+
                    "inconsistency_type": None,
                    "recommendation": flag.opportunity_type,
                }
            )
    return results


@router.get("/is_safe_pair")
def is_safe_pair(
    market_a: str = Query(..., description="Market A venue_id"),
    market_b: str = Query(..., description="Market B venue_id"),
) -> dict[str, Any]:
    """Check whether a market pair has known inconsistencies."""
    reasons: list[str] = []
    with get_db() as db:
        ma = db.query(Market).filter(Market.venue_id == market_a).first()
        mb = db.query(Market).filter(Market.venue_id == market_b).first()
        if ma is None or mb is None:
            return {"safe": False, "reasons": ["One or both markets not found in DB"]}

        pair = (
            db.query(CandidatePair)
            .filter(
                (
                    (CandidatePair.market_a_id == ma.id)
                    & (CandidatePair.market_b_id == mb.id)
                )
                | (
                    (CandidatePair.market_a_id == mb.id)
                    & (CandidatePair.market_b_id == ma.id)
                )
            )
            .first()
        )
        if pair is None:
            return {"safe": True, "reasons": []}

        # Check for inconsistencies (populated in Phase 4+)
        if pair.inconsistencies:
            for inc in pair.inconsistencies:
                reasons.append(f"{inc.severity}: {inc.description}")

    return {"safe": len(reasons) == 0, "reasons": reasons}
