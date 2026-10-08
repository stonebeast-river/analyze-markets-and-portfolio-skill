"""Deterministic research prioritization and question-specific evidence, never trade signals."""
import json
import math
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .conventions import interval_name, parse_time
from .models import Observation
from .sessions import expected_session


def import_evidence(store, path):
    records = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(records, list):
        raise ValueError("Evidence input must be a JSON array")
    allowed = {"fund_product", "fund_holdings", "fund_distributions", "financials", "announcement", "instrument_listing", "macro_series", "exposure_measure"}
    rows = []
    for record in records:
        if record.get("dataset") not in allowed or not record.get("source_url", "").startswith("https://"):
            raise ValueError("Use a supported dataset and a direct HTTPS source URL")
        if not record.get("identity") or not record.get("as_of") or "value" not in record:
            raise ValueError("identity, as_of and value are required")
        if record["dataset"] == "fund_product" and not isinstance(record["value"], dict):
            raise ValueError("fund_product value must be a field dictionary")
        if record['dataset']=='exposure_measure':
            value=record['value']
            number=value.get('value') if isinstance(value,dict) else None
            if not isinstance(value,dict) or not all(value.get(field) for field in ('measurement','unit','window')) or type(number) not in (int,float) or not math.isfinite(number):
                raise ValueError('Exposure measures require measurement, value, unit and window')
        parse_time(record["as_of"])
        if record.get("publication"):
            parse_time(record["publication"])
        record = dict(record)
        record.setdefault("provider", "documented_source_import")
        record.setdefault("quality", "imported_requires_source_verification")
        rows.append(Observation(**record))
    return store.upsert_observations(rows)


def discover(store, *, as_of=None, limit=200):
    catalog = store.universe(as_of=as_of,limit=limit)
    return {**catalog,"universe_source":"imported_listings_and_collected_data" if catalog["listed_count"] else "collected_data_only",
            "covered_count":catalog["price_covered_count"],"full_market_coverage_verified":False,"holdings_used":False}


def screen(store, *, symbols=None, interval="1d", provider=None, price_basis=None, benchmark=None, as_of=None):
    cutoff = as_of or datetime.now(timezone.utc).isoformat()
    universe = discover(store, as_of=cutoff)
    selected = symbols or universe["price_symbols"]
    snapshot = store.snapshot(as_of=cutoff)
    latest_quotes = {row["symbol"]: row for row in snapshot["latest_quotes"]}
    candidates = []
    for symbol in selected:
        groups = defaultdict(list)
        for bar in store.get_bars(symbol, interval, provider=provider, price_basis=price_basis, limit=120, as_of=cutoff):
            groups[(bar.provider, bar.price_basis, bar.currency)].append(bar)
        if not groups:
            navs = store.get_observations("fund_unit_nav", symbol, limit=120, as_of=cutoff)
            for row in navs:
                groups[(row["provider"], row["price_basis"], row["currency"])].append(row)
        if not groups:
            candidates.append({"identity": symbol, "status": "insufficient_evidence", "missing": ["historical_price_series"], "signals": []})
            continue
        for (source, basis, currency), records in groups.items():
            is_nav = isinstance(records[0], dict)
            try:
                closes = [float(row["value"] if is_nav else row.close) for row in records]
            except (TypeError, ValueError):
                closes = [float("nan")] * len(records)
            timestamps = [row["as_of"] if is_nav else row.timestamp for row in records]
            missing = []
            if len(records) < 61:
                missing.append("minimum_61_observations")
            if basis in {"unknown", "legacy_unknown", "not_applicable", ""}:
                missing.append("verified_price_basis")
            if currency in {"unknown", ""}:
                missing.append("verified_currency")
            if not all(math.isfinite(value) and value > 0 for value in closes):
                missing.append("valid_positive_prices")
            if not is_nav and symbol.startswith(("sh", "sz", "bj")) and interval_name(interval) == "1d":
                expected = expected_session(cutoff)
                if expected is None or timestamps[-1][:10] != expected:
                    missing.append("current_exchange_session")
            metrics, signals = {}, []
            if not missing:
                metrics = {f"return_{period}period": closes[-1] / closes[-1-period] - 1 for period in (1,5,20,60)}
                metrics["drawdown_from_20period_high"] = closes[-1] / max(closes[-20:]) - 1
                for name, threshold in (("return_5period", 0.05), ("return_20period", 0.10)):
                    if abs(metrics[name]) >= threshold:
                        signals.append({"rule": "price_move", "metric": name, "value": metrics[name], "absolute_threshold": threshold})
                if not is_nav:
                    volumes = [row.volume for row in records[-6:]]
                    if all(value is not None and value > 0 for value in volumes):
                        ratio = volumes[-1] / (sum(volumes[:-1]) / 5)
                        metrics["volume_ratio_previous_5bars"] = ratio
                        if ratio >= 2:
                            signals.append({"rule": "volume_expansion", "metric": "volume_ratio_previous_5bars", "value": ratio, "threshold": 2})
                    if benchmark:
                        compared = store.get_bars(benchmark, interval, provider=provider, price_basis=basis, limit=120, as_of=cutoff)
                        aligned = {bar.timestamp: bar for bar in compared if bar.currency == currency}
                        window = records[-21:]
                        if all(bar.timestamp in aligned for bar in window):
                            benchmark_return = aligned[window[-1].timestamp].close / aligned[window[0].timestamp].close - 1
                            metrics["relative_return_20period"] = metrics["return_20period"] - benchmark_return
                            if abs(metrics["relative_return_20period"]) >= 0.05:
                                signals.append({"rule": "relative_strength_change", "benchmark": benchmark, "value": metrics["relative_return_20period"], "absolute_threshold": 0.05})
                        else:
                            missing.append("benchmark_matching_dates_currency_and_basis")
            candidates.append({"identity": symbol, "provider": source, "interval": interval_name(interval), "price_basis": basis, "currency": currency,
                "as_of": timestamps[-1], "observation_count": len(records), "status": "insufficient_evidence" if missing else "needs_investigation" if signals else "no_significant_signal",
                "missing": missing, "signals": signals, "metrics": metrics,
                "follow_up": "Check corporate actions/distributions, announcements and a competing explanation before any thesis",
                "return_meaning": "unit_NAV_price_return_not_total_return" if is_nav else "specified_basis_price_return"})
    return {"as_of": cutoff, "universe": universe, "requested_count": len(selected), "candidates": candidates,
            "metadata_without_price_count":universe["total_count"]-universe["price_covered_count"],
            "rules": {"minimum_observations":61,"price_5period":0.05,"price_20period":0.10,"volume_ratio":2,"relative_20period":0.05},
            "interpretation": "Research priority only; no probability, expected return or buy/sell decision"}


def financial_field_coverage(observations):
    primary=[];aligned=[];unverified=[];raw=[]
    for row in observations:
        if not isinstance(row.get('value'),dict):continue
        if row['dataset']=='financials_primary':
            value=row['value'];provenance=value.get('provenance',{})
            for field in value.get('fields',[]):
                semantic=field.get('semantic_verification',{})
                verified=(row.get('quality')=='primary_financial_fields_reviewed'
                          and provenance.get('review_matches_current_bytes') is True
                          and semantic.get('row_column_values_verified') is True
                          and semantic.get('period_and_scope_schema_verified') is True)
                primary.append({**field,'provider':row['provider'],'identity':row['identity'],
                    'period_start':value.get('period_start'),'period_end':value.get('period_end'),
                    'period_months':value.get('period_months'),'publication':row.get('publication'),
                    'state':'primary_row_column_verified' if verified else 'needs_semantic_row_review',
                    'usable':verified})
        elif row['dataset']=='financials_field_audit':
            for field in row['value'].get('rows',[]):
                aligned.append({**field,'provider':row['provider'],'period_end':row['as_of'],
                    'state':'numeric_alignment_only','raw_vendor_record_promoted':False})
            for name,item in row['value'].get('unverified_or_noncomparable',{}).items():
                unverified.append({'provider_field':name,'period_end':row['as_of'],**item})
        elif row['dataset']=='financials':
            raw.append({'provider':row['provider'],'as_of':row['as_of'],'quality':row.get('quality'),
                        'unit_state':row['value'].get('unit_state'),'whole_record_verified':False})
    return {'primary_fields':primary,'numeric_vendor_alignments':aligned,'unverified_or_noncomparable_vendor_fields':unverified,
            'raw_vendor_records':raw,'primary_fields_usable':sum(field['usable'] for field in primary),
            'scope':'Named fields and issuer periods only; numeric alignment does not verify all vendor definitions'}


def evidence_pack(store, identity, *, question="trend", interval="1d", provider=None, price_basis=None, window=120, as_of=None, point_in_time=False):
    cutoff = as_of or datetime.now(timezone.utc).isoformat()
    snapshot = store.snapshot(as_of=cutoff)
    quotes = store.get_quotes([identity],as_of=cutoff)
    bars = [asdict(row) for row in store.get_bars(identity, interval, provider=provider, price_basis=price_basis, limit=window, as_of=cutoff)]
    datasets = {"trend": ["fund_unit_nav", "fund_distribution_notice", "intraday_source_quality"],
                "flow": ["stock_order_size_flow_1m", "stock_order_size_flow_1d", "tick_order_size_summary", "transaction_aggregate_summary", "intraday_source_quality"],
                "valuation": ["cn_daily_valuation_liquidity", "financials", "financials_primary", "financials_field_audit", "announcement"],
                "fund": ["fund_unit_nav", "fund_profile_basics", "fund_product", "fund_holdings", "fund_distributions", "fund_distribution_notice", "fund_dealing_snapshot"],
                "allocation": ["fund_unit_nav", "fund_product", "macro_series", "financials", "financials_primary", "financials_field_audit", "announcement", "intraday_source_quality"]}[question]
    observations = []
    for dataset in datasets:
        observations.extend(store.get_observations(dataset, None if dataset == "macro_series" else identity, limit=window, as_of=cutoff))
    publication_gaps = []
    if point_in_time:
        usable = []
        for row in observations:
            publication = row.get("publication") or ""
            explicit_time = "T" in publication and datetime.fromisoformat(publication.replace("Z", "+00:00")).tzinfo is not None
            if explicit_time and parse_time(publication) <= parse_time(cutoff):
                usable.append(row)
            else:
                publication_gaps.append(f"publication_not_established:{row['dataset']}:{row['identity']}")
        observations = usable
        # Bar and quote schemas do not establish original publication times.
        if bars or quotes:
            publication_gaps.append("bar_or_quote_publication_not_established")
            bars, quotes = [], []
    financial_coverage=financial_field_coverage(observations)
    missing = list(dict.fromkeys(publication_gaps))
    present = {row["dataset"] for row in observations}
    if question == "trend":
        if not bars and "fund_unit_nav" not in present:
            missing.append("historical_prices")
        if max([len(bars), sum(row["dataset"] == "fund_unit_nav" for row in observations)]) < 61:
            missing.append("minimum_61_observations")
    elif question == "flow":
        if not {"stock_order_size_flow_1m", "stock_order_size_flow_1d", "transaction_aggregate_summary"} & present:
            missing.append("dated_vendor_flow")
        if not quotes:
            missing.append("matching_price_session")
        elif any(row["freshness"]["status"] != "current_session" for row in quotes):
            missing.append("current_price_session")
        flows = [row for row in observations if row["dataset"].startswith("stock_order_size_flow") or row["dataset"]=="transaction_aggregate_summary"]
        if any(row["dataset"]=="transaction_aggregate_summary" and row["value"].get("status")!="complete_supplier_window" for row in flows):
            missing.append("complete_supplier_aggregate_window")
        if quotes and flows and max(row["as_of"] for row in flows)[:10] != quotes[0]["as_of"][:10]:
            missing.append("flow_and_price_session_alignment")
    elif question == "valuation":
        if 'cn_daily_valuation_liquidity' not in present:missing.append('cn_daily_valuation_liquidity')
        if not {'financials','financials_primary'} & present:missing.append('financials')
        financials=[row for row in observations if row['dataset']=='financials']
        if not financial_coverage['primary_fields_usable'] and any(row['value'].get('unit_state')=='requires_primary_field_unit_verification' for row in financials):
            missing.append('financial_field_units_verification')
        elif 'financials_primary' in present and not financial_coverage['primary_fields_usable']:
            missing.append('primary_financial_semantic_row_review')
        if financial_coverage['primary_fields_usable']:
            valuations=[row for row in observations if row['dataset']=='cn_daily_valuation_liquidity']
            ttm={name for row in valuations for name in ('pe_ttm','ps_ttm','pcf_ncf_ttm')
                 if type(row['value'].get(name)) in (int,float) and math.isfinite(row['value'][name])}
            if ttm and any(field['usable'] and field.get('period_kind')=='flow_YTD' and field.get('period_months')!=12
                           for field in financial_coverage['primary_fields']):
                missing.append('valuation_TTM_denominator_reconciliation')
    elif question == "fund":
        for required in ("fund_unit_nav", "fund_product"):
            if required not in present:
                missing.append(required)
        products = [row for row in observations if row["dataset"] == "fund_product"]
        if products:
            product = products[-1]["value"]
            for field in product.get('fee_contract_missing',[]):missing.append('fee_contract:'+field)
            if product.get('field_conflicts'):missing.append('unresolved_product_field_conflicts')
            if product.get('unreviewed_documents'):missing.append('latest_document_fact_review')
            if product.get('subscription_currentness_verified') is False:missing.append('current_subscription_notice_audit')
            for field in ("fund_type", "share_class", "currency", "underlying_identity", "fee_terms", "dealing_rules", "subscription_status"):
                if product.get(field) in (None, "", "unknown"):
                    missing.append("product_field:" + field)
            if isinstance(product.get("dealing_rules"),dict):
                for field in ("opening_days","confirmation","redemption_payment"):
                    if product["dealing_rules"].get(field) in (None,"","unknown"):
                        missing.append("dealing_field:"+field)
            if product.get("fund_type")=="etf_link" and product.get("target_etf") in (None,"","unknown"):
                missing.append("verified_target_ETF_identity")
            if product.get("fund_type") in {"active_equity", "mixed", "bond", "fof"} and "fund_holdings" not in present:
                missing.append("dated_fund_holdings")
            underlying = product.get("underlying_identity")
            if underlying and underlying != "unknown" and not any(row["symbol"] == underlying for row in snapshot["latest_bars"] + snapshot["latest_quotes"]):
                missing.append("underlying_market_evidence:" + underlying)
    elif question == "allocation":
        if not bars and not quotes and "fund_unit_nav" not in present:
            missing.append("target_asset_price")
        if "macro_series" not in present:
            missing.append("task_matched_macro_rates_fx")
    if bars:
        if len({(row["provider"],row["price_basis"],row["currency"]) for row in bars}) > 1:
            missing.append("select_one_provider_basis_currency_for_analysis")
        if any(row["price_basis"] in {"unknown","legacy_unknown"} for row in bars):
            missing.append("verified_price_basis")
        if identity.startswith(("sh", "sz", "bj")):
            latest_bar = max(bars, key=lambda row: row["timestamp"])
            if expected_session(cutoff) is None or latest_bar["timestamp"][:10] != expected_session(cutoff):
                missing.append("current_exchange_session")
        if any(row["currency"] in {"", "unknown"} for row in bars):
            missing.append("verified_currency")
    navs = [row for row in observations if row["dataset"] == "fund_unit_nav"]
    if navs and any(row["currency"] in {"", "unknown"} for row in navs):
        missing.append("verified_NAV_currency")
    return {"identity": identity, "question": question, "as_of": cutoff, "status": "incomplete" if missing else "ready_for_research",
            "missing": sorted(set(missing)), "quotes": quotes, "bars": bars, "observations": observations,
            "financial_coverage":financial_coverage,
            "source_quality_context":[row for row in observations if row['dataset']=='intraday_source_quality'],
            "point_in_time_verified": point_in_time and bool(observations) and not publication_gaps,
            "interpretation": "Ready means sufficient for the named data question, not an investable thesis or product recommendation"}


def ledger_append(path, entry_path):
    entry = json.loads(Path(entry_path).read_text(encoding="utf-8-sig"))
    required = {"thesis_id","created_at","cutoff","scope","thesis","status","horizon","expected_observation","evidence_for","evidence_against","alternative","confirmation","invalidation","benchmark","action_relevance"}
    if any(key not in entry or entry[key] in (None, "") for key in required):
        raise ValueError("Complete thesis-ledger schema is required")
    parse_time(entry["created_at"])
    parse_time(entry["cutoff"])
    for field in ("created_at", "cutoff"):
        if datetime.fromisoformat(entry[field].replace("Z", "+00:00")).tzinfo is None:
            raise ValueError("Ledger timestamps require an explicit timezone")
    if entry["status"] not in {"active", "strengthened", "unchanged", "weakened", "invalidated", "not yet testable", "expired"}:
        raise ValueError("Use a thesis-ledger status")
    if entry["action_relevance"] not in {"none", "watch", "worth dedicated research", "portfolio review"}:
        raise ValueError("Use a thesis-ledger action relevance")
    if parse_time(entry["cutoff"]) > parse_time(entry["created_at"]):
        raise ValueError("cutoff cannot be later than created_at")
    target = Path(path).expanduser().resolve()
    existing = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines() if line.strip()] if target.exists() else []
    originals = [row for row in existing if row["thesis_id"] == entry["thesis_id"]]
    if originals:
        for field in ("thesis","horizon","benchmark","confirmation","invalidation","cutoff"):
            if entry[field] != originals[0][field]:
                raise ValueError("An update cannot rewrite original field: " + field)
    entry["recorded_at"] = datetime.now(timezone.utc).isoformat()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return {"file":str(target),"thesis_id":entry["thesis_id"],"event_number":len(originals)+1,"append_only":True}
