from __future__ import annotations

import enum
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Venue(str, enum.Enum):
    kalshi = "kalshi"
    polymarket = "polymarket"


class Market(Base):
    __tablename__ = "markets"
    __table_args__ = (UniqueConstraint("venue", "venue_id", name="uq_venue_venue_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    venue_id: Mapped[str] = mapped_column(String, nullable=False)
    venue: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rules_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    close_time: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    yes_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    no_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    raw_data: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    constraint: Mapped[Optional["Constraint"]] = relationship(
        back_populates="market", uselist=False
    )


class Constraint(Base):
    __tablename__ = "constraints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("markets.id"), nullable=False, unique=True
    )

    event_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    entity: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    threshold_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    threshold_unit: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    comparison_operator: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    start_time: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    end_time: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    timezone: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    resolution_source: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    fallback_sources: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)

    revision_policy: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    occurrence_definition: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    announcement_definition: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    cancellation_conditions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    ladder_group_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    complement_group_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    parse_failed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    market: Mapped["Market"] = relationship(back_populates="constraint")


class CandidatePair(Base):
    __tablename__ = "candidate_pairs"
    __table_args__ = (
        UniqueConstraint("market_a_id", "market_b_id", name="uq_pair"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_a_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("markets.id"), nullable=False
    )
    market_b_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("markets.id"), nullable=False
    )
    similarity_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    matching_basis: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)

    inconsistencies: Mapped[list["Inconsistency"]] = relationship(
        back_populates="pair"
    )
    alpha_flag: Mapped[Optional["AlphaFlag"]] = relationship(
        back_populates="pair", uselist=False
    )


class Inconsistency(Base):
    __tablename__ = "inconsistencies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pair_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("candidate_pairs.id"), nullable=False
    )
    type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    severity: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fields_involved: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    counterexample: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)

    pair: Mapped["CandidatePair"] = relationship(back_populates="inconsistencies")


class AlphaFlag(Base):
    __tablename__ = "alpha_flags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pair_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("candidate_pairs.id"), nullable=False, unique=True
    )
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    opportunity_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    brief_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    pair: Mapped["CandidatePair"] = relationship(back_populates="alpha_flag")
