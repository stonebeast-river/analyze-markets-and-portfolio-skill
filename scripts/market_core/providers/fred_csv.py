"""Official FRED graph downloads: keyless public data, distinct from vintage API results."""
import csv
import io
import math
import re
from datetime import datetime, timezone

from ..http import DataSourceError, HttpClient
from ..models import Observation
from ..parsing import html_text


class FredCsvProvider:
    name = "fred_public_csv"
    FX_CONTRACTS={
        'DEXCHUS':{'base_currency':'USD','quote_currency':'CNY','unit_phrase':'Chinese Yuan Renminbi to One U.S. Dollar'},
        'DEXUSEU':{'base_currency':'EUR','quote_currency':'USD','unit_phrase':'U.S. Dollars to One Euro'},
    }

    def __init__(self, client=None):
        self.client = client or HttpClient(timeout=12, retries=1, min_interval_by_host={"fred.stlouisfed.org": 0.6})

    def fetch_series(self, series_ids, *, observation_start=None, observation_end=None):
        collected = datetime.now(timezone.utc).isoformat()
        rows = []
        for identity in series_ids:
            row_start = len(rows)
            if not re.fullmatch(r"[A-Z0-9_]+", identity):
                raise ValueError("Invalid FRED series ID")
            page_url = f"https://fred.stlouisfed.org/series/{identity}"
            page, _ = self.client.get_text(page_url)
            metadata_receipts = self.client.source_receipts()
            readable = html_text(page)
            units = re.search(r"Units:\s*(.*?)\s*Frequency:", readable, re.S)
            frequency = re.search(r"Frequency:\s*([^\n]+)", readable)
            if not units or not frequency:
                raise DataSourceError(f"FRED metadata units/frequency unavailable for {identity}")
            unit_text=" ".join(units.group(1).split())
            fx=self.FX_CONTRACTS.get(identity)
            if fx and fx['unit_phrase'] not in unit_text:
                raise DataSourceError('FRED FX unit direction conflicts with the registered contract')
            params = {"id": identity}
            if observation_start: params["cosd"] = observation_start
            if observation_end: params["coed"] = observation_end
            content, download_url = self.client.get_text("https://fred.stlouisfed.org/graph/fredgraph.csv", params=params)
            reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")))
            if identity not in (reader.fieldnames or []):
                raise DataSourceError(f"Unexpected FRED CSV columns for {identity}")
            usable = 0
            for record in reader:
                date = record.get("observation_date") or record.get("DATE")
                if not date: raise DataSourceError("FRED observation date is missing")
                if observation_start and date < observation_start: continue
                if observation_end and date > observation_end: continue
                try: value = float(record[identity])
                except (ValueError, TypeError): continue
                if not math.isfinite(value): continue
                usable += 1
                rows.append(Observation(self.name, "macro_series", identity, date, value,
                    unit=unit_text, currency=fx['quote_currency'] if fx else "not_applicable",
                    revision="downloaded:" + collected[:10], publication="",
                    quality="official_public_download", latency="series_specific",
                    source_url=page_url,
                    raw={"row":record,"download_url":download_url,"frequency":frequency.group(1).strip(),
                         "retrieved_at":collected,"original_publication_known":False,"vintage_verified":False,
                         "fx_contract":fx,"fx_fixing":"New_York_noon_buying_rate_not_intraday_OHLC" if fx else None}))
            if not usable: raise DataSourceError(f"No usable FRED observations for {identity}")
            self.client.bind_rows(rows[row_start:], metadata_receipts + self.client.source_receipts())
        return rows
