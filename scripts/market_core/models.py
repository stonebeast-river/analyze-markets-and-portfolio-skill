from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Quote:
    provider: str
    symbol: str
    as_of: str
    name: str = ""
    asset_class: str = "unknown"
    currency: str = ""
    session: str = "unknown"
    last: float | None = None
    previous_close: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float | None = None
    amount: float | None = None
    volume_unit: str = ""
    amount_unit: str = ""
    book_volume_unit: str = ""
    turnover_pct: float | None = None
    volume_ratio_vendor: float | None = None
    pe_ttm: float | None = None
    pb: float | None = None
    market_cap: float | None = None
    inner_volume: float | None = None
    outer_volume: float | None = None
    bid_book: list[dict[str, float]] = field(default_factory=list)
    ask_book: list[dict[str, float]] = field(default_factory=list)
    source_url: str = ""
    quality: str = "provider_reported"
    latency: str = "unknown"
    raw: dict[str, Any] = field(default_factory=dict)
    source_receipts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Bar:
    provider: str
    symbol: str
    interval: str
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    amount: float | None = None
    volume_unit: str = ""
    amount_unit: str = ""
    currency: str = ""
    session: str = "regular"
    price_basis: str = "unknown"
    source_url: str = ""
    quality: str = "provider_reported"
    raw: dict[str, Any] = field(default_factory=dict)
    source_receipts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Observation:
    provider: str
    dataset: str
    identity: str
    as_of: str
    value: Any
    unit: str = ""
    currency: str = ""
    publication: str = ""
    revision: str = "unknown"
    price_basis: str = "not_applicable"
    latency: str = "unknown"
    quality: str = "provider_reported"
    source_url: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
    source_receipts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class IndicatorValue:
    symbol: str
    interval: str
    timestamp: str
    name: str
    value: float | None
    parameters: dict[str, Any]
    input_provider: str
    quality: str = "locally_derived"
    price_basis: str = "unknown"
    unit: str = "unknown"
    currency: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
