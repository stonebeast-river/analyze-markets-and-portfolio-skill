from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from .conventions import SHANGHAI
from .http import redact_error, HttpClient
from .responses import ResponseVault
from .task_health import profile_health
from .sessions import expected_session
from .fund_products import verified_nav_currency
from .providers.fund_huaan import HuaanDealingProvider

from .indicators import indicator_rows_grouped, quote_indicator_rows, series_indicator_rows
from .microstructure import summarize_transactions
from .providers import (
    BaoStockProvider,
    EastmoneyFundProvider,
    EastmoneyProvider,
    FredProvider,
    MootdxProvider,
    TencentProvider,
    TwelveDataProvider,
)
from .store import MarketStore
from .symbols import normalize_cn_symbol,is_cn_index,is_cn_exchange_fund
from .providers.tencent_history import TencentHistoryProvider
from .providers.tencent_intraday import TencentIntradayProvider
from .providers.fred_csv import FredCsvProvider
from .providers.yahoo import YahooProvider
from .history_collection import collect_cn_history,DEFAULT_HISTORY_REFRESH


DEFAULT_CONFIG: dict[str, Any] = {
    "database": "market-data/market.sqlite3",
    "collection_transport": {
        "archive_enabled": True,
        "cache_ttl_by_host": {"fred.stlouisfed.org":300,"fund.eastmoney.com":300},
        "cache_on_failure": False,
    },
    "profiles": {
        "allocation": {
            "cn_benchmarks": ["sh000300", "sh000905", "sh000016", "sz399006"],
            "cn_sector_indices": [
                "sh000928", "sh000929", "sh000930", "sh000931", "sh000932",
                "sh000933", "sh000934", "sh000935", "sh000936", "sh000937"
            ],
            "global_symbols": [
                "SPY", "QQQ", "IWM", "EEM", "FXI", "GLD", "TLT", "UUP",
                "XLK", "XLF", "XLE", "XLY", "XLP", "XLI", "XLV", "XLU",
                "XLB", "XLRE", "XLC"
            ],
            "fred_series": ["DGS2", "DGS10", "DFII10", "DTWEXBGS", "DEXCHUS"],
            "fund_codes": [],
            "board_types": ["industry"],
            "board_periods": ["today", "5d", "10d"],
            "history_lookback_days": 450,
            "history_fallback_sources": ["tencent"],
            "history_refresh": dict(DEFAULT_HISTORY_REFRESH),
        },
        "tactical": {
            "cn_symbols": [],
            "board_types": ["industry"],
            "board_periods": ["today", "5d", "10d"],
            "flow_symbols": [],
            "tick_symbols": [],
            "tick_lot_size": 100,
            "large_notional_threshold": 200000,
            "super_large_notional_threshold": 1000000,
            "intraday_interval": "5m",
            "intraday_count": 240,
            "history_lookback_days": 450,
            "history_fallback_sources": ["tencent"],
            "history_refresh": dict(DEFAULT_HISTORY_REFRESH),
        },
    },
    "providers": {
        "tencent": {"enabled": True},
        "eastmoney": {"enabled": True},
        "fund_eastmoney": {"enabled": True},
        "huaan_dealing": {"enabled": False},
        "fred": {"enabled": True, "api_key_env": "FRED_API_KEY"},
        "twelve_data": {"enabled": True, "api_key_env": "TWELVE_DATA_API_KEY"},
        "baostock": {"enabled": True},
        "mootdx": {"enabled": True},
    },
}


@dataclass(slots=True)
class RunResult:
    provider: str
    dataset: str
    status: str
    row_count: int
    error: str = ""


def load_config(path: str | Path) -> dict[str, Any]:
    with Path(path).expanduser().open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    if not isinstance(config.get("profiles"), dict) or not isinstance(config.get("providers"), dict):
        raise ValueError("Config must contain profiles and providers objects")
    return config


def write_default_config(path: str | Path, *, overwrite: bool = False) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists() and not overwrite:
        raise FileExistsError(f"Config already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


class MarketPipeline:
    def __init__(self, config: dict[str, Any], *, config_path: str | Path):
        self.config = config
        base = Path(config_path).expanduser().resolve().parent
        db_value = Path(str(config.get("database", "market-data/market.sqlite3")))
        self.database = db_value if db_value.is_absolute() else base / db_value
        self.store = MarketStore(self.database)
        transport=config.get('collection_transport') or DEFAULT_CONFIG['collection_transport']
        if transport.get('cache_on_failure'):raise ValueError('Expired response cache cannot replace a failed live collection')
        archive_path=Path(transport.get('archive_directory') or self.database.parent/'raw-responses')
        if not archive_path.is_absolute():archive_path=base/archive_path
        self.response_vault=ResponseVault(archive_path) if transport.get('archive_enabled',True) else None
        self.cache_ttl_by_host=transport.get('cache_ttl_by_host') or {}

    def _http(self,provider):
        if isinstance(getattr(provider,'client',None),HttpClient):
            provider.client.archive=self.response_vault
            provider.client.cache_ttl_by_host=dict(self.cache_ttl_by_host)
        return provider

    def health(self,profile_name,*,as_of=None):
        return profile_health(MarketStore(self.database,read_only=True),self.config,profile_name,as_of=as_of)

    def _history_results(self,provider,symbol,profile,start_date,end_date):
        adjustment='none' if is_cn_exchange_fund(symbol) or is_cn_index(symbol) else 'qfq'
        def collect(source):
            return self._run(source.name,'cn_daily_bars:'+symbol,lambda:collect_cn_history(
                self,source,symbol,profile,start_date,end_date,adjustment))
        result=collect(provider);results=[result]
        fallbacks=profile.get('history_fallback_sources',['tencent'])
        if result.status=='failed' and not isinstance(provider,TencentHistoryProvider) and 'tencent' in fallbacks and self._enabled('tencent'):
            results.append(collect(self._http(TencentHistoryProvider())))
        return results

    def _enabled(self, name: str) -> bool:
        return bool((self.config.get("providers", {}).get(name) or {}).get("enabled", False))

    def _api_key(self, name: str) -> str:
        settings = self.config.get("providers", {}).get(name) or {}
        env_name = settings.get("api_key_env") or {'fred':'FRED_API_KEY','twelve_data':'TWELVE_DATA_API_KEY'}.get(name,'')
        return os.environ.get(env_name, "") if env_name else ""

    def _run(
        self,
        provider: str,
        dataset: str,
        operation: Callable[[], tuple[int, dict[str, Any]]],
    ) -> RunResult:
        started = datetime.now(timezone.utc).isoformat()
        response_start=len(self.response_vault.events) if self.response_vault else 0
        try:
            count, details = operation()
            if count <= 0:
                raise RuntimeError("provider completed without usable rows")
            status = str(details.pop("_status", "ok"))
            if self.response_vault:
                details['response_receipts']=self.response_vault.events[response_start:]
            self.store.record_run(provider, dataset, started, status, count, details=details)
            return RunResult(provider, dataset, status, count, str(details.get("warning", "")))
        except Exception as exc:
            events=list(self.response_vault.events[response_start:]) if self.response_vault else []
            if self.response_vault:
                for event in events:
                    if event.get('status') in {'http_ok','cache_hit'}:self.response_vault.reject(event,'Collection operation failed validation')
                events=list(self.response_vault.events[response_start:])
            self.store.record_run(provider, dataset, started, "failed", 0, error=str(exc),details={'response_receipts':events})
            return RunResult(provider, dataset, "failed", 0, redact_error(str(exc)))

    def run_profile(self, profile_name: str) -> list[RunResult]:
        profile = self.config.get("profiles", {}).get(profile_name)
        if not isinstance(profile, dict):
            raise ValueError(f"Unknown profile {profile_name!r}")
        if profile_name == "allocation":
            return self._run_allocation(profile)
        if profile_name == "tactical":
            return self._run_tactical(profile)
        raise ValueError("Profiles currently supported: allocation, tactical")

    def _run_allocation(self, profile: dict[str, Any]) -> list[RunResult]:
        results: list[RunResult] = []
        cn_symbols = list(dict.fromkeys(
            (profile.get("cn_benchmarks") or []) + (profile.get("cn_sector_indices") or [])
        ))
        if self._enabled("tencent") and cn_symbols:
            provider = self._http(TencentProvider())
            results.append(
                self._run(
                    provider.name,
                    "cn_benchmark_quotes",
                    lambda: self._store_quotes(
                        provider.fetch_quotes(cn_symbols, strict=False), expected_symbols=cn_symbols
                    ),
                )
            )

        if cn_symbols and (self._enabled("baostock") or (profile.get("history_source") == "tencent" and self._enabled("tencent"))):
            provider = self._http(TencentHistoryProvider() if profile.get("history_source") == "tencent" else BaoStockProvider())
            start_date, end_date = self._history_window(profile)
            for symbol in cn_symbols:
                results.extend(self._history_results(provider,symbol,profile,start_date,end_date))
                if isinstance(provider, TencentHistoryProvider) or is_cn_index(symbol) or is_cn_exchange_fund(symbol):
                    continue
                results.append(
                    self._run(
                        provider.name,
                        f"cn_daily_metrics:{symbol}",
                        lambda symbol=symbol: self._store_observations(
                            provider.fetch_daily_metrics(
                                symbol, start_date=start_date, end_date=end_date
                            )
                        ),
                    )
                )

        results.extend(self._run_boards(profile))

        global_symbols = profile.get("global_symbols") or []
        if self._enabled("twelve_data") and global_symbols:
            key = self._api_key("twelve_data")
            transport=(self.config.get("providers",{}).get("twelve_data") or {}).get("source","auto")
            if key or transport in {"auto","yahoo"}:
                provider = self._http(TwelveDataProvider(key) if key and transport!="yahoo" else YahooProvider())
                for symbol in global_symbols:
                    results.append(
                        self._run(
                            provider.name,
                            f"global_daily_bars:{symbol}",
                            lambda symbol=symbol: self._store_global(provider,symbol),
                        )
                    )
            else:
                for symbol in global_symbols:
                    results.append(
                        self._record_missing_key(
                            "twelve_data", f"global_daily_bars:{symbol}"
                        )
                    )

        fred_series = profile.get("fred_series") or []
        if self._enabled("fred") and fred_series:
            key = self._api_key("fred")
            transport=(self.config.get("providers",{}).get("fred") or {}).get("source","auto")
            if key or transport in {"auto","csv"}:
                provider = self._http(FredProvider(key) if key and transport!="csv" else FredCsvProvider())
                start_date,end_date=self._history_window(profile)
                for series_id in fred_series:
                    results.append(
                        self._run(
                            provider.name,
                            f"macro_series:{series_id}",
                            lambda series_id=series_id: self._store_observations(
                                provider.fetch_series([series_id],observation_start=start_date,observation_end=end_date)
                            ),
                        )
                    )
            else:
                for series_id in fred_series:
                    results.append(
                        self._record_missing_key("fred", f"macro_series:{series_id}")
                    )

        fund_codes = profile.get("fund_codes") or []
        if self._enabled("fund_eastmoney") and fund_codes:
            provider = self._http(EastmoneyFundProvider())
            for code in fund_codes:
                results.append(
                    self._run(
                        provider.name,
                        f"fund_unit_nav:{code}",
                        lambda code=code: self._collect_fund_nav(provider,code),
                    )
                )
        huaan_codes=profile.get('huaan_fund_codes') or []
        if self._enabled('huaan_dealing') and huaan_codes:
            registry=Path(__file__).resolve().parents[2]/'assets/fund-document-sources.json'
            provider=self._http(HuaanDealingProvider(registry))
            results.append(self._run(provider.name,'fund_dealing_snapshot',
                lambda:self._store_observations(provider.fetch_evidence(huaan_codes))))
        return results

    def _run_tactical(self, profile: dict[str, Any]) -> list[RunResult]:
        results: list[RunResult] = []
        symbols = profile.get("cn_symbols") or []
        if self._enabled("tencent") and symbols:
            provider = self._http(TencentProvider())
            results.append(
                self._run(
                    provider.name,
                    "cn_watchlist_quotes",
                    lambda: self._store_quotes(
                        provider.fetch_quotes(symbols, strict=False), expected_symbols=symbols
                    ),
                )
            )
        if symbols and (self._enabled("baostock") or (profile.get("history_source") == "tencent" and self._enabled("tencent"))):
            provider = self._http(TencentHistoryProvider() if profile.get("history_source") == "tencent" else BaoStockProvider())
            start_date, end_date = self._history_window(profile)
            for symbol in symbols:
                results.extend(self._history_results(provider,symbol,profile,start_date,end_date))
                if isinstance(provider, TencentHistoryProvider) or is_cn_index(symbol) or is_cn_exchange_fund(symbol):
                    continue
                results.append(
                    self._run(
                        provider.name,
                        f"cn_daily_metrics:{symbol}",
                        lambda symbol=symbol: self._store_observations(
                            provider.fetch_daily_metrics(
                                symbol, start_date=start_date, end_date=end_date
                            )
                        ),
                    )
                )
        results.extend(self._run_boards(profile))
        if self._enabled("eastmoney"):
            provider = self._http(EastmoneyProvider())
            for symbol in profile.get("flow_symbols") or []:
                results.append(
                    self._run(
                        provider.name,
                        f"stock_order_size_flow_1m:{symbol}",
                        lambda symbol=symbol: self._store_observations(
                            provider.fetch_stock_flow(symbol, interval="1m")
                        ),
                    )
                )
        intraday_tencent=profile.get('intraday_source')=='tencent'
        if symbols and (self._enabled('tencent') if intraday_tencent else self._enabled('mootdx')):
            provider = self._http(TencentIntradayProvider() if profile.get("intraday_source")=="tencent" else MootdxProvider())
            interval = str(profile.get("intraday_interval", "5m"))
            count = int(profile.get("intraday_count", 240))
            for symbol in symbols:
                results.append(
                    self._run(
                        provider.name,
                        f"bars_{interval}:{symbol}",
                        lambda symbol=symbol: self._store_bars(
                            provider.fetch_bars(symbol, interval=interval, count=count)
                        ),
                    )
                )
            tick_symbols = profile.get("tick_symbols") or []
            tick_date = str(
                profile.get("tick_date")
                or expected_session(datetime.now(timezone.utc).isoformat())
                or datetime.now(SHANGHAI).date().isoformat()
            )
            for symbol in tick_symbols:
                if isinstance(provider,TencentIntradayProvider):
                    results.append(self._run(provider.name,f"transaction_aggregates:{symbol}",lambda symbol=symbol:self._store_observations(provider.fetch_transactions(symbol,date=tick_date,max_pages=int(profile.get("aggregate_max_pages",64))))))
                    continue
                results.append(
                    self._run(
                        provider.name,
                        f"tick_transactions:{symbol}",
                        lambda symbol=symbol: self._store_transactions(
                            provider.fetch_transactions(symbol, date=tick_date),
                            lot_size=float(profile.get("tick_lot_size", 100)),
                            large_notional=float(profile.get("large_notional_threshold", 200000)),
                            super_large_notional=float(
                                profile.get("super_large_notional_threshold", 1000000)
                            ),
                        ),
                    )
                )
        return results

    def _run_boards(self, profile: dict[str, Any]) -> list[RunResult]:
        if not self._enabled("eastmoney"):
            return []
        results: list[RunResult] = []
        provider = self._http(EastmoneyProvider())
        for board_type in profile.get("board_types") or []:
            for period in profile.get("board_periods") or ["today"]:
                results.append(
                    self._run(
                        provider.name,
                        f"board_{board_type}_{period}",
                        lambda board_type=board_type, period=period: self._store_observations(
                            provider.fetch_board_snapshot(board_type, period)
                        ),
                    )
                )
        return results

    @staticmethod
    def _history_window(profile: dict[str, Any]) -> tuple[str, str]:
        end = datetime.now(SHANGHAI).date()
        if profile.get("history_start"):
            start = str(profile["history_start"])
        else:
            start = (end - timedelta(days=int(profile.get("history_lookback_days", 450)))).isoformat()
        return start, end.isoformat()

    def _record_missing_key(self, provider: str, dataset: str) -> RunResult:
        started = datetime.now(timezone.utc).isoformat()
        message = f"missing API key environment variable for {provider}"
        self.store.record_run(provider, dataset, started, "not_configured", 0, error=message)
        return RunResult(provider, dataset, "not_configured", 0, message)

    def _store_quotes(self, rows, *, expected_symbols=None):
        rows = list(rows)
        count = self.store.upsert_quotes(rows)
        indicator_count = self.store.upsert_indicators(quote_indicator_rows(rows))
        details = {"kind": "raw_provider_quote", "indicator_rows": indicator_count}
        if expected_symbols:
            expected = {normalize_cn_symbol(symbol) for symbol in expected_symbols}
            returned = {row.symbol for row in rows}
            missing = sorted(expected - returned)
            if missing:
                details.update(
                    {
                        "_status": "partial",
                        "missing_symbols": missing,
                        "warning": "provider returned only part of the configured symbol set",
                    }
                )
        return count, details

    def _store_global(self,provider,symbol):
        if isinstance(provider,YahooProvider):
            bars,observations=provider.fetch_evidence([symbol],lookback_days=450)
            count,details=self._store_bars(bars)
            details["corporate_event_and_adjusted_close_rows"]=self.store.upsert_observations(observations)
            return count,details
        return self._store_bars(provider.fetch_time_series([symbol],interval="1day",outputsize=300))

    def _store_observations(self, rows):
        rows=list(rows)
        count = self.store.upsert_observations(rows)
        details={"kind":"observation"}
        incomplete=[]
        for row in rows:
            if row.dataset=='transaction_aggregate_summary' and row.value.get('status')!='complete_supplier_window':
                incomplete.append({'identity':row.identity,'status':row.value.get('status','unknown'),
                    'expected_pages':row.value.get('expected_pages'),'received_pages':row.value.get('received_pages'),
                    'records':row.value.get('records'),'error':redact_error(row.value.get('error',''))})
        if incomplete:
            details.update(_status='partial',incomplete_source_windows=incomplete,
                           warning='Supplier window is incomplete; retained rows are not full-window acceptance')
        return count,details

    def _store_bars(self, rows):
        rows = list(rows)
        count = self.store.upsert_bars(rows)
        indicator_count = self.store.upsert_indicators(indicator_rows_grouped(rows))
        return count, {"kind": "bars", "indicator_rows": indicator_count}

    def _store_fund_nav(self, rows):
        rows = list(rows)
        count = self.store.upsert_observations(rows)
        indicator_count = self.store.upsert_indicators(series_indicator_rows([row for row in rows if row.dataset == "fund_unit_nav"]))
        return count, {"kind": "published_fund_nav", "indicator_rows": indicator_count}

    def _collect_fund_nav(self,provider,code):
        contract=verified_nav_currency(self.store,code)
        rows=provider.fetch_evidence(code,currency=contract['currency'])
        for row in rows:row.raw['currency_contract']=contract
        return self._store_fund_nav(rows)

    def _store_transactions(
        self, rows, *, lot_size: float, large_notional: float, super_large_notional: float
    ):
        rows = list(rows)
        summary = summarize_transactions(
            rows,
            lot_size=lot_size,
            large_notional=large_notional,
            super_large_notional=super_large_notional,
        )
        count = self.store.upsert_observations([*rows, summary])
        return count, {
            "kind": "raw_provider_transactions_plus_local_summary",
            "raw_tick_rows": len(rows),
            "summary_rows": 1,
        }
