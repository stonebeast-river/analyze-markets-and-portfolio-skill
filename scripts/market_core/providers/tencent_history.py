from ..conventions import price_basis_name
from ..http import DataSourceError, HttpClient
from ..models import Bar
from ..symbols import normalize_cn_symbol, is_cn_index


class TencentHistoryProvider:
    """Daily price/volume fallback; never fills its missing amount from another source."""
    name = "tencent_web_history"

    def __init__(self, client=None):
        self.client = client or HttpClient(timeout=8, retries=1)

    def fetch_bars(self, symbol, *, start_date, end_date, frequency="d", adjustment="qfq", count=640):
        if frequency not in {"d", "1d", "1day"} or adjustment not in {"qfq", "hfq", "none"}:
            raise ValueError("Tencent fallback supports daily qfq/hfq/none only")
        normalized = normalize_cn_symbol(symbol)
        index = is_cn_index(normalized)
        effective = "none" if index else adjustment
        flag = "" if effective == "none" else effective
        payload, source = self.client.get_json("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
            params={"param":f"{normalized},day,{start_date},{end_date},{min(count,640)},{flag}"})
        body = (payload.get("data") or {}).get(normalized) or {}
        key = "day" if effective == "none" else effective + "day"
        records = body.get(key) or []
        if not records:
            raise DataSourceError(f"No matching {key} history for {normalized}; adjustment fallback is prohibited")
        rows = []
        for item in records:
            if len(item) < 6:
                raise DataSourceError("Malformed Tencent daily history row")
            if start_date <= item[0] <= end_date:
                rows.append(Bar(self.name,normalized,"1d",item[0],float(item[1]),float(item[3]),float(item[4]),float(item[2]),
                    volume=float(item[5]),amount=None,volume_unit="provider_native_lot",amount_unit="",currency="CNY",
                    price_basis=price_basis_name(effective),source_url=source,quality="provider_reported",
                    raw={"row":item,"series_key":key,"amount_available":False,"publication_time_known":False}))
        if not rows:
            raise DataSourceError("No Tencent bars within the requested date window")
        return self.client.bind_rows(rows)
