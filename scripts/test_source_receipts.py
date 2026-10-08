import gzip
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from market_core.http import HttpClient
from market_core.models import Bar, Observation
from market_core.providers.tencent_history import TencentHistoryProvider
from market_core.providers.tencent_intraday import TencentIntradayProvider,aggregate_clock_audit
from market_core.providers.fred_csv import FredCsvProvider
from market_core.responses import ResponseVault
from market_core.store import MarketStore


class Reply(io.BytesIO):
    def __init__(self, data, url):
        super().__init__(data); self.headers = {}; self.status = 200; self.url = url

    def geturl(self):
        return self.url


class SourceReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.vault = ResponseVault(self.root / 'responses')
        self.client = HttpClient(retries=0, archive=self.vault)
        self.store = MarketStore(self.root / 'store.sqlite3')

    def tearDown(self):
        self.temp.cleanup()

    def history(self, identity, close):
        payload = json.dumps({'data': {identity: {'day': [['2026-09-30', str(close), str(close), str(close+1), str(close-1), '100']]}}}).encode()
        with patch('urllib.request.urlopen',return_value=Reply(payload,'https://example.test/'+identity)):
            return TencentHistoryProvider(self.client).fetch_bars(identity, start_date='2026-09-01', end_date='2026-09-30', adjustment='none')

    def test_each_symbol_keeps_its_consumed_response_after_later_request(self):
        first = self.history('sh000300',100); second = self.history('sh000905',200)
        self.assertNotEqual(first[0].source_receipts[0]['receipt_sha256'],second[0].source_receipts[0]['receipt_sha256'])
        self.store.upsert_bars(first+second)
        loaded = self.store.get_bars('sh000300','1d')[0]
        self.assertEqual(loaded.source_receipts,first[0].source_receipts)
        trace = MarketStore(self.store.path,read_only=True).source_trace('bar','sh000300')
        self.assertEqual(trace['status'],'verified')
        self.assertEqual(trace['rows'][0]['responses'][0]['final_url'],'https://example.test/sh000300')

    def test_unit_metadata_and_csv_are_both_bound_to_the_correct_series(self):
        html=b'<p>Units:</p><p>Percent</p><p>Frequency:</p><p>Daily</p>'
        replies=[Reply(html,'https://example.test/DGS2-metadata'),Reply(b'observation_date,DGS2\n2026-09-30,4.2\n','https://example.test/DGS2-csv'),
                 Reply(html,'https://example.test/DGS10-metadata'),Reply(b'observation_date,DGS10\n2026-09-30,5.2\n','https://example.test/DGS10-csv')]
        with patch('urllib.request.urlopen',side_effect=replies):
            rows=FredCsvProvider(self.client).fetch_series(['DGS2','DGS10'])
        self.assertEqual([len(row.source_receipts) for row in rows],[2,2])
        self.assertFalse(set(ref['receipt_sha256'] for ref in rows[0].source_receipts) &
                         set(ref['receipt_sha256'] for ref in rows[1].source_receipts))
        self.store.upsert_observations(rows)
        self.assertEqual(self.store.source_trace('observation','DGS10',dataset='macro_series')['status'],'verified')

    def test_metadata_mutation_blocks_write_before_any_normalized_receipt(self):
        rows=self.history('sh000300',100)
        ref=rows[0].source_receipts[0]; path=self.vault.directory/ref['receipt_path']
        payload=json.loads(path.read_bytes()); payload['received_at']='2030-01-01T00:00:00+00:00'
        path.write_text(json.dumps(payload),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'metadata hash'):
            self.store.upsert_bars(rows)
        self.assertEqual(self.store.get_bars('sh000300','1d'),[])
        self.assertFalse((self.root/'receipts/bars').exists())

    def test_archived_byte_mutation_is_reported_instead_of_green_trace(self):
        rows=self.history('sh000300',100); self.store.upsert_bars(rows)
        ref=rows[0].source_receipts[0]
        receipt=json.loads((self.vault.directory/ref['receipt_path']).read_bytes())
        (self.vault.directory/receipt['decoded']['path']).write_bytes(gzip.compress(b'modified bytes'))
        trace=self.store.source_trace('bar','sh000300')
        self.assertEqual(trace['status'],'invalid')
        self.assertEqual(trace['rows'][0]['status'],'invalid_original_response')

    def test_cached_row_keeps_original_receipt_time_and_hash(self):
        first=self.history('sh000300',100)
        self.client.cache_ttl_by_host={'web.ifzq.gtimg.cn':300}
        with patch('urllib.request.urlopen') as network:
            second=TencentHistoryProvider(self.client).fetch_bars('sh000300',start_date='2026-09-01',end_date='2026-09-30',adjustment='none')
        network.assert_not_called()
        self.assertEqual(first[0].source_receipts[0]['received_at'],second[0].source_receipts[0]['received_at'])
        self.assertEqual(first[0].source_receipts[0]['receipt_sha256'],second[0].source_receipts[0]['receipt_sha256'])
        self.assertEqual(second[0].source_receipts[0]['transport'],'cache')

    def test_unlinked_legacy_or_tcp_rows_are_not_retroactively_verified(self):
        self.store.upsert_bars([Bar('tcp_fixture','sh000300','1d','2026-09-30',100,101,99,100)])
        trace=self.store.source_trace('bar','sh000300')
        self.assertEqual(trace['status'],'partial')
        self.assertEqual(trace['rows'][0]['status'],'normalized_receipt_only')
        self.assertFalse(trace['historical_links_inferred'])

    def test_schema_migration_retains_old_rows_with_empty_not_inferred_links(self):
        self.store.upsert_observations([Observation('fixture','macro_series','DGS2','2026-09-30',4.2)])
        with self.store.connect() as db:
            db.execute('ALTER TABLE observations DROP COLUMN source_receipts_json')
            db.execute("UPDATE meta SET value='4' WHERE key='schema_version'")
        migrated=MarketStore(self.store.path)
        with migrated.connect() as db:
            self.assertIn('source_receipts_json',{row['name'] for row in db.execute('PRAGMA table_info(observations)')})
        self.assertEqual(migrated.get_observations('macro_series','DGS2')[0]['source_receipts'],[])
        self.assertEqual(migrated.get_observations('macro_series','DGS2')[0]['value'],4.2)

    def test_malformed_later_page_does_not_leave_unbound_partial_rows(self):
        property_body=b'v_detail_time_sh600519=[20260930,"09:25:01~09:33:25|09:33:25~09:40:00"]'
        page0=b'v_detail_data_sh600519=[0,"0/09:25:01/100/1/10/1000/B"]'
        page1=b'v_detail_data_sh600519=[1,"1/09:34:01/100/1/10/1000/B|malformed"]'
        with patch('urllib.request.urlopen',side_effect=[Reply(property_body,'https://example.test/property'),Reply(page0,'https://example.test/page0'),Reply(page1,'https://example.test/page1')]):
            rows=TencentIntradayProvider(self.client).fetch_transactions('600519')
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[-1].value['records'],1)
        self.assertEqual(rows[-1].value['received_pages'],1)
        self.assertEqual(len(rows[0].source_receipts),2)
        self.assertEqual(rows[-1].source_receipts,rows[0].source_receipts)

    def test_after_close_supplier_rows_are_retained_and_time_meaning_unverified(self):
        rows=[Observation('fixture','transaction_aggregate','sh600519#'+str(index),stamp,
                          {'amount':amount}) for index,(stamp,amount) in enumerate([
            ('2026-09-30T15:00:00+08:00',100),('2026-09-30T15:00:03+08:00',50)])]
        audit=aggregate_clock_audit(rows)
        self.assertEqual(audit['after_cash_close_records'],1)
        self.assertEqual(audit['after_cash_close_amount_CNY'],50)
        self.assertFalse(audit['execution_time_verified'])
        self.assertEqual(len(rows),2)


if __name__=='__main__':
    unittest.main()
