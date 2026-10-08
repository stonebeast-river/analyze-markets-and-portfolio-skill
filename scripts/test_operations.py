import gzip
import io
import json
import tempfile
import time
import unittest
import urllib.error
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from market_core.http import HttpClient,DataSourceError
from market_core.pipeline import MarketPipeline
from market_core.responses import ResponseVault
from market_core.providers.tencent_intraday import TencentIntradayProvider


class Reply(io.BytesIO):
    def __init__(self,data,headers=None):super().__init__(data);self.headers=headers or {};self.status=200
    def geturl(self):return 'https://example.test/data'


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.vault=ResponseVault(self.root/'responses')
        self.client=HttpClient(retries=0,archive=self.vault)
        self.url='https://example.test/data'

    def tearDown(self):self.temp.cleanup()

    def test_new_response_preserves_previous_raw_version(self):
        with patch('urllib.request.urlopen',side_effect=[Reply(b'{"price":100}'),Reply(b'{"price":105}')]):
            self.assertEqual(self.client.get_json(self.url)[0]['price'],100)
            self.assertEqual(self.client.get_json(self.url)[0]['price'],105)
        payloads={gzip.decompress(path.read_bytes()) for path in (self.root/'responses'/'payloads').glob('*.gz')}
        self.assertEqual(payloads,{b'{"price":100}',b'{"price":105}'})

    def seed(self,body,age):
        request_id=self.vault.request_id(self.url,{'User-Agent':self.client.user_agent,'Accept-Encoding':'gzip'})
        received=datetime.fromtimestamp(time.time()-age,timezone.utc).isoformat()
        receipt=self.vault.store(request_id,self.url,self.url,body,body,headers={},received_at=received)
        return received,receipt

    def test_cache_preserves_original_receive_time(self):
        received,_=self.seed(b'{"price":100}',5);self.client.cache_ttl_by_host={'example.test':30}
        with patch('urllib.request.urlopen') as network:
            self.assertEqual(self.client.get_json(self.url)[0]['price'],100);network.assert_not_called()
        self.assertEqual(self.client.last_response_receipt['received_at'],received)
        self.assertEqual(self.client.last_response_receipt['transport'],'cache')

    def test_expired_cache_is_not_failure_fallback(self):
        self.seed(b'{"price":100}',60);self.client.cache_ttl_by_host={'example.test':10}
        with patch('urllib.request.urlopen',side_effect=urllib.error.URLError('offline')):
            with self.assertRaises(DataSourceError):self.client.get_json(self.url)
        self.assertEqual(self.vault.events[-1]['status'],'network_failed')

    def test_invalid_json_is_retained_but_removed_from_cache(self):
        self.client.cache_ttl_by_host={'example.test':300}
        with patch('urllib.request.urlopen',side_effect=[Reply(b'broken json'),Reply(b'{"price":105}')]) as network:
            with self.assertRaises(DataSourceError):self.client.get_json(self.url)
            self.assertEqual(self.client.get_json(self.url)[0]['price'],105)
            self.assertEqual(network.call_count,2)
        self.assertTrue(any(gzip.decompress(path.read_bytes())==b'broken json' for path in (self.root/'responses'/'payloads').glob('*.gz')))

    def test_corrupted_cache_refetches_and_retains_damaged_bytes(self):
        self.seed(b'{"price":100}',5);self.client.cache_ttl_by_host={'example.test':30}
        payload=next((self.root/'responses'/'payloads').glob('*.gz'));payload.write_bytes(gzip.compress(b'changed'))
        with patch('urllib.request.urlopen',return_value=Reply(b'{"price":100}')) as network:
            self.assertEqual(self.client.get_json(self.url)[0]['price'],100);self.assertEqual(network.call_count,1)
        self.assertEqual(len(list((self.root/'responses'/'quarantine').glob('*.gz'))),1)

    def test_request_credentials_and_echo_are_not_written(self):
        url=self.url+'?api_key=fixture-private-key'
        with patch('urllib.request.urlopen',return_value=Reply(b'{"error":"fixture-private-key"}')):
            self.client.get_json(url)
        self.assertEqual(self.vault.events[-1]['status'],'credential_echo_not_archived')
        for path in (self.root/'responses').rglob('*.json'):
            self.assertNotIn('fixture-private-key',path.read_text(encoding='utf-8'))
        self.assertFalse((self.root/'responses'/'payloads').exists())

    def test_gzip_receipt_retains_wire_and_decoded_bytes(self):
        plain=b'{"price":100}';wire=gzip.compress(plain,mtime=0)
        with patch('urllib.request.urlopen',return_value=Reply(wire,{'Content-Encoding':'gzip'})):
            self.assertEqual(self.client.get_json(self.url)[0]['price'],100)
        bodies={gzip.decompress(path.read_bytes()) for path in (self.root/'responses'/'payloads').glob('*.gz')}
        self.assertEqual(bodies,{wire,plain})

    def test_decoding_failure_never_becomes_cache_success(self):
        with patch('urllib.request.urlopen',return_value=Reply(b'bad gzip',{'Content-Encoding':'gzip'})):
            with self.assertRaises(DataSourceError):self.client.get_bytes(self.url)
        self.assertEqual(self.vault.events[-1]['status'],'decode_failed')
        self.assertFalse((self.root/'responses'/'cache').exists())

    def test_pipeline_contract_failure_invalidates_response_cache(self):
        config={'database':'test.sqlite3','profiles':{},'providers':{},
                'collection_transport':{'archive_enabled':True,'cache_ttl_by_host':{'example.test':300}}}
        pipeline=MarketPipeline(config,config_path=self.root/'config.json')
        provider=pipeline._http(SimpleNamespace(name='fixture',client=HttpClient(retries=0)))
        def failed():
            provider.client.get_json(self.url)
            raise DataSourceError('Required contract field missing')
        with patch('urllib.request.urlopen',return_value=Reply(b'{"wrong":1}')):
            result=pipeline._run('fixture','contract',failed)
        self.assertEqual(result.status,'failed')
        self.assertFalse(any((pipeline.response_vault.directory/'cache').glob('*.json')))
        with pipeline.store.connect() as db:
            details=json.loads(db.execute('SELECT details_json FROM provider_runs ORDER BY id DESC LIMIT 1').fetchone()[0])
        self.assertTrue(any(row['status']=='response_rejected_by_parser_or_contract' for row in details['response_receipts']))

    def test_invalid_deflate_cache_is_refetched(self):
        self.seed(b'{"price":100}',5);self.client.cache_ttl_by_host={'example.test':30}
        payload=next((self.root/'responses'/'payloads').glob('*.gz'))
        payload.write_bytes(b'\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03\x07')
        with patch('urllib.request.urlopen',return_value=Reply(b'{"price":100}')) as network:
            self.assertEqual(self.client.get_json(self.url)[0]['price'],100);self.assertEqual(network.call_count,1)

    def test_modified_receipt_time_does_not_make_expired_data_fresh(self):
        _,receipt=self.seed(b'{"price":100}',60);self.client.cache_ttl_by_host={'example.test':30}
        path=self.vault.directory/receipt['receipt_path'];record=json.loads(path.read_bytes())
        record['received_at']=datetime.now(timezone.utc).isoformat();path.write_text(json.dumps(record),encoding='utf-8')
        with patch('urllib.request.urlopen',return_value=Reply(b'{"price":105}')) as network:
            self.assertEqual(self.client.get_json(self.url)[0]['price'],105);self.assertEqual(network.call_count,1)

    def test_pipeline_records_partial_supplier_window_and_rejects_only_bad_page(self):
        config={'database':'partial.sqlite3','profiles':{},'providers':{},
                'collection_transport':{'archive_enabled':True,'cache_ttl_by_host':{'stock.gtimg.cn':300}}}
        pipeline=MarketPipeline(config,config_path=self.root/'config.json')
        provider=pipeline._http(TencentIntradayProvider(HttpClient(retries=0)))
        property_body=b'v_detail_time_sh600519=[20260930,"09:25:01~09:33:25|09:33:25~09:40:00"]'
        page0=b'v_detail_data_sh600519=[0,"0/09:25:01/100/1/10/1000/B"]'
        page1=b'v_detail_data_sh600519=[1,"malformed"]'
        with patch('urllib.request.urlopen',side_effect=[Reply(property_body),Reply(page0),Reply(page1)]):
            result=pipeline._run(provider.name,'supplier_window',lambda:pipeline._store_observations(provider.fetch_transactions('600519')))
        self.assertEqual(result.status,'partial')
        with pipeline.store.connect() as db:
            row=db.execute('SELECT status,row_count,details_json FROM provider_runs ORDER BY id DESC LIMIT 1').fetchone()
        self.assertEqual(row['status'],'partial')
        self.assertEqual(row['row_count'],2)
        details=json.loads(row['details_json'])
        self.assertEqual(details['incomplete_source_windows'][0]['received_pages'],1)
        self.assertTrue(any(event['status']=='response_rejected_by_parser_or_contract' for event in details['response_receipts']))
        self.assertEqual(len(list((pipeline.response_vault.directory/'cache').glob('*.json'))),2)
        summaries=pipeline.store.get_observations('transaction_aggregate_summary','sh600519')
        self.assertEqual(summaries[-1]['value']['records'],1)
        self.assertEqual(summaries[-1]['value']['status'],'partial')
        repaired=b'v_detail_data_sh600519=[1,"1/09:35:01/100/1/10/1000/S"]'
        with patch('urllib.request.urlopen',return_value=Reply(repaired)) as network:
            recovered=pipeline._run(provider.name,'supplier_window',lambda:pipeline._store_observations(provider.fetch_transactions('600519')))
        self.assertEqual(network.call_count,1)
        self.assertEqual(recovered.status,'ok')
        self.assertEqual(recovered.row_count,3)
        self.assertEqual(pipeline.store.get_observations('transaction_aggregate_summary','sh600519',limit=1)[-1]['value']['status'],'complete_supplier_window')


if __name__=='__main__':unittest.main(verbosity=2)
