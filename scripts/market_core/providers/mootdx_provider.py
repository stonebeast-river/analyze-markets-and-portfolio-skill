from datetime import datetime
import os
from types import SimpleNamespace

from ..conventions import SHANGHAI, interval_name
from ..http import DataSourceError
from ..models import Bar, Observation
from ..symbols import normalize_cn_symbol, is_cn_index

FREQUENCIES = {"1m": 8, "5m": 0, "15m": 1, "30m": 2, "60m": 3, "1d": 9, "1w": 5, "1mo": 6}


class MootdxProvider:
    name = "mootdx_tdx_protocol"

    @staticmethod
    def _close(api):
        try:
            api.disconnect()
        except Exception:
            socket=getattr(api,"client",None)
            if socket is not None:
                try: socket.close()
                except OSError: pass

    @staticmethod
    def _client():
        try:
            from tdxpy.hq import TdxHq_API
        except ImportError as exc:
            raise DataSourceError("Optional dependency missing: pip install tdxpy") from exc
        # Avoid mootdx's automatic home-directory config writes and broad best-IP scan.
        configured = os.environ.get("MARKET_TDX_HOST")
        servers = [(configured, int(os.environ.get("MARKET_TDX_PORT", "7709")))] if configured else [("110.41.147.114", 7709), ("8.129.13.54", 7709), ("120.24.149.49", 7709)]
        for host, port in servers:
            api = TdxHq_API(raise_exception=True, auto_retry=False)
            try:
                if api.connect(host, int(port), time_out=4) and api.get_security_count(1):
                    return SimpleNamespace(client=api, close=lambda api=api:MootdxProvider._close(api))
            except Exception:
                MootdxProvider._close(api)
        raise DataSourceError("No reachable TDX server among the bounded configured endpoints")

    @staticmethod
    def _market(symbol):
        if symbol.startswith("bj"):
            raise DataSourceError("Beijing routing has not been verified for this adapter")
        return 1 if symbol.startswith("sh") else 0

    def fetch_bars(self, symbol, *, interval="1m", count=240):
        interval = interval_name(interval)
        if interval not in FREQUENCIES or not 1 <= count <= 800:
            raise ValueError("Supported interval and a count from 1 to 800 are required")
        normalized = normalize_cn_symbol(symbol)
        market = self._market(normalized)
        is_index = is_cn_index(normalized)
        client = self._client()
        try:
            method = client.client.get_index_bars if is_index else client.client.get_security_bars
            records = method(FREQUENCIES[interval], market, normalized[2:], 0, count)
            if not records:
                raise DataSourceError(f"No {interval} bars for {normalized}")
            rows = []
            for record in records:
                timestamp = record.get("datetime") or record.get("date")
                if not timestamp and all(key in record for key in ("year", "month", "day")):
                    timestamp = datetime(record["year"], record["month"], record["day"], record.get("hour", 0), record.get("minute", 0), tzinfo=SHANGHAI).isoformat()
                if not timestamp:
                    raise DataSourceError("TDX bar timestamp is missing")
                rows.append(Bar(self.name, normalized, interval, str(timestamp), float(record["open"]), float(record["high"]), float(record["low"]), float(record["close"]),
                                volume=float(record["vol"]) if record.get("vol") is not None else None,
                                amount=float(record["amount"]) if record.get("amount") is not None else None,
                                volume_unit="provider_native_unverified", amount_unit="CNY", currency="CNY", price_basis="unadjusted",
                                source_url="https://github.com/mootdx/mootdx", quality="provider_protocol_data",
                                raw={"row": record, "market_id": market, "index_api": is_index, "coverage": "bounded_recent_window"}))
            return rows
        finally:
            if hasattr(client, "close"):
                client.close()

    def fetch_transactions(self, symbol, *, date, count=800):
        normalized = normalize_cn_symbol(symbol, stock_only=True)
        market = self._market(normalized)
        if not 1 <= count <= 800:
            raise ValueError("count must be from 1 to 800")
        datetime.fromisoformat(date)
        client = self._client()
        try:
            today = datetime.now(SHANGHAI).date().isoformat()
            if date == today:
                records = client.client.get_transaction_data(market, normalized[2:], 0, count)
            else:
                records = client.client.get_history_transaction_data(market, normalized[2:], 0, count, int(date.replace("-", "")))
            if not records:
                raise DataSourceError(f"No transaction records for {normalized} on {date}")
            rows = []
            for index, record in enumerate(records):
                rows.append(Observation(self.name, "tick_transaction", f"{normalized}#{index}", f"{date}T{record.get('time', '')}+08:00",
                    {"symbol": normalized, "price": record.get("price"), "volume": record.get("vol"), "volume_unit": "provider_native_unverified",
                     "trade_count": record.get("num"), "direction": {0: "provider_buy", 1: "provider_sell", 2: "provider_neutral"}.get(int(record.get("buyorsell", 2)), "unknown")},
                    unit="price_CNY_volume_provider_native_unverified", currency="CNY", quality="provider_classified", latency="historical_or_intraday",
                    source_url="https://github.com/mootdx/mootdx",
                    raw={"symbol": normalized, "sequence": index, "row": record, "market_id": market,
                         "coverage": "bounded_page_not_full_session", "max_records": count, "lot_size_verified": False}))
            return rows
        finally:
            if hasattr(client, "close"):
                client.close()
