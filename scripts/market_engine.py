#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from market_core.indicators import indicator_rows_grouped, quote_indicator_rows, series_indicator_rows
from market_core.microstructure import summarize_transactions
from market_core.pipeline import MarketPipeline, load_config, write_default_config
from market_core.providers import (
    BaoStockProvider,
    EastmoneyFundProvider,
    EastmoneyProvider,
    FredProvider,
    MootdxProvider,
    TencentProvider,
    TwelveDataProvider,
)
from market_core.store import MarketStore
from market_core.models import Observation
from market_core.http import redact_error,HttpClient
from market_core.symbols import normalize_cn_symbol
from market_core.responses import ResponseVault
from market_core.task_health import profile_health,requirements
from market_core.fund_products import assemble_product,verified_nav_currency
from market_core.sector_windows import sector_price_scan
from market_core.ledger_review import review_ledger
from market_core.product_dossier import freeze_product_dossier
from market_core.portfolio_overlay import map_portfolio
from market_core.reporting import export_report
from market_core.research import discover, evidence_pack, import_evidence, ledger_append, screen
from market_core.providers.tencent_history import TencentHistoryProvider
from market_core.providers.tencent_intraday import TencentIntradayProvider
from market_core.providers.fred_csv import FredCsvProvider
from market_core.providers.yahoo import YahooProvider
from market_core.providers.fund_catalog import FundCatalogProvider
from market_core.providers.fund_official import ChinaAMCFundProvider
from market_core.market_scan import scan_market
from market_core.providers.fund_documents import FundDocumentProvider
from market_core.providers.issuer_financials import IssuerFinancialProvider
from market_core.providers.fund_huaan import HuaanDealingProvider
from market_core.providers.fund_holdings import ChinaAMCHoldingsProvider
from market_core.fund_holdings import look_through_feeder,stored_lookthrough
from market_core.fund_reviewed_holdings import reviewed_snapshot
from market_core.fund_graph import stored_fund_graph
from market_core.issuer_document_followup import fetch_catalogued_documents
from market_core.fund_nav import create_fund_nav_chart
from market_core.fund_research import create_fund_research,resolve_fund_identifier
from market_core.providers.fund_chinaamc_status import ChinaAMCBusinessProvider
from market_core.opportunity_research import prepare_opportunity_research
from market_core.candidate_research import research_candidates
from market_core.stock_research import create_stock_research,resolve_stock_identifier,verify_stock_research
from market_core.stock_request import research_stock_request
from market_core.providers.chinabond_curve import ChinaBondCurveProvider
from market_core.global_history_request import public_history_request,completed_public_intraday
from market_core.intraday_quality import audit_intraday_quality,quality_observations,mark_volume_indicator_quality
from market_core.workflow import prepare_research,lock_market_view,load_portfolio_after_view,verify_research


def _archived(provider,store):
    if isinstance(getattr(provider,'client',None),HttpClient):
        provider.client.archive=store.response_vault
    return provider
from market_core.followup import collect_followups


def _json(value) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="strict")
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _started() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local, auditable market-data engine")
    parser.add_argument("--db", default="market-data/market.sqlite3", help="SQLite database path")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init-config", help="Write a safe starter configuration")
    init.add_argument("--config", default="market-config.json")
    init.add_argument("--overwrite", action="store_true")

    run = sub.add_parser("run", help="Run one configured collection profile")
    run.add_argument("--config", default="market-config.json")
    run.add_argument("--profile", choices=("allocation", "tactical"), required=True)

    doctor = sub.add_parser("doctor", help="Check configuration, credentials and optional packages")
    doctor.add_argument("--config", default="market-config.json")
    doctor.add_argument("--profile", choices=("allocation", "tactical"))

    quote = sub.add_parser("fetch-cn-quote", help="Fetch China quotes, order book, volume and amount")
    quote.add_argument("symbols", nargs="+")
    sub.add_parser('fetch-cn-yield-curves',help='Collect dated official ChinaBond government/bank/CP-note curve snapshots')
    stock=sub.add_parser('research-stock',help='Collect one stock, freeze daily curves, evaluate a causal direction model and create a chart/report')
    stock.add_argument('symbol')
    stock.add_argument('--market',choices=('auto','CN','HK','US'),default='auto',help='Native cash market; explicit foreign tickers or market-qualified codes are supported')
    stock.add_argument('--output-dir',required=True)
    stock.add_argument('--horizon',type=int,default=20)
    stock.add_argument('--lookback-years',type=int,default=5)
    stock.add_argument('--no-collect',action='store_true')
    stock.add_argument('--position-state',choices=('unknown','unheld','held'),default='unknown',help='User-confirmed position state; leave unknown when absent')
    stock.add_argument('--risk-budget-cny',type=float,help='User-confirmed risk budget, not inferred personal wealth')
    stock.add_argument('--provider')
    stock.add_argument('--registry',default=str(SCRIPT_DIR.parent/'assets/issuer-financial-sources.json'))
    stock_verify=sub.add_parser('verify-stock-research',help='Replay sealed stock curves/forecasts from frozen inputs without the live database')
    stock_verify.add_argument('--directory',required=True)
    chips=sub.add_parser('research-chips',help='Fetch matched daily price/turnover and freeze a transparent estimated cost distribution')
    chips.add_argument('symbol')
    chips.add_argument('--output-dir',required=True)
    chips.add_argument('--no-collect',action='store_true')
    chips.add_argument('--end',help='Completed mainland trading-day cutoff, YYYY-MM-DD')
    chips_verify=sub.add_parser('verify-chips',help='Replay a frozen chip estimate without the live database')
    chips_verify.add_argument('--directory',required=True)
    issuer_docs=sub.add_parser('fetch-issuer-documents',help='Continue analyst-selected original-content research using exact stored issuer announcement IDs')
    issuer_docs.add_argument('symbol')
    issuer_docs.add_argument('--announcement-ids',nargs='+',required=True)

    board = sub.add_parser("fetch-board", help="Fetch vendor-derived board breadth and flow")
    board.add_argument("--type", choices=("industry", "concept", "region"), default="industry")
    board.add_argument("--period", choices=("today", "5d", "10d"), default="today")
    board.add_argument("--limit", type=int, default=500)

    flow = sub.add_parser("fetch-cn-flow", help="Fetch vendor order-size flow series")
    flow.add_argument("symbol")
    flow.add_argument("--interval", choices=("1m", "1d"), default="1m")
    universe = sub.add_parser("fetch-universe", help="Enumerate a bounded provider universe and retain its coverage")
    universe.add_argument("--scope", choices=("stocks", "etfs"), default="stocks")
    universe.add_argument("--max-pages", type=int, default=10)
    universe.add_argument("--page-size", type=int, default=100)
    universe.add_argument("--source",choices=("eastmoney","baostock"),default="eastmoney")
    universe.add_argument("--day")
    sub.add_parser("fetch-fund-catalog",help="Collect a complete supplier fund catalogue with explicit active-status gaps")
    huaan=sub.add_parser('fetch-huaan-dealing',help='Collect dated exact-share issuer status and limits, retaining merged cells and currentness gaps')
    huaan.add_argument('codes',nargs='+')
    huaan.add_argument('--registry',default=str(SCRIPT_DIR.parent/'assets/fund-document-sources.json'))

    bars = sub.add_parser("fetch-cn-bars", help="Fetch BaoStock historical bars")
    bars.add_argument("symbol")
    bars.add_argument("--start", required=True)
    bars.add_argument("--end", required=True)
    bars.add_argument("--frequency", default="d")
    bars.add_argument("--adjustment", choices=("qfq", "hfq", "none"), default="qfq")
    bars.add_argument("--source", choices=("baostock", "tencent"), default="baostock")

    metrics = sub.add_parser("fetch-cn-daily-metrics", help="Fetch dated turnover, valuation and status")
    metrics.add_argument("symbol")
    metrics.add_argument("--start", required=True)
    metrics.add_argument("--end", required=True)
    actions=sub.add_parser('fetch-cn-corporate-actions',help='Collect dated adjustment factors and original-unit dividend fields')
    actions.add_argument('symbol');actions.add_argument('--start',required=True);actions.add_argument('--end',required=True)
    sub.add_parser("fetch-cn-industries",help="Collect dated supplier industry taxonomy")
    financial=sub.add_parser("fetch-cn-financials",help="Collect dated profit/growth/cashflow without silently rescaling undocumented units")
    financial.add_argument("symbol")
    financial.add_argument("--year",type=int,required=True)
    financial.add_argument("--quarter",type=int,choices=(1,2,3,4),required=True)
    primary=sub.add_parser('fetch-primary-financials',help='Collect registered SHA/page-reviewed issuer fields with explicit units and periods')
    primary.add_argument('symbol')
    primary.add_argument('--period-end',required=True)
    primary.add_argument('--registry',default=str(SCRIPT_DIR.parent/'assets/issuer-financial-sources.json'))
    primary.add_argument('--document-dir',default='market-data/documents')

    intraday = sub.add_parser("fetch-cn-intraday", help="Fetch mootdx intraday bars")
    intraday.add_argument("symbol")
    intraday.add_argument("--interval", choices=("1m", "5m", "15m", "30m", "60m"), default="5m")
    intraday.add_argument("--count", type=int, default=240)
    intraday.add_argument("--source",choices=("tencent","tdx"),default="tencent")

    aggregates=sub.add_parser("fetch-cn-aggregates",help="Collect dated supplier transaction aggregate pages and their coverage")
    aggregates.add_argument("symbol")
    aggregates.add_argument("--date")
    aggregates.add_argument("--max-pages",type=int,default=64)

    ticks = sub.add_parser("fetch-cn-ticks", help="Fetch classified ticks and calculate order-size totals")
    ticks.add_argument("symbol")
    ticks.add_argument("--date", required=True)
    ticks.add_argument("--lot-size", type=float, default=100.0)
    ticks.add_argument("--large-threshold", type=float, default=200_000.0)
    ticks.add_argument("--super-threshold", type=float, default=1_000_000.0)

    global_bars = sub.add_parser("fetch-global", help="Fetch registered free-tier global bars")
    global_bars.add_argument("symbols", nargs="+")
    global_bars.add_argument("--interval", default="1day")
    global_bars.add_argument("--outputsize", type=int, default=300)
    global_bars.add_argument("--source",choices=("auto","yahoo","twelve_data"),default="auto")

    fred = sub.add_parser("fetch-fred", help="Fetch FRED observations with optional vintage")
    fred.add_argument("series", nargs="+")
    fred.add_argument("--start")
    fred.add_argument("--end")
    fred.add_argument("--vintage")
    fred.add_argument("--source",choices=("auto","csv","api"),default="auto")

    fund = sub.add_parser("fetch-fund-nav", help="Fetch fund NAV from a disclosed fallback source")
    fund.add_argument("codes", nargs="+")
    fund.add_argument("--currency", default="unknown", choices=("unknown", "CNY", "USD", "HKD", "EUR"), help="Exact share-class currency verified from product documents")
    official=sub.add_parser("fetch-fund-official",help="Collect issuer-owned fund terms, documents and dated notices")
    official.add_argument("code")
    official.add_argument("--manager",choices=("chinaamc",),required=True)
    official.add_argument("--document-dir",required=True,help="Runtime directory for original official PDF documents")
    documents=sub.add_parser('fetch-fund-documents',help='Collect reviewed issuer document sources and bind facts to exact PDF bytes')
    documents.add_argument('codes',nargs='+')
    documents.add_argument('--registry',default=str(SCRIPT_DIR.parent/'assets'/'fund-document-sources.json'))
    documents.add_argument('--document-dir',required=True)
    product=sub.add_parser('assemble-fund-product',help='Combine SHA-reviewed exact-share facts and retain field conflicts/gaps')
    holdings=sub.add_parser('fetch-fund-holdings',help='Discover supported issuer equity report and retain exact NAV denominators and partial coverage')
    holdings.add_argument('code')
    holdings.add_argument('--look-through',action='store_true',help='Also collect the exact disclosed target ETF holdings')
    holdings_view=sub.add_parser('fund-lookthrough',help='Read disclosed feeder/ETF snapshots and compute dated exposure without portfolio inputs')
    holdings_view.add_argument('code')
    holdings_view.add_argument('--as-of')
    graph_view=sub.add_parser('fund-lookthrough-graph',help='Recursively replace disclosed fund wrappers with exact reviewed child holdings, retaining dates and missing branches')
    graph_view.add_argument('code')
    graph_view.add_argument('--as-of')
    graph_view.add_argument('--max-depth',type=int,default=8)
    fund_chart=sub.add_parser('chart-fund-nav',help='Freeze exact-share NAV inputs and render NAV/BOLL/MACD/drawdown without invented OHLC or volume')
    fund_chart.add_argument('code')
    fund_chart.add_argument('--output-dir',required=True)
    fund_chart.add_argument('--provider')
    fund_chart.add_argument('--as-of')
    fund_study=sub.add_parser('research-fund',help='Proactively collect one exact fund and assemble NAV/exposure/underlying/cost/dealing evidence for the final skill report')
    fund_study.add_argument('fund')
    fund_study.add_argument('--output-dir',required=True)
    fund_study.add_argument('--no-collect',action='store_true')
    fund_study.add_argument('--horizon',type=int,default=20)
    fund_study.add_argument('--position-state',choices=('unknown','held','unheld'),default='unknown')
    fund_study.add_argument('--holding-fee-age-days',type=int,default=90)
    fund_study.add_argument('--A-subscription-rate-scenario',type=float)
    fund_study.add_argument('--registry',help='Runtime source-reviewed exact-share registry for a manager outside the bundled sources')
    reviewed_holdings=sub.add_parser('import-reviewed-fund-holdings',help='Bind analyst-reviewed manager-neutral holdings to original PDF bytes/passages and verify denominators')
    reviewed_holdings.add_argument('review_json')
    reviewed_holdings.add_argument('--document-dir',required=True)
    fund_business=sub.add_parser('fetch-chinaamc-business',help='Retain issuer business flags and page update label, without claiming current channel availability')
    fund_business.add_argument('codes',nargs='+')
    product.add_argument('codes',nargs='+')

    compute = sub.add_parser("compute", help="Compute indicators from stored bars")
    compute.add_argument("symbol")
    compute.add_argument("--interval", default="d")
    compute.add_argument("--provider")
    compute.add_argument("--price-basis")
    compute.add_argument("--limit", type=int, default=500)

    health = sub.add_parser("health", help="Report missing, failed and stale collection runs")
    health.add_argument("--recent-runs", type=int, default=100)
    health.add_argument("--as-of")
    scoped=sub.add_parser('profile-health',help='Read data/collector health for exactly the configured research requirements')
    scoped.add_argument('--config',required=True)
    scoped.add_argument('--profile',choices=('allocation','tactical'),required=True)
    scoped.add_argument('--as-of')
    sectors=sub.add_parser('sector-price-scan',help='Compare named CN/US sector proxies on common dated price windows')
    sectors.add_argument('--config',required=True)
    sectors.add_argument('--as-of')

    snapshot = sub.add_parser("snapshot", help="Emit a compact evidence snapshot for the research agent")
    snapshot.add_argument("--observation-limit", type=int, default=100, help="Legacy hint; latest per series is not globally truncated. Use evidence --window for histories")
    snapshot.add_argument("--as-of")

    discovery = sub.add_parser("discover", help="List the independent imported/collected research universe")
    discovery.add_argument("--as-of")
    discovery.add_argument("--limit",type=int,default=200)
    trace=sub.add_parser('source-trace',help='Verify a bounded set of database rows against their explicit archived HTTP responses')
    trace.add_argument('identity')
    trace.add_argument('--kind',choices=('quote','bar','observation'),required=True)
    trace.add_argument('--dataset')
    trace.add_argument('--interval',default='1d')
    trace.add_argument('--provider')
    trace.add_argument('--limit',type=int,default=10)
    trace.add_argument('--as-of')
    broad=sub.add_parser("scan-market",help="Measure actual equity breadth and shortlist current quote anomalies")
    opportunity=sub.add_parser('research-opportunities',help='Freeze a portfolio-independent market/sector scan; continue the autonomous skill through exact candidate diligence and action')
    opportunity.add_argument('--config',required=True)
    opportunity.add_argument('--output-dir',required=True)
    opportunity.add_argument('--refresh-global',action='store_true')
    opportunity.add_argument('--as-of',help='Frozen evidence cutoff; incompatible with live refresh')
    candidates=sub.add_parser('research-candidates',help='Collect each independently selected candidate own native price history, chart and fund evidence')
    candidates.add_argument('--candidates-json',required=True,help='Analyst shortlist with market/kind/identity/selection_reason; not a user sector-choice pause')
    candidates.add_argument('--output-dir',required=True)
    candidates.add_argument('--no-collect',action='store_true')
    broad.add_argument("--as-of")
    broad.add_argument("--limit",type=int,default=30)
    deeper=sub.add_parser('collect-followups',help='Collect histories and dated evidence for independently discovered anomalies')
    deeper.add_argument('--config',required=True)
    deeper.add_argument('--limit',type=int,default=5)
    deeper.add_argument('--year',type=int)
    deeper.add_argument('--quarter',type=int,choices=(1,2,3,4))
    imported = sub.add_parser("import-evidence", help="Import source-grounded product, holdings or fundamental observations")
    imported.add_argument("path")
    screening = sub.add_parser("screen", help="Find price/volume/relative-strength questions without issuing trades")
    screening.add_argument("symbols", nargs="*")
    screening.add_argument("--interval", default="1d")
    screening.add_argument("--provider")
    screening.add_argument("--price-basis")
    screening.add_argument("--benchmark")
    screening.add_argument("--as-of")
    evidence = sub.add_parser("evidence", help="Read a bounded evidence package for a specific question")
    evidence.add_argument("identity")
    evidence.add_argument("--question", choices=("trend", "flow", "valuation", "fund", "allocation"), default="trend")
    evidence.add_argument("--interval", default="1d")
    evidence.add_argument("--provider")
    evidence.add_argument("--price-basis")
    evidence.add_argument("--window", type=int, default=120)
    evidence.add_argument("--as-of")
    evidence.add_argument("--point-in-time", action="store_true")
    ledger = sub.add_parser("ledger-add", help="Append a complete thesis or dated review without rewriting its original")
    ledger.add_argument("--file", required=True)
    ledger.add_argument("--entry", required=True)
    reviewed=sub.add_parser('ledger-review',help='Evaluate original typed conditions against sealed newer evidence and optionally append review')
    reviewed.add_argument('--file',required=True)
    reviewed.add_argument('--directory',required=True)
    reviewed.add_argument('--append',action='store_true')
    prepared=sub.add_parser('prepare-research',help='Freeze numerical research inputs without holdings')
    prepared.add_argument('--directory',required=True)
    prepared.add_argument('--profile',choices=('allocation','tactical'),required=True)
    prepared.add_argument('--config',help='Use the named config database and its task-scoped requirements')
    verify=sub.add_parser('verify-research',help='Recompute sealed evidence from frozen inputs without the live database')
    verify.add_argument('--directory',required=True)
    locked=sub.add_parser('lock-market-view',help='Validate evidence-bound independent analysis before personalization')
    locked.add_argument('--directory',required=True)
    locked.add_argument('--view',required=True)
    overlay=sub.add_parser('load-portfolio',help='Load authoritative private holdings only after market-view sealing')
    overlay.add_argument('--directory',required=True)
    overlay.add_argument('--portfolio',required=True)
    dossier=sub.add_parser('freeze-product-dossier',help='Freeze requested exact-share product evidence after market-view locking')
    dossier.add_argument('codes',nargs='+');dossier.add_argument('--directory',required=True)
    mapping=sub.add_parser('map-portfolio',help='Map loaded authoritative positions after the market/product seals')
    mapping.add_argument('--directory',required=True)
    report=sub.add_parser('export-report',help='Export sealed market research and an optional separate private appendix')
    report.add_argument('--directory',required=True)
    report.add_argument('--output',required=True)
    report.add_argument('--include-portfolio',action='store_true')
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "init-config":
        _json({"config": str(write_default_config(args.config, overwrite=args.overwrite))})
        return 0
    if args.command in {'profile-health','sector-price-scan'}:
        try:
            config=load_config(args.config);base=Path(args.config).resolve().parent
            database=Path(config.get('database','market-data/market.sqlite3'))
            store=MarketStore(database if database.is_absolute() else base/database,read_only=True)
            result=sector_price_scan(store,config,as_of=args.as_of) if args.command=='sector-price-scan' else profile_health(store,config,args.profile,as_of=args.as_of)
            _json(result)
            return 0 if result['status'] in {'ok','recovered','bounded_price_proxy_scan'} else 2
        except Exception as exc:
            _json({'status':'failed','error':redact_error(str(exc))});return 2
    if args.command == "ledger-add":
        try:
            _json(ledger_append(args.file, args.entry))
            return 0
        except Exception as exc:
            _json({"status": "failed", "error": redact_error(str(exc))})
            return 2
    if args.command=='ledger-review':
        try:
            _json(review_ledger(args.file,args.directory,append=args.append));return 0
        except Exception as exc:
            _json({'status':'failed','error':redact_error(str(exc))});return 2
    if args.command=='map-portfolio':
        try:
            _json(map_portfolio(args.directory));return 0
        except Exception as exc:
            _json({'status':'failed','error':redact_error(str(exc))});return 2
    if args.command=='export-report':
        try:
            _json(export_report(args.directory,args.output,include_portfolio=args.include_portfolio));return 0
        except Exception as exc:
            _json({'status':'failed','error':redact_error(str(exc))});return 2
    if args.command=='verify-chips':
        try:
            from market_core.chips import verify_chip_research
            result=verify_chip_research(args.directory);_json(result)
            return 0 if result['status']=='ok' else 2
        except Exception as exc:
            _json({'status':'failed','error':redact_error(str(exc))});return 2
    if args.command in {'verify-research','verify-stock-research'}:
        try:
            result=(verify_research(args.directory) if args.command=='verify-research' else verify_stock_research(args.directory));_json(result)
            return 0 if result['status']=='ok' else 2
        except Exception as exc:
            _json({'status':'failed','error':redact_error(str(exc))});return 2
    if args.command in {'lock-market-view','load-portfolio'}:
        try:
            _json(lock_market_view(args.directory,args.view) if args.command=='lock-market-view' else load_portfolio_after_view(args.directory,args.portfolio))
            return 0
        except Exception as exc:
            _json({'status':'failed','error':redact_error(str(exc))});return 2
    if args.command=='collect-followups':
        try:
            pipeline=MarketPipeline(load_config(args.config),config_path=args.config)
            result=collect_followups(pipeline,limit=args.limit,year=args.year,quarter=args.quarter)
            _json(result)
            return 0 if all(row['status']=='ok' for row in result['runs']) else 2
        except Exception as exc:
            _json({'status':'failed','error':redact_error(str(exc))});return 2
    if args.command == "run":
        config = load_config(args.config)
        pipeline = MarketPipeline(config, config_path=args.config)
        results = [asdict(result) for result in pipeline.run_profile(args.profile)]
        health = pipeline.health(args.profile)
        _json({"profile": args.profile, "database": str(pipeline.database), "runs": results, "health": health})
        return 0 if results and health['status'] in {'ok','recovered'} else 2
    if args.command == "doctor":
        config = load_config(args.config)
        providers = config.get("providers", {})
        profiles = config.get("profiles", {})
        checks = []
        for provider_name in ("tencent", "eastmoney", "fund_eastmoney"):
            enabled = bool((providers.get(provider_name) or {}).get("enabled", False))
            checks.append(
                {
                    "component": provider_name, "enabled": enabled,
                    "status": "configured_unprobed" if enabled else "disabled",
                }
            )
        for provider_name, default_env in (
            ("fred", "FRED_API_KEY"), ("twelve_data", "TWELVE_DATA_API_KEY")
        ):
            settings = providers.get(provider_name) or {}
            enabled = bool(settings.get("enabled", False))
            if args.profile == "tactical":
                enabled = False
            env_name = str(settings.get("api_key_env") or default_env)
            present = bool(os.environ.get(env_name))
            public_transport=settings.get("source","auto") in ({"auto","csv"} if provider_name=="fred" else {"auto","yahoo"})
            checks.append(
                {
                    "component": provider_name, "enabled": enabled,
                    "credential_env": env_name, "credential_present": present,
                    "status": "ready" if enabled and present else "public_source_ready_for_probe" if enabled and public_transport else "missing_key" if enabled else "disabled",
                }
            )
        for provider_name, package in (("baostock", "baostock"), ("mootdx", "tdxpy")):
            enabled = bool((providers.get(provider_name) or {}).get("enabled", False))
            installed = importlib.util.find_spec(package) is not None
            checks.append(
                {
                    "component": provider_name, "enabled": enabled,
                    "package_installed": installed,
                    "status": "ready" if enabled and installed else "missing_package" if enabled else "disabled",
                }
            )
        allocation = profiles.get("allocation") or {}
        tactical = profiles.get("tactical") or {}
        coverage = {
            "allocation": {
                key: len(allocation.get(key) or [])
                for key in ("cn_benchmarks", "cn_sector_indices", "global_symbols", "fred_series", "fund_codes")
            },
            "tactical": {
                key: len(tactical.get(key) or [])
                for key in ("cn_symbols", "flow_symbols", "tick_symbols", "board_types", "board_periods")
            },
        }
        blockers = [row for row in checks if row["status"].startswith("missing_")]
        if args.profile != "allocation" and not tactical.get("cn_symbols"):
            blockers.append({"component": "tactical.cn_symbols", "status": "not_configured"})
        _json(
            {
                "status": "ready_for_live_probe" if not blockers else "incomplete",
                "config": str(Path(args.config).expanduser().resolve()),
                "checks": checks,
                "coverage_counts": coverage,
                "blockers": blockers,
                "secrets_printed": False,
            }
        )
        return 0 if not blockers else 2

    try:
        prepared_config=None
        if args.command=='research-opportunities' and args.as_of and args.refresh_global:
            raise ValueError('Historical cutoff research cannot use live refresh')
        if args.command in {'prepare-research','research-opportunities'} and args.config:
            prepared_config=load_config(args.config);base=Path(args.config).resolve().parent
            configured_db=Path(prepared_config.get('database','market-data/market.sqlite3'))
            configured_db=(configured_db if configured_db.is_absolute() else base/configured_db).resolve()
            supplied_args=argv if argv is not None else sys.argv[1:]
            if any(arg=='--db' or arg.startswith('--db=') for arg in supplied_args) and Path(args.db).resolve()!=configured_db:
                raise ValueError('Explicit --db differs from the preparation config database')
            args.db=str(configured_db)
        store = MarketStore(args.db, read_only=args.command in {"health", "snapshot", "discover", "screen", "evidence", "scan-market", "prepare-research","freeze-product-dossier","source-trace","fund-lookthrough","fund-lookthrough-graph","chart-fund-nav"} or (args.command=='research-opportunities' and not args.refresh_global) or (args.command in {'research-stock','research-fund','research-candidates'} and args.no_collect))
        if args.command=='source-trace':
            result=store.source_trace(args.kind,args.identity,dataset=args.dataset,interval=args.interval,
                                      provider=args.provider,limit=args.limit,as_of=args.as_of)
            _json(result)
            return 0 if result['status']=='verified' else 2
        if not store.read_only:store.response_vault=ResponseVault(store.path.parent/'raw-responses')
        if args.command == "fetch-cn-quote":
            provider = _archived(TencentProvider(),store)
            started = _started()
            rows = provider.fetch_quotes(args.symbols)
            count = store.upsert_quotes(rows)
            derived = store.upsert_indicators(quote_indicator_rows(rows))
            store.record_run(provider.name, "cn_quote", started, "ok", count)
            _json({"stored": count, "stored_indicators": derived, "quotes": [row.to_dict() for row in rows]})
        elif args.command == "fetch-board":
            provider = _archived(EastmoneyProvider(),store)
            started = _started()
            rows = provider.fetch_board_snapshot(args.type, args.period, args.limit)
            count = store.upsert_observations(rows)
            store.record_run(provider.name, f"board_{args.type}_{args.period}", started, "ok", count)
            _json({"stored": count, "sample": [row.to_dict() for row in rows[:10]]})
        elif args.command == "fetch-cn-flow":
            provider = _archived(EastmoneyProvider(),store)
            started = _started()
            rows = provider.fetch_stock_flow(args.symbol, interval=args.interval)
            count = store.upsert_observations(rows)
            store.record_run(provider.name, f"stock_flow_{args.interval}", started, "ok", count)
            _json({"stored": count, "latest": rows[-1].to_dict()})
        elif args.command == "fetch-universe":
            started = _started()
            if args.source=="baostock":
                if args.scope!="stocks" or not args.day: raise ValueError("BaoStock universe needs --scope stocks and an explicit --day")
                provider=BaoStockProvider()
                rows=provider.fetch_universe(day=args.day)
            else:
                provider=_archived(EastmoneyProvider(),store)
                rows=provider.fetch_universe(scope=args.scope,max_pages=args.max_pages,page_size=args.page_size)
            count = store.upsert_observations(rows)
            coverage = rows[-1].value
            status = "ok" if coverage["status"] in {"complete_for_provider_filter","complete_query"} else "partial"
            store.record_run(provider.name, "universe:" + args.scope, started, status, count, details=coverage)
            _json({"stored":count,"coverage":coverage})
            return 0 if status == "ok" else 2
        elif args.command == "fetch-fund-catalog":
            provider=_archived(FundCatalogProvider(),store)
            started=_started()
            rows=provider.fetch_universe()
            count=store.upsert_observations(rows)
            store.record_run(provider.name,"fund_catalog",started,"ok",count,details=rows[-1].value)
            _json({"stored":count,"coverage":rows[-1].value})
        elif args.command == "fetch-cn-bars":
            provider = _archived(BaoStockProvider() if args.source == "baostock" else TencentHistoryProvider(),store)
            started = _started()
            rows = provider.fetch_bars(
                args.symbol, start_date=args.start, end_date=args.end,
                frequency=args.frequency, adjustment=args.adjustment,
            )
            count = store.upsert_bars(rows)
            derived = store.upsert_indicators(indicator_rows_grouped(rows))
            store.record_run(provider.name, f"bars_{args.frequency}", started, "ok", count)
            _json({"stored_bars": count, "stored_indicators": derived})
        elif args.command == "fetch-cn-intraday":
            provider = _archived(TencentIntradayProvider() if args.source=="tencent" else MootdxProvider(),store)
            started = _started()
            rows = provider.fetch_bars(args.symbol, interval=args.interval, count=args.count)
            count = store.upsert_bars(rows)
            derived = store.upsert_indicators(indicator_rows_grouped(rows))
            store.record_run(provider.name, f"bars_{args.interval}", started, "ok", count)
            _json({"stored_bars": count, "stored_indicators": derived})
        elif args.command == "fetch-cn-aggregates":
            provider=_archived(TencentIntradayProvider(),store)
            started=_started()
            rows=provider.fetch_transactions(args.symbol,date=args.date,max_pages=args.max_pages)
            count=store.upsert_observations(rows)
            summary=rows[-1].value
            status="ok" if summary["status"]=="complete_supplier_window" else "partial"
            store.record_run(provider.name,"transaction_aggregates:"+args.symbol,started,status,count,details=summary)
            _json({"stored":count,"summary":summary})
            return 0 if status=="ok" else 2
        elif args.command == "fetch-cn-ticks":
            provider = MootdxProvider()
            started = _started()
            rows = provider.fetch_transactions(args.symbol, date=args.date)
            summary = summarize_transactions(
                rows, lot_size=args.lot_size, large_notional=args.large_threshold,
                super_large_notional=args.super_threshold,
            )
            count = store.upsert_observations([*rows, summary])
            store.record_run(
                provider.name, "tick_transactions", started, "ok", count,
                details={"raw_tick_rows": len(rows), "summary_rows": 1},
            )
            _json({"stored": count, "summary": summary.to_dict()})
        elif args.command=='fetch-cn-corporate-actions':
            import contextlib,io
            with contextlib.redirect_stdout(io.StringIO()):
                rows=BaoStockProvider().fetch_corporate_actions(args.symbol,start_date=args.start,end_date=args.end)
            _json({'stored':store.upsert_observations(rows),'records':[row.to_dict() for row in rows]})
        elif args.command=='research-chips':
            from market_core.chips import create_chip_research
            _json(create_chip_research(store,args.symbol,args.output_dir,collect=not args.no_collect,end=args.end))
        elif args.command=='verify-chips':
            from market_core.chips import verify_chip_research
            result=verify_chip_research(args.directory);_json(result)
            return 0 if result['status']=='ok' else 2
        elif args.command=='research-stock':
            result=research_stock_request(store,args.symbol,args.output_dir,market=args.market,
                collect=not args.no_collect,lookback_years=args.lookback_years,horizon=args.horizon,
                provider=args.provider,registry_path=args.registry,position_state=args.position_state,risk_budget_CNY=args.risk_budget_cny)
            _json(result)
        elif args.command=='fetch-issuer-documents':
            result=fetch_catalogued_documents(store,args.symbol,args.announcement_ids);_json(result)
            return 2 if any(r['status']!='original_document_received' for r in result['documents']) else 0
        elif args.command=='fetch-huaan-dealing':
            provider=_archived(HuaanDealingProvider(args.registry),store);started=_started()
            rows=provider.fetch_evidence(args.codes);count=store.upsert_observations(rows)
            store.record_run(provider.name,'fund_dealing_snapshot',started,'ok',count,
                details={'codes':args.codes,'later_notice_audit_complete':False})
            _json({'stored':count,'status':'ok','later_notice_audit_complete':False,
                   'source_dates':sorted({r.as_of for r in rows}),'rows':[r.to_dict() for r in rows]})
        elif args.command=='fetch-cn-yield-curves':
            provider=_archived(ChinaBondCurveProvider(),store);started=_started()
            rows=provider.fetch_evidence();count=store.upsert_observations(rows)
            store.record_run(provider.name,'cn_bond_yield_curves',started,'ok',count)
            _json({'stored':count,'curves':[r.value for r in rows]})
        elif args.command=='fetch-primary-financials':
            provider=_archived(IssuerFinancialProvider(args.registry,args.document_dir),store);started=_started()
            rows=provider.fetch_evidence(normalize_cn_symbol(args.symbol,stock_only=True),args.period_end)
            count=store.upsert_observations(rows)
            reviewed=any(row.dataset=='financials_primary' for row in rows)
            status='ok' if reviewed else 'partial'
            store.record_run(provider.name,'primary_financials:'+args.symbol,started,status,count,
                             details={'reviewed_fields':sum(len(r.value.get('fields',[])) for r in rows),'original_publication_time_known':False})
            _json({'stored':count,'status':status,'reviewed_fields':sum(len(r.value.get('fields',[])) for r in rows),
                   'vendor_records_promoted':False})
            return 0 if reviewed else 2
        elif args.command == "fetch-cn-daily-metrics":
            provider = BaoStockProvider()
            started = _started()
            rows = provider.fetch_daily_metrics(
                args.symbol, start_date=args.start, end_date=args.end
            )
            count = store.upsert_observations(rows)
            store.record_run(provider.name, "cn_daily_valuation_liquidity", started, "ok", count)
            _json({"stored": count, "latest": rows[-1].to_dict()})
        elif args.command in {"fetch-cn-industries","fetch-cn-financials"}:
            provider=BaoStockProvider();started=_started()
            rows=provider.fetch_industries() if args.command=="fetch-cn-industries" else provider.fetch_financials(args.symbol,year=args.year,quarter=args.quarter)
            count=store.upsert_observations(rows)
            store.record_run(provider.name,args.command,started,'ok',count)
            _json({'stored':count,'sample':[row.to_dict() for row in rows[:3]]})
        elif args.command == "fetch-global":
            started = _started()
            minute_quality=[]
            registered=args.source=="twelve_data" or (args.source=="auto" and bool(os.environ.get("TWELVE_DATA_API_KEY")))
            if registered:
                provider=_archived(TwelveDataProvider(os.environ.get("TWELVE_DATA_API_KEY","")),store)
                rows=provider.fetch_time_series(args.symbols,interval=args.interval,outputsize=args.outputsize)
            else:
                from market_core.conventions import interval_name
                provider=_archived(YahooProvider(),store)
                native_interval,lookback=public_history_request(args.interval,args.outputsize)
                rows,extra=provider.fetch_evidence(args.symbols,interval=native_interval,lookback_days=lookback,as_of=started)
                rows=completed_public_intraday(rows,native_interval,started)
                if not rows:raise ValueError('No completed public price bars at the request cutoff')
                if native_interval=='1m':
                    previous=[]
                    for symbol in args.symbols:
                        previous.extend(store.get_bars(symbol,'1m',provider=provider.name,price_basis='provider_split_adjusted_close',limit=2000))
                    minute_quality=audit_intraday_quality(rows,previous)
                    store.upsert_observations(quality_observations(minute_quality,started))
                store.upsert_observations(extra)
            count = store.upsert_bars(rows)
            computed=mark_volume_indicator_quality(indicator_rows_grouped(rows),minute_quality)
            derived = store.upsert_indicators(computed)
            store.record_run(provider.name, f"bars_{args.interval}", started, "ok", count)
            _json({"stored_bars": count, "stored_indicators": derived,"intraday_source_quality":minute_quality})
        elif args.command == "fetch-fred":
            started = _started()
            registered=args.source=="api" or (args.source=="auto" and bool(os.environ.get("FRED_API_KEY")))
            if args.vintage and not registered: raise ValueError("Historical vintage needs the registered API; public CSV does not prove vintage availability")
            provider=_archived(FredProvider(os.environ.get("FRED_API_KEY","")) if registered else FredCsvProvider(),store)
            parameters={"observation_start":args.start,"observation_end":args.end}
            if registered: parameters["vintage_date"]=args.vintage
            rows=provider.fetch_series(args.series,**parameters)
            count = store.upsert_observations(rows)
            store.record_run(provider.name, "macro_series", started, "ok", count)
            _json({"stored": count})
        elif args.command == "fetch-fund-nav":
            provider = _archived(EastmoneyFundProvider(),store)
            total = 0
            for code in args.codes:
                started = _started()
                contract=verified_nav_currency(store,code)
                if args.currency!='unknown':contract={'currency':args.currency,'verified':True,'source':'explicit_caller_verified_currency'}
                rows = provider.fetch_evidence(code, currency=contract['currency'])
                for row in rows:row.raw['currency_contract']=contract
                count = store.upsert_observations(rows)
                store.upsert_indicators(series_indicator_rows([row for row in rows if row.dataset == "fund_unit_nav"]))
                total += count
                store.record_run(provider.name, f"fund_unit_nav:{code}", started, "ok", count)
            _json({"stored": total})
        elif args.command == "fetch-fund-official":
            provider=_archived(ChinaAMCFundProvider(document_dir=args.document_dir),store)
            started=_started()
            rows=provider.fetch_evidence(args.code)
            count=store.upsert_observations(rows)
            store.record_run(provider.name,"fund_official:"+args.code,started,"ok",count)
            _json({"stored":count,"product":rows[0].to_dict()})
        elif args.command=='fetch-fund-documents':
            provider=_archived(FundDocumentProvider(args.registry,args.document_dir),store);started=_started()
            rows=[]
            for code in args.codes:rows.extend(provider.fetch_evidence(code))
            count=store.upsert_observations(rows)
            store.record_run(provider.name,args.command,started,'ok',count)
            _json({'stored':count,'documents':[{'identity':row.identity,'sha256':row.value['sha256'],'review_required':row.value['review_required']} for row in rows]})
        elif args.command=='assemble-fund-product':
            rows=[assemble_product(store,code) for code in args.codes]
            _json({'stored':store.upsert_observations(rows),'products':[{'code':row.identity,'currency':row.value['currency'],
                   'fields_verified':row.value['fields_verified'],'conflicts':list(row.value['field_conflicts']),
                   'fee_contract_missing':row.value['fee_contract_missing'],'selection_ready':False} for row in rows]})
        elif args.command=='fetch-fund-holdings':
            provider=_archived(ChinaAMCHoldingsProvider(Path(args.db).resolve().parent/'documents'),store)
            started=_started();rows=provider.fetch_evidence(args.code);count=store.upsert_observations(rows)
            parent=rows[0].value
            store.record_run(provider.name,'fund_holdings:'+args.code,started,'ok',count,
                details={'report_date':parent['report_date'],'stock_detail_reconciled':parent['stock_detail_reconciled']})
            result={'stored':count,'fund_code':args.code,'report_date':parent['report_date'],'stock_rows':len(parent['stocks']),
                'stock_detail_reconciled':parent['stock_detail_reconciled'],'today_holdings_reconstructed':False}
            if args.look_through:
                if len(parent['target_funds'])!=1:raise ValueError('Exactly one disclosed target ETF required for this helper')
                target_code=parent['target_funds'][0]['identity'][2:];started=_started()
                target=provider.fetch_evidence(target_code);result['stored']+=store.upsert_observations(target)
                store.record_run(provider.name,'fund_holdings:'+target_code,started,'ok',len(target),
                    details={'report_date':target[0].value['report_date'],'stock_detail_reconciled':target[0].value['stock_detail_reconciled']})
                result['lookthrough']=look_through_feeder(parent,target[0].value)
            _json(result)
        elif args.command=='fund-lookthrough':
            _json(stored_lookthrough(store,args.code,as_of=args.as_of))
        elif args.command=='fund-lookthrough-graph':
            _json(stored_fund_graph(store,args.code,as_of=args.as_of,max_depth=args.max_depth))
        elif args.command=='chart-fund-nav':
            _json(create_fund_nav_chart(store,args.code,args.output_dir,provider=args.provider,as_of=args.as_of))
        elif args.command=='fetch-chinaamc-business':
            provider=_archived(ChinaAMCBusinessProvider(),store);started=_started()
            rows=provider.fetch_evidence(args.codes);count=store.upsert_observations(rows)
            store.record_run(provider.name,'fund_business_table',started,'ok',count)
            _json({'stored':count,'rows':[r.value for r in rows]})
        elif args.command=='research-fund':
            code=resolve_fund_identifier(store,args.fund,allow_network=not args.no_collect)
            _json(create_fund_research(store,code,args.output_dir,collect=not args.no_collect,horizon=args.horizon,
                position_state=args.position_state,holding_fee_age_days=args.holding_fee_age_days,
                A_subscription_rate_scenario=args.A_subscription_rate_scenario,registry_path=args.registry))
        elif args.command=='import-reviewed-fund-holdings':
            review=json.loads(Path(args.review_json).read_text(encoding='utf-8-sig'))
            snapshot=reviewed_snapshot(review,args.document_dir)
            row=Observation('reviewed_primary_holdings','fund_holdings',snapshot['fund_code'],snapshot['report_date'],snapshot,
                publication=snapshot['publication_date'],unit='reviewed_disclosure_snapshot',currency=snapshot['report_currency'],
                quality='source_bound_reviewed_snapshot',source_url=snapshot['source_url'],
                raw={'semantic_review':'analyst reviewed original disclosure; byte/passage/math checks only'},
                source_receipts=snapshot['source_receipts'])
            count=store.upsert_observations([row]);_json({'stored':count,'fund_code':snapshot['fund_code'],
                'security_detail_of_fund_NAV':snapshot['security_detail_of_fund_NAV'],
                'today_holdings_reconstructed':False,'automatic_semantic_extraction_verified':False})
        elif args.command=='freeze-product-dossier':
            _json(freeze_product_dossier(store,args.directory,args.codes))
        elif args.command == "compute":
            bars = store.get_bars(
                args.symbol, args.interval, provider=args.provider, price_basis=args.price_basis, limit=args.limit
            )
            rows = indicator_rows_grouped(bars)
            _json({"stored": store.upsert_indicators(rows), "bar_count": len(bars)})
        elif args.command == "health":
            _json(store.health(recent_runs=args.recent_runs, as_of=args.as_of))
        elif args.command == "snapshot":
            _json(store.snapshot(observation_limit=args.observation_limit, as_of=args.as_of))
        elif args.command == "discover":
            _json(discover(store, as_of=args.as_of,limit=args.limit))
        elif args.command == "scan-market":
            result=scan_market(store,as_of=args.as_of,limit=args.limit)
            _json(result)
            return 0 if result['status']=='research_scan' else 2
        elif args.command=='research-opportunities':
            _json(prepare_opportunity_research(store,prepared_config,args.output_dir,refresh_global=args.refresh_global,as_of=args.as_of))
        elif args.command=='research-candidates':
            result=research_candidates(store,json.loads(Path(args.candidates_json).read_text(encoding='utf-8-sig')),args.output_dir,collect=not args.no_collect)
            _json(result)
            return 2 if any(r['status']=='candidate_evidence_incomplete' for r in result['results']) else 0
        elif args.command=='prepare-research':
            _json(prepare_research(store,args.directory,profile=args.profile,config=prepared_config))
        elif args.command == "import-evidence":
            _json({"stored": import_evidence(store, args.path)})
        elif args.command == "screen":
            _json(screen(store, symbols=args.symbols, interval=args.interval, provider=args.provider, price_basis=args.price_basis, benchmark=args.benchmark, as_of=args.as_of))
        elif args.command == "evidence":
            result = evidence_pack(store, args.identity, question=args.question, interval=args.interval, provider=args.provider, price_basis=args.price_basis, window=args.window, as_of=args.as_of, point_in_time=args.point_in_time)
            _json(result)
            return 0 if result["status"] == "ready_for_research" else 2
        return 0
    except Exception as exc:
        provider = getattr(locals().get("provider"), "name", "local_engine")
        if getattr(locals().get('store'),'response_vault',None):
            for event in list(store.response_vault.events[store._response_offset:]):
                if event.get('status') in {'http_ok','cache_hit'}:store.response_vault.reject(event,'Collection command failed validation')
        try:
            store.record_run(provider, args.command, locals().get("started", _started()), "failed", 0, error=str(exc))
        except Exception:
            pass
        _json({"status": "failed", "command": args.command, "error": redact_error(str(exc))})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
