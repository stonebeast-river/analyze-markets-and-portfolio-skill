import json
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from market_core.models import Bar, Observation, Quote
from market_core.research import evidence_pack, ledger_append, screen
from market_core.sessions import quote_freshness
from market_core.store import MarketStore, SCHEMAS
from market_core.providers.mootdx_provider import MootdxProvider
from market_core.providers.tencent_history import TencentHistoryProvider
from market_core.http import DataSourceError, HttpClient
from market_core.providers.baostock_provider import BaoStockProvider
from market_core.providers.twelvedata import TwelveDataProvider


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = MarketStore(self.root / "test.sqlite3")

    def tearDown(self):
        self.temp.cleanup()

    def bars(self, value=10, count=70, basis="qfq", symbol="sh600519"):
        return [Bar("fixture",symbol,"1d",(date(2026,9,30)-timedelta(days=count-1-index)).isoformat(),value,value,value,value,
                    volume=100,price_basis=basis,currency="CNY") for index in range(count)]

    def test_quiet_market_has_no_manufactured_signal(self):
        self.store.upsert_bars(self.bars())
        result=screen(self.store,as_of="2026-10-05T20:00:00+08:00")
        self.assertEqual(result["candidates"][0]["status"],"no_significant_signal")
        self.assertFalse(result["universe"]["holdings_used"])

    def test_missing_history_downgrades(self):
        self.store.upsert_bars(self.bars(count=5))
        self.assertEqual(screen(self.store,as_of="2026-10-05T20:00:00+08:00")["candidates"][0]["status"],"insufficient_evidence")

    def test_screen_detects_move_without_issuing_trade(self):
        bars=self.bars()
        bars[-1].close=12
        self.store.upsert_bars(bars)
        row=screen(self.store,as_of="2026-10-05T20:00:00+08:00")["candidates"][0]
        self.assertEqual(row["status"],"needs_investigation")
        self.assertGreater(len(row["signals"]),0)

    def test_no_basis_mixing_in_screen_or_evidence(self):
        self.store.upsert_bars(self.bars(basis="qfq")+self.bars(value=100,basis="hfq"))
        self.assertEqual(len(screen(self.store,as_of="2026-10-05T20:00:00+08:00")["candidates"]),2)
        evidence=evidence_pack(self.store,"sh600519",as_of="2026-10-05T20:00:00+08:00")
        self.assertIn("select_one_provider_basis_currency_for_analysis",evidence["missing"])

    def test_nav_alone_cannot_select_fund(self):
        self.store.upsert_observations([Observation("fixture","fund_unit_nav","000051","2026-09-30",1.2)])
        result=evidence_pack(self.store,"000051",question="fund")
        self.assertEqual(result["status"],"incomplete")
        self.assertIn("fund_product",result["missing"])

    def test_historical_publication_is_required(self):
        self.store.upsert_observations([Observation("fixture","financials","sh600519","2026-06-30",{"profit":100},publication="2026-10-01T09:00:00+08:00")])
        result=evidence_pack(self.store,"sh600519",question="valuation",as_of="2026-09-30T20:00:00+08:00",point_in_time=True)
        self.assertEqual(result["observations"],[])
        self.assertFalse(result["point_in_time_verified"])

    def test_cutoff_uses_prior_eligible_row_same_day(self):
        self.store.upsert_quotes([Quote("fixture","sh600519",stamp,last=price) for stamp,price in (("2026-09-30T10:00:00+08:00",100),("2026-09-30T14:00:00+08:00",110))])
        self.assertEqual(self.store.snapshot(as_of="2026-09-30T11:00:00+08:00")["latest_quotes"][0]["last"],100)

    def test_holiday_close_and_read_time_staleness(self):
        quote={"as_of":"2026-09-30T15:00:00+08:00","quality":"provider_reported"}
        self.assertEqual(quote_freshness(quote,"2026-10-05T20:00:00+08:00")["status"],"current_session")
        self.assertEqual(quote_freshness(quote,"2026-10-08T10:00:00+08:00")["status"],"stale")
        self.assertEqual(quote_freshness(quote,"2027-01-04T10:00:00+08:00")["status"],"unknown")

    def test_legacy_migration_preserves_bars(self):
        path=self.root/"legacy.sqlite3"
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE bars("+SCHEMAS["bars"].replace(",price_basis)",")")+")")
            db.execute("INSERT INTO bars(provider,symbol,interval,timestamp,open,high,low,close,price_basis,quality,raw_json,collected_at) VALUES('fixture','sh600519','d','2026-09-30',10,10,10,10,'qfq','provider_reported','{}','2026-10-01')")
        db.close()
        migrated=MarketStore(path)
        self.assertEqual(migrated.get_bars("sh600519","1d",price_basis="qfq")[0].close,10)
        self.assertEqual(len(MarketStore(path).get_bars("sh600519","1d")),1)

    def test_append_ledger_rejects_rewriting_original(self):
        keys=("thesis_id","created_at","cutoff","scope","thesis","status","horizon","expected_observation","evidence_for","evidence_against","alternative","confirmation","invalidation","benchmark","action_relevance")
        entry={key:"documented" for key in keys}
        entry.update(thesis_id="test",created_at="2026-10-05T12:00:00+08:00",cutoff="2026-10-05T11:00:00+08:00",status="active",action_relevance="none")
        source=self.root/"entry.json"
        source.write_text(json.dumps(entry),encoding="utf-8")
        target=self.root/"ledger.jsonl"
        ledger_append(target,source)
        original=target.read_bytes()
        entry["thesis"]="hindsight revision"
        source.write_text(json.dumps(entry),encoding="utf-8")
        with self.assertRaises(ValueError): ledger_append(target,source)
        self.assertEqual(target.read_bytes(),original)

    def test_tdx_index_routing_is_explicit(self):
        calls=[]
        class Raw:
            def get_index_bars(self,*args):
                calls.append(args)
                return [{"datetime":"2026-09-30 15:00:00","open":100,"high":101,"low":99,"close":100,"vol":1}]
        class Client:
            client=Raw()
        with patch.object(MootdxProvider,"_client",return_value=Client()):
            rows=MootdxProvider().fetch_bars("sh000300",interval="5m",count=1)
        self.assertEqual(calls[0][1:3],(1,"000300"))
        self.assertTrue(rows[0].raw["index_api"])

    def test_missing_adjusted_history_never_becomes_raw(self):
        client=HttpClient()
        with patch.object(client,"get_json",return_value=({"data":{"sh600519":{"day":[["2026-09-30","10","10","10","10","100"]]}}},"https://example.test/history")):
            with self.assertRaises(DataSourceError):
                TencentHistoryProvider(client).fetch_bars("sh600519",start_date="2026-09-01",end_date="2026-09-30",adjustment="qfq")

    def test_missing_key_profile_is_nonzero(self):
        import market_engine
        from market_core.pipeline import DEFAULT_CONFIG
        config=json.loads(json.dumps(DEFAULT_CONFIG))
        config["profiles"]["allocation"].update(cn_benchmarks=[],cn_sector_indices=[],board_types=[],fund_codes=[],global_symbols=["SPY"],fred_series=[])
        config["providers"]["twelve_data"]["source"]="api"
        path=self.root/"config.json"
        path.write_text(json.dumps(config),encoding="utf-8")
        with patch.dict("os.environ",{"TWELVE_DATA_API_KEY":""}),patch.object(market_engine,"_json"):
            self.assertEqual(market_engine.main(["run","--config",str(path),"--profile","allocation"]),2)

    def test_baostock_retains_actual_index_basis(self):
        from types import SimpleNamespace
        class Result:
            error_code="0"
            fields="date,code,open,high,low,close,volume,amount,adjustflag".split(",")
            def __init__(self): self.count=0
            def next(self):
                self.count+=1
                return self.count==1
            def get_row_data(self): return ["2026-09-30","sh.000300","10","11","9","10","100","1000","3"]
        module=SimpleNamespace(login=lambda:SimpleNamespace(error_code="0"),logout=lambda:None,query_history_k_data_plus=lambda *a,**k:Result())
        with patch.dict("sys.modules",{"baostock":module}):
            rows=BaoStockProvider().fetch_bars("sh000300",start_date="2026-09-01",end_date="2026-09-30",adjustment="qfq")
            self.assertEqual(rows[0].price_basis,"unadjusted")
            with self.assertRaises(DataSourceError):
                BaoStockProvider().fetch_bars("sh600519",start_date="2026-09-01",end_date="2026-09-30",adjustment="qfq")

    def test_diagnostics_do_not_change_database(self):
        self.store.upsert_bars(self.bars())
        path=self.root/"test.sqlite3"
        before=path.read_bytes()
        reader=MarketStore(path,read_only=True)
        reader.health()
        reader.snapshot()
        screen(reader,as_of="2026-10-05T20:00:00+08:00")
        self.assertEqual(path.read_bytes(),before)

    def test_date_only_publication_is_not_point_in_time(self):
        self.store.upsert_observations([Observation("fixture","financials","sh600519","2026-06-30",{"profit":100},publication="2026-09-30")])
        result=evidence_pack(self.store,"sh600519",question="valuation",as_of="2026-09-30T12:00:00+08:00",point_in_time=True)
        self.assertEqual(result["observations"],[])
        self.assertFalse(result["point_in_time_verified"])

    def test_global_intraday_timestamp_has_UTC_identity(self):
        client=HttpClient()
        payload={"meta":{"currency":"USD"},"values":[{"datetime":"2026-09-30 14:00:00","open":"10","high":"11","low":"9","close":"10","volume":"100"}]}
        with patch.object(client,"get_json",return_value=(payload,"https://example.test/")):
            rows=TwelveDataProvider("fixture_key",client).fetch_time_series(["SPY"],interval="5min")
        self.assertEqual(rows[0].timestamp,"2026-09-30T14:00:00+00:00")

    def test_known_future_publication_excluded_from_current_snapshot(self):
        self.store.upsert_observations([Observation("fixture","financials","sh600519","2026-06-30",{"profit":100},publication="2026-10-06T09:00:00+08:00")])
        self.assertEqual(self.store.snapshot(as_of="2026-10-05T12:00:00+08:00")["recent_observations"],[])
        self.assertEqual(self.store.get_observations("financials",as_of="2026-10-05T12:00:00+08:00"),[])

    def test_valuation_does_not_accept_financial_units_merely_by_presence(self):
        self.store.upsert_observations([Observation('fixture','financials','sh600519','2026-06-30',{'unit_state':'requires_primary_field_unit_verification'},publication='2026-08-15'),
            Observation('fixture','cn_daily_valuation_liquidity','sh600519','2026-09-30',{'pe_ttm':20})])
        result=evidence_pack(self.store,'sh600519',question='valuation',as_of='2026-10-05T12:00:00+08:00')
        self.assertEqual(result['status'],'incomplete')
        self.assertIn('financial_field_units_verification',result['missing'])


if __name__=="__main__": unittest.main(verbosity=2)
