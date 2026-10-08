from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..http import DataSourceError, HttpClient
from ..models import Observation
from ..symbols import eastmoney_secid, normalize_cn_symbol


BOARD_FILTERS = {
    "industry": "m:90+t:2",
    "concept": "m:90+t:3",
    "region": "m:90+t:1",
}

BOARD_PERIODS = {
    "today": ("f62", "f62", "f184", "f3", "f204"),
    "5d": ("f164", "f164", "f165", "f109", "f257"),
    "10d": ("f174", "f174", "f175", "f160", None),
}


class EastmoneyProvider:
    name = "eastmoney_provider_derived"

    def __init__(self, client: HttpClient | None = None):
        self.client = client or HttpClient(
            timeout=8.0,
            retries=0,
            min_interval_by_host={
                "push2.eastmoney.com": 1.2,
                "push2delay.eastmoney.com": 1.2,
                "push2his.eastmoney.com": 1.2,
            }
        )
        self.headers = {
            "Referer": "https://quote.eastmoney.com/",
            "Origin": "https://quote.eastmoney.com",
        }

    def fetch_universe(self, *, scope="stocks", max_pages=10, page_size=100):
        filters = {"stocks": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048", "etfs": "b:MK0021,b:MK0022,b:MK0023,b:MK0024"}
        if scope not in filters or not 1 <= max_pages <= 100 or not 1 <= page_size <= 500:
            raise ValueError("Use stocks/etfs with bounded pages and page_size")
        rows, expected, error = {}, None, ""
        all_receipts = []
        as_of = datetime.now(timezone.utc).isoformat()
        source_url = "https://push2.eastmoney.com/api/qt/clist/get"
        for page in range(1, max_pages + 1):
            try:
                payload, source_url = self.client.get_json(source_url, params={"pn": page, "pz": page_size, "po": 1, "np": 1, "fltt": 2, "invt": 2, "fid": "f12", "fs": filters[scope], "fields": "f12,f13,f14"}, headers=self.headers)
                body = payload.get("data") or {}
                items = body.get("diff") or []
                if isinstance(items, dict):
                    items = list(items.values())
                expected = body.get("total", expected)
                if not items:
                    raise DataSourceError("Universe page returned no usable items")
                page_receipts = self.client.source_receipts()
                all_receipts.extend(page_receipts)
                for item in items:
                    code = str(item.get("f12") or "")
                    explicit = ("sh" if item.get("f13") == 1 else "sz") + code
                    if code.startswith(("4", "8", "92")):
                        explicit = "bj" + code
                    identity = normalize_cn_symbol(explicit)
                    rows[identity] = Observation(self.name, "instrument_listing", identity, as_of,
                        {"name":item.get("f14"),"market":identity[:2],"scope":scope}, unit="instrument_metadata",
                        source_url=source_url, quality="provider_universe_unverified", raw=item)
                    self.client.bind_rows([rows[identity]], page_receipts)
                if expected is not None and len(rows) >= int(expected):
                    break
            except Exception as exc:
                error = str(exc)
                break
        if not rows:
            raise DataSourceError("Universe enumeration failed: " + error)
        complete = expected is not None and len(rows) == int(expected) and not error
        coverage = Observation(self.name, "universe_coverage", scope, as_of,
            {"scope_filter":filters[scope],"expected_by_provider":expected,"received":len(rows),"max_pages":max_pages,"page_size":page_size,
             "status":"complete_for_provider_filter" if complete else "partial", "error":error,"full_market_coverage_verified":False},
            unit="coverage_counts",source_url=source_url,quality="provider_scope_coverage")
        self.client.bind_rows([coverage], all_receipts)
        return [*rows.values(), coverage]

    def fetch_board_snapshot(
        self, board_type: str = "industry", period: str = "today", limit: int = 500
    ) -> list[Observation]:
        if board_type not in BOARD_FILTERS:
            raise ValueError(f"board_type must be one of {sorted(BOARD_FILTERS)}")
        if period not in BOARD_PERIODS:
            raise ValueError(f"period must be one of {sorted(BOARD_PERIODS)}")
        sort_field, main_field, pct_field, change_field, leader_field = BOARD_PERIODS[period]
        fields = ["f12", "f14", change_field, main_field, pct_field, "f104", "f105"]
        if leader_field:
            fields.append(leader_field)
        if period == "today":
            fields.extend(["f66", "f72", "f78", "f84"])
        params = {
                "pn": "1", "pz": str(min(max(limit, 1), 1000)), "po": "1", "np": "1",
                "fltt": "2", "invt": "2", "fid": sort_field,
                "fs": BOARD_FILTERS[board_type], "fields": ",".join(dict.fromkeys(fields)),
        }
        errors: list[str] = []
        for host in ("push2.eastmoney.com", "push2delay.eastmoney.com"):
            try:
                data, source_url = self.client.get_json(
                    f"https://{host}/api/qt/clist/get", params=params, headers=self.headers
                )
                if (data.get("data") or {}).get("diff"):
                    break
                errors.append(f"{host}: empty payload")
            except Exception as exc:
                errors.append(f"{host}: {exc}")
        else:
            raise DataSourceError("Eastmoney board sources failed: " + " | ".join(errors))
        body = data.get("data") or {}
        items = body.get("diff") or []
        if isinstance(items, dict):
            items = list(items.values())
        if not items:
            raise DataSourceError("Eastmoney board endpoint returned an empty payload")
        as_of = datetime.now(timezone.utc).isoformat()
        rows: list[Observation] = []
        for item in items:
            value: dict[str, Any] = {
                "code": item.get("f12"),
                "name": item.get("f14"),
                "change_pct": item.get(change_field),
                "main_net": item.get(main_field),
                "main_net_pct": item.get(pct_field),
                "advancers": item.get("f104"),
                "decliners": item.get("f105"),
                "leader": item.get(leader_field) if leader_field else None,
            }
            if period == "today":
                value.update(
                    {
                        "super_large_net": item.get("f66"),
                        "large_net": item.get("f72"),
                        "medium_net": item.get("f78"),
                        "small_net": item.get("f84"),
                    }
                )
            rows.append(
                Observation(
                    provider=self.name,
                    dataset=f"board_{board_type}_{period}",
                    identity=str(item.get("f12") or item.get("f14")),
                    as_of=as_of,
                    value=value,
                    unit="percent_and_CNY",
                    currency="CNY",
                    latency="real_time_or_delayed_unknown",
                    quality="vendor_derived",
                    source_url=source_url,
                    raw=item,
                )
            )
        return self.client.bind_rows(rows)

    def fetch_stock_flow(self, symbol: str, *, interval: str = "1m") -> list[Observation]:
        normalized = normalize_cn_symbol(symbol, stock_only=True)
        if interval == "1m":
            url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
            params = {
                "secid": eastmoney_secid(normalized), "klt": "1",
                "fields1": "f1,f2,f3,f7", "fields2": "f51,f52,f53,f54,f55,f56,f57",
            }
        elif interval == "1d":
            url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
            params = {
                "secid": eastmoney_secid(normalized), "lmt": "120",
                "fields1": "f1,f2,f3,f7",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
            }
        else:
            raise ValueError("interval must be 1m or 1d")
        data, source_url = self.client.get_json(url, params=params, headers=self.headers)
        lines = (data.get("data") or {}).get("klines") or []
        if not lines:
            raise DataSourceError(f"Eastmoney returned no {interval} flow data for {normalized}")
        rows: list[Observation] = []
        for line in lines:
            parts = line.split(",")
            if len(parts) < 6:
                continue
            values = []
            for item in parts[1:6]:
                try:
                    values.append(float(item))
                except ValueError:
                    values.append(None)
            rows.append(
                Observation(
                    provider=self.name,
                    dataset=f"stock_order_size_flow_{interval}",
                    identity=normalized,
                    as_of=parts[0],
                    value={
                        "main_net": values[0], "small_net": values[1],
                        "medium_net": values[2], "large_net": values[3],
                        "super_large_net": values[4],
                    },
                    unit="CNY",
                    currency="CNY",
                    latency="real_time_or_delayed_unknown" if interval == "1m" else "end_of_day",
                    quality="vendor_derived",
                    source_url=source_url,
                    raw={"line": line, "classification": "Eastmoney order-size algorithm"},
                )
            )
        return self.client.bind_rows(rows)
