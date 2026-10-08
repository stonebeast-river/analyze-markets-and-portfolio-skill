"""Public minute bars and dated supplier transaction aggregates, without JavaScript execution."""
from datetime import datetime
import math

from ..conventions import SHANGHAI
from ..http import DataSourceError, HttpClient
from ..models import Bar, Observation
from ..parsing import assigned_json
from ..symbols import normalize_cn_symbol
from ..task_health import cash_calendar


def aggregate_clock_audit(rows):
    calendar=cash_calendar('CN_CASH')
    after=[row for row in rows if row.as_of[11:19]>calendar['close']+':00']
    return {'provider_record_time_semantics':'unverified_execution_or_reporting_time',
            'cash_calendar':'CN_CASH','cash_close':calendar['close'],
            'after_cash_close_records':len(after),'after_cash_close_amount_CNY':sum(row.value['amount'] for row in after),
            'execution_time_verified':False,
            'interpretation':'All supplier rows retained; off-clock records cannot be labeled continuous-session execution'}


class TencentIntradayProvider:
    name = "tencent_public_intraday"

    def __init__(self, client=None):
        self.client = client or HttpClient(user_agent="Mozilla/5.0",timeout=10,retries=1,
            min_interval_by_host={"proxy.finance.qq.com":0.5,"stock.gtimg.cn":0.2,"web.ifzq.gtimg.cn":0.5})

    def fetch_bars(self, symbol, *, interval="5m", count=240):
        if interval not in {"1m","5m","15m","30m","60m"} or not 1 <= count <= 640:
            raise ValueError("Use a supported minute interval and bounded count")
        identity = normalize_cn_symbol(symbol)
        period = "m" + interval[:-1]
        errors, body, source = [], None, ""
        for base in ("https://proxy.finance.qq.com/ifzqgtimg/appstock/app/kline/mkline",
                     "https://web.ifzq.gtimg.cn/appstock/app/kline/mkline"):
            try:
                payload, source = self.client.get_json(base,params={"param":f"{identity},{period},,{count}"},headers={"Referer":"https://gu.qq.com/"})
                body = (payload.get("data") or {}).get(identity) or {}
                if body.get(period): break
                raise DataSourceError("No matching minute data")
            except Exception as exc:
                errors.append(str(exc))
                body = None
        if body is None: raise DataSourceError("Tencent minute endpoints unavailable: " + " | ".join(errors))
        rows = []
        for record in body[period]:
            if len(record) < 6: raise DataSourceError("Malformed Tencent minute bar")
            stamp = datetime.strptime(record[0],"%Y%m%d%H%M").replace(tzinfo=SHANGHAI)
            if stamp>datetime.now(SHANGHAI): continue
            rows.append(Bar(self.name,identity,interval,stamp.isoformat(),float(record[1]),float(record[3]),float(record[4]),float(record[2]),
                volume=float(record[5]),amount=None,volume_unit="provider_native_lot",currency="CNY",price_basis="unadjusted",
                source_url=source,quality="provider_reported",session="provider_bar_end",
                raw={"row":record,"amount_available":False,"time_semantics":"bar_end","coverage":"bounded_recent_window",
                     "quote_timestamp":((body.get("qt") or {}).get(identity) or [None]*31)[30]}))
        return self.client.bind_rows(rows)

    def fetch_transactions(self, symbol, *, date=None, max_pages=64):
        identity = normalize_cn_symbol(symbol,stock_only=True)
        if not 1 <= max_pages <= 200: raise ValueError("Use a bounded page limit")
        endpoint = "https://stock.gtimg.cn/data/index.php"
        properties, property_source = self.client.get_text(endpoint,params={"appn":"detail","action":"property","c":identity},encoding="gbk")
        property_receipts = self.client.source_receipts()
        all_receipts = list(property_receipts)
        metadata = assigned_json(properties,"v_detail_time_" + identity)
        if not isinstance(metadata,list) or len(metadata)!=2: raise DataSourceError("Invalid dated transaction metadata")
        source_date = datetime.strptime(str(metadata[0]),"%Y%m%d").date().isoformat()
        if date and date != source_date: raise DataSourceError("Requested date does not match the supplier's dated transaction window")
        windows = str(metadata[1]).split("|") if metadata[1] else []
        if not windows: raise DataSourceError("Supplier has no transaction pages")
        rows, received, error, ids = [], 0, "", set()
        for page in range(min(max_pages,len(windows))):
            row_start = len(rows)
            try:
                content, source = self.client.get_text(endpoint,params={"appn":"detail","action":"data","c":identity,"p":page},encoding="gbk")
                page_receipts = self.client.source_receipts()
                value = assigned_json(content,"v_detail_data_" + identity)
                if not isinstance(value,list) or len(value)!=2 or value[0]!=page: raise DataSourceError("Unexpected transaction page identity")
                records = str(value[1]).split("|") if value[1] else []
                if not records: raise DataSourceError("Empty transaction page")
                for record in records:
                    fields = record.split("/")
                    if len(fields)!=7: raise DataSourceError("Malformed aggregate transaction record")
                    sequence, clock, price, change, volume, amount, direction = fields
                    if sequence in ids: raise DataSourceError("Duplicate supplier sequence across pages")
                    ids.add(sequence)
                    observed = f"{source_date}T{clock}+08:00"
                    datetime.fromisoformat(observed)
                    rows.append(Observation(self.name,"transaction_aggregate",identity+"#"+sequence,observed,
                        {"symbol":identity,"price":float(price),"price_change":float(change),"volume":float(volume),
                         "amount":float(amount),"amount_unit":"CNY","volume_unit":"provider_native_lot",
                         "direction":{"B":"provider_buy","S":"provider_sell","M":"provider_neutral"}.get(direction,"unknown"),
                         "record_type":"supplier_aggregate_not_individual_order"},
                        unit="CNY_and_provider_native_lot",currency="CNY",quality="provider_classified_aggregate",
                        latency="supplier_latest_dated_window",source_url=source,
                        raw={"row":fields,"page":page,"source_date":source_date,"source_window":windows[page],
                             'as_of_meaning':'supplier_record_clock_not_verified_execution_or_publication_time',
                             "individual_order_verified":False,"lot_size_verified":False}))
                self.client.bind_rows(rows[row_start:], property_receipts + page_receipts)
                all_receipts.extend(page_receipts)
                received += 1
            except Exception as exc:
                del rows[row_start:]
                receipt=self.client.last_response_receipt
                if self.client.archive and receipt and receipt.get('status') in {'http_ok','cache_hit'}:
                    self.client.archive.reject(receipt,'Supplier aggregate page failed parsing or identity validation')
                error=str(exc)
                break
        if not rows: raise DataSourceError("No usable aggregate transactions: " + error)
        complete = received == len(windows) and not error
        totals={"buy_amount":0.0,"sell_amount":0.0,"neutral_amount":0.0,"unknown_amount":0.0,"large_aggregate_buy_amount":0.0,"large_aggregate_sell_amount":0.0}
        for row in rows:
            if not all(math.isfinite(row.value[field]) and row.value[field]>=0 for field in ("price","volume","amount")):
                raise DataSourceError("Non-finite or negative transaction aggregate")
            side = "buy" if row.value["direction"]=="provider_buy" else "sell" if row.value["direction"]=="provider_sell" else "neutral" if row.value["direction"]=="provider_neutral" else "unknown"
            totals[side+"_amount"] += row.value["amount"]
            if side in {"buy","sell"} and row.value["amount"] >= 200000:
                totals["large_aggregate_"+side+"_amount"] += row.value["amount"]
        complete=complete and totals["unknown_amount"]==0
        totals.update(net_amount=totals["buy_amount"]-totals["sell_amount"],expected_pages=len(windows),received_pages=received,
            records=len(rows),status="complete_supplier_window" if complete else "partial",error=error,
            order_size_threshold_CNY=200000,individual_order_verified=False,
            coverage="supplier_aggregate_pages_not_exchange_level_2")
        totals['clock_audit']=aggregate_clock_audit(rows)
        rows.append(Observation(self.name,"transaction_aggregate_summary",identity,max(row.as_of for row in rows),totals,
            unit="CNY_and_coverage_counts",currency="CNY",source_url=property_source,
            quality="locally_derived_from_supplier_aggregates",latency="supplier_latest_dated_window"))
        self.client.bind_rows(rows[-1:], all_receipts)
        return rows
