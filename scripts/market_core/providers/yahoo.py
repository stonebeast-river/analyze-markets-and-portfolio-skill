"""Keyless public Yahoo chart data with explicit provider adjustment and corporate events."""
import math
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

from ..http import DataSourceError, HttpClient
from ..models import Bar, Observation
from ..task_health import completed_cash_session


class YahooProvider:
    name = "yahoo_public_chart"

    def __init__(self, client=None):
        self.client = client or HttpClient(user_agent="Mozilla/5.0",timeout=12,retries=1,
                                         min_interval_by_host={"query1.finance.yahoo.com":0.6,"query2.finance.yahoo.com":0.6})

    def fetch_evidence(self, symbols, *, lookback_days=450, interval="1d", as_of=None):
        end = datetime.fromisoformat(as_of.replace("Z","+00:00")) if as_of else datetime.now(timezone.utc)
        if end.tzinfo is None: raise ValueError("as_of requires a timezone")
        start = end - timedelta(days=lookback_days)
        bars, observations = [], []
        for identity in symbols:
            bar_start, observation_start = len(bars), len(observations)
            errors, result, source = [], None, ""
            for host in ("query1.finance.yahoo.com","query2.finance.yahoo.com"):
                try:
                    payload, source = self.client.get_json(f"https://{host}/v8/finance/chart/{quote(identity,safe='')}",
                        params={"period1":int(start.timestamp()),"period2":int(end.timestamp()),"interval":interval,"events":"div,splits","includeAdjustedClose":"true"})
                    chart = payload.get("chart") or {}
                    if chart.get("error"): raise DataSourceError(str(chart["error"]))
                    result = (chart.get("result") or [None])[0]
                    if not result or not result.get("timestamp"): raise DataSourceError("Empty Yahoo time series")
                    break
                except Exception as exc: errors.append(str(exc))
            if result is None: raise DataSourceError("Yahoo sources unavailable: " + " | ".join(errors))
            meta = result.get("meta") or {}
            if str(meta.get("symbol","")).upper() != identity.upper(): raise DataSourceError("Yahoo returned a different instrument")
            currency = meta.get("currency")
            zone_name = meta.get("exchangeTimezoneName")
            if not currency or not zone_name: raise DataSourceError("Yahoo currency/timezone metadata missing")
            try: zone = ZoneInfo(zone_name)
            except Exception as exc: raise DataSourceError("Install tzdata for the source exchange timezone") from exc
            values = (result.get("indicators",{}).get("quote") or [{}])[0]
            adjusted = (result.get("indicators",{}).get("adjclose") or [{}])[0].get("adjclose") or []
            regular = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
            kind=meta.get('instrumentType')
            market=None
            cash_index=identity in {'^HSI','^GSPC','^IXIC','^NDX','^RUT','^DJI','^N225'} or identity.endswith(('.SS','.SZ'))
            if kind in {'ETF','EQUITY'} or (kind=='INDEX' and cash_index):
                market={'America/New_York':'US_CASH','Asia/Hong_Kong':'HK_CASH',
                        'Asia/Shanghai':'CN_CASH','Asia/Tokyo':'JP_CASH'}.get(zone_name)
            completed=completed_cash_session(market,end.isoformat()) if market else None
            usable = 0
            for index, stamp in enumerate(result["timestamp"]):
                if stamp > end.timestamp(): continue
                source_time = datetime.fromtimestamp(stamp,timezone.utc)
                source_day=source_time.astimezone(zone).date().isoformat()
                if interval=='1d' and completed and source_day>completed:continue
                if interval == "1d" and regular.get("start", float("inf")) <= stamp and end.timestamp() < regular.get("end",0):
                    continue  # Do not calculate completed daily indicators from an unfinished session.
                try:
                    prices = [float(values[field][index]) for field in ("open","high","low","close")]
                except (KeyError,IndexError,TypeError,ValueError): continue
                if not all(math.isfinite(value) and value > 0 for value in prices): continue
                if prices[1] < max(prices[0],prices[3]) or prices[2] > min(prices[0],prices[3]):
                    raise DataSourceError("Yahoo OHLC bounds are inconsistent")
                observed = source_time.astimezone(zone).date().isoformat() if interval == "1d" else source_time.isoformat()
                volume = values.get("volume",[])
                volume = volume[index] if index < len(volume) else None
                usable += 1
                bars.append(Bar(self.name,identity,interval,observed,*prices,
                    volume=float(volume) if volume is not None else None,
                    volume_unit="share" if meta.get("instrumentType") in {"ETF","EQUITY"} else "provider_native",
                    currency=currency,price_basis="provider_split_adjusted_close",quality="provider_reported",
                    session=("completed_regular_session" if completed else "completion_unverified") if interval == "1d" else "provider_bar",
                    source_url=source,
                    raw={"source_timestamp_utc":source_time.isoformat(),"exchange_timezone":zone_name,
                         "instrument_type":kind,"metadata":meta,"publication_known":False,
                         "completion_calendar":market,"completion_calendar_covered":completed is not None,
                         "expected_completed_session":completed}))
                if index < len(adjusted) and adjusted[index] is not None:
                    adjusted_value = float(adjusted[index])
                    if math.isfinite(adjusted_value) and adjusted_value > 0:
                        observations.append(Observation(self.name,"global_adjusted_close",identity,observed,adjusted_value,
                            unit=f"{currency}_per_unit",currency=currency,price_basis="provider_dividend_split_adjusted_close",
                            quality="provider_derived_adjustment",source_url=source,latency="end_of_day",
                            raw={"close":prices[3],"source_timestamp_utc":source_time.isoformat(),"method_source":"https://in.help.yahoo.com/kb/adjusted-close-sln28256.html"}))
            if not usable: raise DataSourceError("No completed usable Yahoo bars")
            for event_type, events in (result.get("events") or {}).items():
                for event_id, event in events.items():
                    if event['date']>end.timestamp():continue
                    source_time=datetime.fromtimestamp(event["date"],timezone.utc)
                    observations.append(Observation(self.name,"corporate_action",identity+"#"+event_type+"#"+event_id,
                        source_time.astimezone(zone).date().isoformat(),{"identity":identity,"type":event_type,**event},
                        unit="provider_event",currency=currency,quality="provider_reported",source_url=source))
            self.client.bind_rows(bars[bar_start:] + observations[observation_start:])
        return bars, observations

    def fetch_time_series(self, symbols, *, lookback_days=450, interval="1d"):
        return self.fetch_evidence(symbols,lookback_days=lookback_days,interval=interval)[0]
