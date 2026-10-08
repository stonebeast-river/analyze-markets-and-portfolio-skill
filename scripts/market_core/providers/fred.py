from __future__ import annotations

from typing import Iterable

from ..http import DataSourceError, HttpClient
from ..models import Observation


class FredProvider:
    name = "fred_official_api"

    def __init__(self, api_key: str, client: HttpClient | None = None):
        if not api_key:
            raise ValueError("FRED_API_KEY is required")
        self.api_key = api_key
        self.client = client or HttpClient(min_interval_by_host={"api.stlouisfed.org": 0.15})

    def fetch_series(
        self,
        series_ids: Iterable[str],
        *,
        observation_start: str | None = None,
        observation_end: str | None = None,
        vintage_date: str | None = None,
    ) -> list[Observation]:
        rows: list[Observation] = []
        for series_id in series_ids:
            row_start = len(rows)
            metadata_payload, _ = self.client.get_json(
                "https://api.stlouisfed.org/fred/series",
                params={
                    "series_id": series_id,
                    "api_key": self.api_key,
                    "file_type": "json",
                },
            )
            metadata_rows = metadata_payload.get("seriess") or []
            metadata_receipts = self.client.source_receipts()
            if not metadata_rows:
                raise DataSourceError(f"FRED returned no metadata for {series_id}")
            metadata = metadata_rows[0]
            params = {
                "series_id": series_id,
                "api_key": self.api_key,
                "file_type": "json",
            }
            if observation_start:
                params["observation_start"] = observation_start
            if observation_end:
                params["observation_end"] = observation_end
            if vintage_date:
                params["vintage_dates"] = vintage_date
            data, _ = self.client.get_json(
                "https://api.stlouisfed.org/fred/series/observations", params=params
            )
            if "error_code" in data:
                raise DataSourceError(f"FRED error for {series_id}: {str(data.get('error_message')).replace(self.api_key, 'REDACTED')}")
            observations = data.get("observations") or []
            if not observations:
                raise DataSourceError(f"FRED returned no observations for {series_id}")
            for item in observations:
                raw_value = item.get("value")
                try:
                    value = float(raw_value)
                except (TypeError, ValueError):
                    value = None
                rows.append(
                    Observation(
                        provider=self.name,
                        dataset="macro_series",
                        identity=series_id,
                        as_of=item.get("date", ""),
                        value=value,
                        unit=metadata.get("units", ""),
                        publication="",
                        revision=(
                            f"vintage:{vintage_date}" if vintage_date else "latest_available_with_realtime_fields"
                        ),
                        latency="series_specific",
                        quality="official_or_source_aggregated",
                        source_url=f"https://fred.stlouisfed.org/series/{series_id}",
                        raw={"observation": item, "series_metadata": metadata},
                    )
                )
            self.client.bind_rows(rows[row_start:], metadata_receipts + self.client.source_receipts())
        return rows
