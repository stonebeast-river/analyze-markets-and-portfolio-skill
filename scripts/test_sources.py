import gzip
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from market_core.http import HttpClient,DataSourceError
from market_core.models import Observation
from market_core.parsing import assigned_json
from market_core.providers.fred_csv import FredCsvProvider
from market_core.providers.fund_catalog import FundCatalogProvider
from market_core.providers.tencent_intraday import TencentIntradayProvider
from market_core.providers.yahoo import YahooProvider
from market_core.providers.fund_documents import FundDocumentProvider
from market_core.market_scan import scan_market
from market_core.models import Quote
from market_core.research import discover
from market_core.store import MarketStore
from market_core.symbols import is_cn_index,normalize_cn_symbol


class SourceTests(unittest.TestCase):
    def test_assigned_data_does_not_execute_or_accept_extra_script(self):
        self.assertEqual(assigned_json('var r = [["000051"]];','r'),[["000051"]])
        with self.assertRaises(ValueError): assigned_json('var r = []; sendCredentials();','r')

    def test_catalogue_is_not_asserted_to_be_active_funds(self):
        client=HttpClient()
        with patch.object(client,'get_text',return_value=('var r = [["000051","HX","华夏A","指数型","HX"]];','https://example.test/catalog')):
            rows=FundCatalogProvider(client).fetch_universe()
        self.assertEqual(rows[0].value['active_status'],'unknown')
        self.assertFalse(rows[-1].value['active_investable_universe_verified'])

    def test_fred_public_download_retains_units_and_missing_publication(self):
        client=HttpClient()
        responses=[('<p>Units:</p><p>Percent, Not Seasonally Adjusted</p><p>Frequency:</p><p>Daily</p>','https://fred.stlouisfed.org/series/DGS2'),('observation_date,DGS2\n2026-09-30,4.88\n2026-10-01,\n','https://fred.stlouisfed.org/graph/fredgraph.csv')]
        with patch.object(client,'get_text',side_effect=responses): rows=FredCsvProvider(client).fetch_series(['DGS2'])
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0].value,4.88)
        self.assertIn('Percent',rows[0].unit)
        self.assertEqual(rows[0].publication,'')
        self.assertFalse(rows[0].raw['vintage_verified'])

    def test_dated_aggregate_rejects_another_day(self):
        client=HttpClient()
        with patch.object(client,'get_text',return_value=('v_detail_time_sh600519=[20260930,"09:25:01~09:33:25"]','https://example.test')):
            with self.assertRaises(DataSourceError): TencentIntradayProvider(client).fetch_transactions('600519',date='2026-09-29')

    def test_aggregate_window_and_amount_are_not_individual_orders(self):
        client=HttpClient()
        responses=[('v_detail_time_sh600519=[20260930,"09:25:01~09:33:25"]','https://example.test/property'),('v_detail_data_sh600519=[0,"0/09:25:01/100/1/10/101000/B"]','https://example.test/page')]
        with patch.object(client,'get_text',side_effect=responses): rows=TencentIntradayProvider(client).fetch_transactions('600519',date='2026-09-30')
        self.assertEqual(rows[-1].value['buy_amount'],101000)
        self.assertFalse(rows[-1].value['individual_order_verified'])
        self.assertEqual(rows[-1].value['status'],'complete_supplier_window')

    def test_global_incomplete_daily_bar_is_excluded(self):
        client=HttpClient()
        payload={'chart':{'result':[{'meta':{'symbol':'SPY','currency':'USD','exchangeTimezoneName':'UTC','instrumentType':'ETF','currentTradingPeriod':{'regular':{'start':1791190800,'end':1791214200}}},'timestamp':[1790931600,1791190800], 'indicators':{'quote':[{'open':[10,11],'high':[11,12],'low':[9,10],'close':[10,11],'volume':[100,100]}],'adjclose':[{'adjclose':[9.9,10.9]}]}}]}}
        with patch.object(client,'get_json',return_value=(payload,'https://example.test/chart')):
            bars,observations=YahooProvider(client).fetch_evidence(['SPY'],as_of='2026-10-05T14:00:00+00:00')
        self.assertEqual(len(bars),1)
        self.assertEqual(observations[0].price_basis,'provider_dividend_split_adjusted_close')

    def test_historical_cutoff_uses_its_own_exchange_close_not_current_meta(self):
        unix=lambda x:int(datetime.fromisoformat(x).timestamp())
        client=HttpClient()
        payload={'chart':{'result':[{'meta':{'symbol':'XLK','currency':'USD','exchangeTimezoneName':'America/New_York','instrumentType':'ETF',
            'currentTradingPeriod':{'regular':{'start':unix('2026-10-06T13:30:00+00:00'),'end':unix('2026-10-06T20:00:00+00:00')}}},
            'timestamp':[unix('2026-10-02T13:30:00+00:00'),unix('2026-10-05T13:30:00+00:00')],
            'indicators':{'quote':[{'open':[100,100],'high':[102,102],'low':[99,99],'close':[101,101],'volume':[1,1]}]},
            'events':{'dividends':{'future':{'date':unix('2026-10-06T13:30:00+00:00'),'amount':1}}}}]}}
        with patch.object(client,'get_json',return_value=(payload,'https://example.test/chart')):
            bars,observations=YahooProvider(client).fetch_evidence(['XLK'],as_of='2026-10-05T15:00:00+00:00')
        self.assertEqual([r.timestamp for r in bars],['2026-10-02'])
        self.assertEqual(observations,[])
        self.assertEqual(bars[0].session,'completed_regular_session')
        self.assertTrue(bars[0].raw['completion_calendar_covered'])

    def test_US_early_close_and_unknown_instrument_completion(self):
        unix=lambda x:int(datetime.fromisoformat(x).timestamp())
        client=HttpClient()
        meta={'symbol':'XLK','currency':'USD','exchangeTimezoneName':'America/New_York','instrumentType':'ETF'}
        payload={'chart':{'result':[{'meta':meta,'timestamp':[unix('2026-11-27T14:30:00+00:00')],
            'indicators':{'quote':[{'open':[100],'high':[102],'low':[99],'close':[101],'volume':[1]}]}}]}}
        with patch.object(client,'get_json',return_value=(payload,'https://example.test/chart')):
            bars,_=YahooProvider(client).fetch_evidence(['XLK'],as_of='2026-11-27T19:00:00+00:00')
            self.assertEqual(bars[0].session,'completed_regular_session')
            with self.assertRaises(DataSourceError):
                YahooProvider(client).fetch_evidence(['XLK'],as_of='2026-11-27T17:00:00+00:00')
            meta['instrumentType']='FUTURE'
            bars,_=YahooProvider(client).fetch_evidence(['XLK'],as_of='2026-11-27T19:00:00+00:00')
        self.assertEqual(bars[0].session,'completion_unverified')
        self.assertFalse(bars[0].raw['completion_calendar_covered'])

    def test_catalogue_does_not_expand_agent_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            store=MarketStore(Path(directory)/'test.sqlite3')
            store.upsert_observations([Observation('fixture','instrument_listing',f'{index:06d}','2026-09-30',{'scope':'funds'}) for index in range(300)])
            self.assertEqual(store.snapshot()['recent_observations'],[])
            universe=discover(store,limit=10)
            self.assertEqual(universe['total_count'],300)
            self.assertTrue(universe['truncated'])
            self.assertEqual(universe['covered_count'],0)

    def test_receipts_preserve_prior_values_after_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            store=MarketStore(Path(directory)/'test.sqlite3')
            store.upsert_observations([Observation('fixture','macro_series','rate','2026-09-30',1)])
            store.upsert_observations([Observation('fixture','macro_series','rate','2026-09-30',2)])
            receipts=list((Path(directory)/'receipts'/'observations').glob('*.gz'))
            values={json.loads(gzip.decompress(path.read_bytes()))['rows'][0]['value_json'] for path in receipts}
            self.assertEqual(values,{'1','2'})

    def test_csi_930_index_is_not_routed_as_stock(self):
        self.assertTrue(is_cn_index('sh930713'))
        with self.assertRaises(ValueError): normalize_cn_symbol('sh930713',stock_only=True)

    def test_fx_direction_must_match_official_units(self):
        client=HttpClient()
        with patch.object(client,'get_text',return_value=('<p>Units:</p><p>U.S. Dollars to One Euro</p><p>Frequency:</p><p>Daily</p>','https://fred.stlouisfed.org/series/DEXCHUS')):
            with self.assertRaises(DataSourceError):FredCsvProvider(client).fetch_series(['DEXCHUS'])

    def test_document_change_invalidates_previously_reviewed_facts(self):
        from types import SimpleNamespace
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            old=b'%PDF-original';new=b'%PDF-changed'
            registry={'funds':{'040046':{'name':'fixture','manager':'issuer','registry_verified_at':'2026-10-05','issuer_document_hosts':['example.test'],
                'documents':[{'kind':'prospectus','url':'https://example.test/file.pdf','publication_date':'2026-09-18','reviewed_facts':{'sha256':hashlib.sha256(old).hexdigest(),'facts':{'fee':0.01}}}]}}}
            path=root/'registry.json';path.write_text(json.dumps(registry),encoding='utf-8')
            client=HttpClient()
            with patch.object(client,'get_bytes',return_value=(new,'https://example.test/file.pdf')),patch('pypdf.PdfReader',return_value=SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda:'基金代码040046')])):
                rows=FundDocumentProvider(path,root/'docs',client).fetch_evidence('040046')
            self.assertTrue(rows[0].value['review_required'])
            self.assertEqual(rows[0].value['reviewed_facts'],{})

    def test_sector_breadth_reports_taxonomy_and_measured_members(self):
        with tempfile.TemporaryDirectory() as directory:
            store=MarketStore(Path(directory)/'test.sqlite3')
            store.upsert_quotes([Quote('fixture','sh600519','2026-09-30T15:00:00+08:00',asset_class='equity',last=11,previous_close=10)])
            store.upsert_observations([Observation('fixture','industry_classification','sh600519','2026-09-30',{'classification':'fixture_taxonomy','industry':'industry_A'})])
            result=scan_market(store,as_of='2026-10-05T12:00:00+08:00')
            self.assertEqual(result['industry_mapping_coverage'],1)
            self.assertEqual(result['industry_breadth'][0]['classification'],'fixture_taxonomy')
            self.assertEqual(result['industry_breadth'][0]['observed_members'],1)


if __name__=='__main__': unittest.main(verbosity=2)
