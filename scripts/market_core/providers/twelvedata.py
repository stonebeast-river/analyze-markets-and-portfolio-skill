from __future__ import annotations

from typing import Iterable
from datetime import datetime, timezone

from ..http import DataSourceError, HttpClient
from ..models import Bar


class TwelveDataProvider:
    name = "twelve_data_registered_api"

    def __init__(self, api_key: str, client: HttpClient | None = None):
        if not api_key:
            raise ValueError("TWELVE_DATA_API_KEY is required")
        self.api_key = api_key
        self.client = client or HttpClient(min_interval_by_host={"api.twelvedata.com": 8.0})

    def fetch_time_series(
        self,
        symbols: Iterable[str],
        *,
        interval: str = "1day",
        outputsize: int = 250,
        timezone_name: str = "UTC",
    ) -> list[Bar]:
        rows: list[Bar] = []
        for symbol in symbols:
            row_start = len(rows)
            data, _ = self.client.get_json(
                "https://api.twelvedata.com/time_series",
                params={
                    "symbol": symbol,
                    "interval": interval,
                    "outputsize": min(max(outputsize, 1), 5000),
                    "timezone": timezone_name,
                    "format": "JSON",
                    "apikey": self.api_key,
                },
            )
            if data.get("status") == "error" or not data.get("values"):
                raise DataSourceError(
                    f"Twelve Data error for {symbol}: {str(data.get('message', 'empty response')).replace(self.api_key, 'REDACTED')}"
                )
            meta = data.get("meta") or {}
            currency = meta.get("currency", "")
            for item in reversed(data["values"]):
                try:
                    stamp = item["datetime"]
                    if len(stamp) > 10:
                        if timezone_name != "UTC":
                            raise DataSourceError("Use UTC for intraday timestamps until another timezone is explicitly validated")
                        stamp = datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc).isoformat()
                    rows.append(
                        Bar(
                            provider=self.name,
                            symbol=str(symbol),
                            interval=interval,
                            timestamp=stamp,
                            open=float(item["open"]), high=float(item["high"]),
                            low=float(item["low"]), close=float(item["close"]),
                            volume=float(item["volume"]) if item.get("volume") not in (None, "") else None,
                            volume_unit="provider_native", amount_unit="",
                            currency=currency,
                            price_basis="provider_price_return",
                            source_url="https://twelvedata.com/docs#time-series",
                            quality="licensed_provider_free_tier",
                            raw={"meta": meta, "row": item, "timestamp_kind":"UTC_intraday" if len(stamp)>10 else "market_date_publication_unknown"},
                        )
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise DataSourceError(f"Malformed Twelve Data row for {symbol}: {exc}") from exc
            self.client.bind_rows(rows[row_start:])
        return rows
