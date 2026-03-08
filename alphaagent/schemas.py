from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class MarketIn(BaseModel):
    venue_id: str
    venue: str
    category: Optional[str] = None
    title: Optional[str] = None
    rules_text: Optional[str] = None
    close_time: Optional[str] = None
    yes_price: Optional[float] = None
    no_price: Optional[float] = None
    volume: Optional[float] = None
    raw_data: Optional[Any] = None


class MarketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    venue_id: str
    venue: str
    category: Optional[str] = None
    title: Optional[str] = None
    rules_text: Optional[str] = None
    close_time: Optional[str] = None
    yes_price: Optional[float] = None
    no_price: Optional[float] = None
    volume: Optional[float] = None


class ContractConstraints(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_type: Optional[str] = None
    entity: Optional[str] = None
    threshold_value: Optional[float] = None
    threshold_unit: Optional[str] = None
    comparison_operator: Optional[str] = None

    start_time: Optional[str] = None
    end_time: Optional[str] = None
    timezone: Optional[str] = None

    resolution_source: Optional[str] = None
    fallback_sources: Optional[list[str]] = None

    revision_policy: Optional[str] = None

    occurrence_definition: Optional[str] = None
    announcement_definition: Optional[str] = None

    cancellation_conditions: Optional[str] = None

    ladder_group_id: Optional[str] = None
    complement_group_id: Optional[str] = None


class CandidatePairIn(BaseModel):
    market_a_id: int
    market_b_id: int
    similarity_score: Optional[float] = None
    matching_basis: Optional[list[str]] = None


class CandidatePairOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    market_a_id: int
    market_b_id: int
    similarity_score: Optional[float] = None
    matching_basis: Optional[list[str]] = None


class Inconsistency(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type: Optional[str] = None
    severity: Optional[str] = None
    description: Optional[str] = None
    fields_involved: Optional[list[str]] = None
    counterexample: Optional[Any] = None


class AlphaScore(BaseModel):
    score: float  # 0–100
    confidence: float  # 0–1
    opportunity_type: str  # arbitrage | asymmetric | avoid | hedge
