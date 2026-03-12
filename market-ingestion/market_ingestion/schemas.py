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
