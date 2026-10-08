from __future__ import annotations

from datetime import datetime
from typing import Iterable
from ..conventions import SHANGHAI

from ..http import DataSourceError, HttpClient
from ..models import Quote
from ..symbols import normalize_cn_symbol


def _number(value: str) -> float | None:
    if value in ("", "-", "--"):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _field(values: list[str], index: int) -> str:
    return values[index] if index < len(values) else ""


def _book(values: list[str], start: int) -> list[dict[str, float]]:
    levels: list[dict[str, float]] = []
    for level in range(5):
        price = _number(_field(values, start + 2 * level))
        volume = _number(_field(values, start + 2 * level + 1))
        if price is not None or volume is not None:
            levels.append({"level": level + 1, "price": price or 0.0, "volume": volume or 0.0})
    return levels


def _asset_class(symbol: str) -> str:
    digits = symbol[2:]
    if symbol.startswith("sh") and digits.startswith(("000","93")):
        return "index"
    if digits.startswith("399"):
        return "index"
    if digits.startswith(("15", "16", "50", "51", "52", "56", "58")):
        return "fund"
    return "equity"


def parse_tencent_payload(payload: str, requested: Iterable[str]) -> list[Quote]:
    requested_map = {normalize_cn_symbol(item): str(item) for item in requested}
    results: list[Quote] = []
    for line in payload.strip().split(";"):
        if "=" not in line or '"' not in line:
            continue
        wire_symbol = line.split("=", 1)[0].rsplit("_", 1)[-1].lower()
        if wire_symbol not in requested_map:
            continue
        values = line.split('"', 2)[1].split("~")
        if len(values) < 53:
            continue
        timestamp_raw = _field(values, 30)
        as_of = timestamp_raw
        timestamp = None
        if len(timestamp_raw) == 14 and timestamp_raw.isdigit():
            timestamp = datetime.strptime(timestamp_raw, "%Y%m%d%H%M%S").replace(
                tzinfo=SHANGHAI
            )
            as_of = timestamp.isoformat()
        volume = _number(_field(values, 6))
        inner = _number(_field(values, 8))
        outer = _number(_field(values, 7))
        last = _number(_field(values, 3))
        previous_close = _number(_field(values, 4))
        amount_wan = _number(_field(values, 37))
        stale_reasons: list[str] = []
        if volume == 0 and last and previous_close and last == previous_close:
            stale_reasons.append("zero_volume_and_unchanged_price")
        stale = bool(stale_reasons)
        results.append(
            Quote(
                provider="tencent_web_quote",
                symbol=wire_symbol,
                as_of=as_of,
                name=_field(values, 1),
                asset_class=_asset_class(wire_symbol),
                currency="CNY",
                session="regular_or_last_available",
                last=last,
                previous_close=previous_close,
                open=_number(_field(values, 5)),
                high=_number(_field(values, 33)),
                low=_number(_field(values, 34)),
                volume=volume,
                amount=amount_wan * 10_000 if amount_wan is not None else None,
                volume_unit="provider_native_lot",
                amount_unit="CNY",
                book_volume_unit="provider_native_lot",
                turnover_pct=_number(_field(values, 38)),
                volume_ratio_vendor=_number(_field(values, 49)),
                pe_ttm=_number(_field(values, 39)),
                pb=_number(_field(values, 46)),
                market_cap=(
                    _number(_field(values, 45)) * 100_000_000
                    if _number(_field(values, 45)) is not None
                    else None
                ),
                inner_volume=inner if _asset_class(wire_symbol) != "index" else None,
                outer_volume=outer if _asset_class(wire_symbol) != "index" else None,
                bid_book=_book(values, 9) if _asset_class(wire_symbol) != "index" else [],
                ask_book=_book(values, 19) if _asset_class(wire_symbol) != "index" else [],
                quality="stale" if stale else "provider_reported",
                latency="real_time_or_delayed_unknown",
                raw={
                    "wire_symbol": wire_symbol,
                    "requested_as": requested_map[wire_symbol],
                    "provider_fields": values,
                    "volume_unit": "provider_native; usually lots for A-shares",
                    "inner_outer_method": "provider trade-direction classification",
                    "is_stale": stale,
                    "stale_reasons": stale_reasons,
                },
            )
        )
    return results


class TencentProvider:
    name = "tencent_web_quote"

    def __init__(self, client: HttpClient | None = None):
        self.client = client or HttpClient()

    def fetch_quotes(self, symbols: Iterable[str], *, strict: bool = True) -> list[Quote]:
        normalized = [normalize_cn_symbol(symbol) for symbol in symbols]
        if not normalized:
            return []
        text, source_url = self.client.get_text(
            "https://qt.gtimg.cn/q=" + ",".join(normalized), encoding="gbk"
        )
        rows = parse_tencent_payload(text, normalized)
        for row in rows:
            row.source_url = source_url
        returned = {row.symbol for row in rows}
        missing = sorted(set(normalized) - returned)
        if missing and strict:
            raise DataSourceError(f"Tencent returned no usable quote for: {', '.join(missing)}")
        return self.client.bind_rows(rows)
