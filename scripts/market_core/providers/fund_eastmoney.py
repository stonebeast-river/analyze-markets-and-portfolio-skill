from __future__ import annotations

import json
import re
import math

from ..http import DataSourceError, HttpClient
from ..models import Observation
from ..conventions import SHANGHAI


_NET_WORTH = re.compile(r"var\s+Data_netWorthTrend\s*=\s*(\[.*?\]);", re.DOTALL)
_ACCUMULATED = re.compile(r"var\s+Data_ACWorthTrend\s*=\s*(\[.*?\]);", re.DOTALL)
_FUND_NAME = re.compile(r'var\s+fS_name\s*=\s*"(.*?)";')
_FUND_CODE = re.compile(r'var\s+fS_code\s*=\s*"(\d{6})"\s*;')


class EastmoneyFundProvider:
    name = "eastmoney_fund_page_fallback"

    def __init__(self, client: HttpClient | None = None):
        self.client = client or HttpClient(min_interval_by_host={"fund.eastmoney.com": 1.2})

    def fetch_nav_history(self, fund_code: str, *, currency: str = "unknown") -> list[Observation]:
        return [row for row in self.fetch_evidence(fund_code, currency=currency) if row.dataset == "fund_unit_nav"]

    def fetch_evidence(self, fund_code: str, *, currency: str = "unknown") -> list[Observation]:
        if not re.fullmatch(r"\d{6}", fund_code):
            raise ValueError("fund_code must be six digits")
        text, source_url = self.client.get_text(
            f"https://fund.eastmoney.com/pingzhongdata/{fund_code}.js",
            headers={"Referer": f"https://fund.eastmoney.com/{fund_code}.html"},
        )
        identity=_FUND_CODE.search(text)
        if not identity or identity.group(1)!=fund_code:
            raise DataSourceError('Fund response does not establish the requested exact share code')
        match = _NET_WORTH.search(text)
        if not match:
            raise DataSourceError(f"No net-worth series found for fund {fund_code}")
        try:
            values = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            raise DataSourceError(f"Malformed fund net-worth series for {fund_code}") from exc
        name_match = _FUND_NAME.search(text)
        fund_name = name_match.group(1) if name_match else ""
        rows: list[Observation] = []
        for item in values:
            timestamp_ms = item.get("x")
            nav = item.get("y")
            if timestamp_ms is None or nav is None:
                continue
            if type(timestamp_ms) not in (int,float) or type(nav) not in (int,float) or not math.isfinite(timestamp_ms) or not math.isfinite(nav) or nav<=0:
                raise DataSourceError('Fund NAV contains an invalid timestamp or price')
            from datetime import datetime

            as_of = datetime.fromtimestamp(timestamp_ms / 1000, tz=SHANGHAI).date().isoformat()
            rows.append(
                Observation(
                    provider=self.name, dataset="fund_unit_nav",
                    identity=fund_code, as_of=as_of, value=float(nav),
                    unit=f"{currency}_per_share", currency=currency, price_basis="unit_nav_price_return",
                    latency="end_of_day_with_publication_lag",
                    quality="aggregator_fallback", source_url=source_url,
                    raw={"fund_name": fund_name, "row": item, "source_timezone": "Asia/Shanghai",
                         "publication_time_known": False, "currency_verified": currency != "unknown"},
                )
            )
        if not rows:
            raise DataSourceError(f"Empty fund NAV history for {fund_code}")
        nav_rows = list(rows)
        cumulative = _ACCUMULATED.search(text)
        if cumulative:
            from datetime import datetime
            for timestamp, value in json.loads(cumulative.group(1)):
                rows.append(Observation(self.name, "fund_accumulated_nav", fund_code,
                    datetime.fromtimestamp(timestamp / 1000, tz=SHANGHAI).date().isoformat(), float(value),
                    unit=f"{currency}_per_share", currency=currency, price_basis="cumulative_nav_not_reinvested_total_return",
                    source_url=source_url, quality="aggregator_fallback", latency="publication_lag_unknown"))
        for nav_row in nav_rows:
            notice = nav_row.raw["row"].get("unitMoney")
            if notice:
                rows.append(Observation(self.name, "fund_distribution_notice", fund_code, nav_row.as_of,
                    {"provider_text": str(notice), "amount_and_event_type_verified": False},
                    unit="provider_text", currency=currency, source_url=source_url,
                    quality="aggregator_fallback", latency="publication_lag_unknown"))
        rows.append(Observation(self.name, "fund_profile_basics", fund_code, nav_rows[-1].as_of,
            {"fund_name": fund_name, "fund_code": fund_code, "currency": currency,
             "share_class": "unknown", "underlying_identity": "unknown", "fee_terms": "unknown", "dealing_rules": "unknown"},
            unit="product_metadata", currency=currency, source_url=source_url, quality="aggregator_fallback"))
        return self.client.bind_rows(rows)
