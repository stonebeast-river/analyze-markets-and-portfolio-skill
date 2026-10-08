import tempfile,unittest,json,gzip,io
from unittest.mock import patch
from datetime import datetime,timedelta,date,timezone
from pathlib import Path

from market_core.models import Bar
from market_core.pipeline import MarketPipeline
from market_core.history_collection import collect_cn_history
from market_core.indicators import indicator_rows
from market_core.workflow import prepare_research,verify_research
from market_core.providers.tencent_history import TencentHistoryProvider
from market_core.http import HttpClient


class Reply(io.BytesIO):
    def __init__(self,data):super().__init__(data);self.headers={};self.status=200
    def geturl(self):return 'https://example.test/history'


class Source:
    name='fixture_raw_history'
    def __init__(self,basis='unadjusted'):
        self.calls=[];self.fail=False;self.basis=basis
        self.rows=[Bar(self.name,'sh000300','1d',(date(2026,1,1)+timedelta(days=i)).isoformat(),
            100+i,102+i,99+i,101+i,volume=1000+i,currency='CNY',price_basis=basis) for i in range(80)]

    def fetch_bars(self,symbol,*,start_date,end_date,frequency,adjustment):
        self.calls.append((start_date,end_date,adjustment))
        if self.fail:raise RuntimeError('fixture network failure')
        return [Bar(**{**row.to_dict(),'source_url':f'https://example.test/history?start={start_date}&end={end_date}'})
                for row in self.rows if start_date<=row.timestamp<=end_date]


class HistoryCollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.pipeline=MarketPipeline({'database':'fixture.sqlite3','profiles':{},'providers':{},
            'collection_transport':{'archive_enabled':False}},config_path=self.root/'config.json')
        self.provider=Source();self.now=datetime(2026,3,22,tzinfo=timezone.utc)
        self.start='2026-01-01';self.end='2026-03-21';self.profile={}

    def tearDown(self):self.temp.cleanup()

    def collect(self,*,now=None,start=None):
        return collect_cn_history(self.pipeline,self.provider,'sh000300',self.profile,start or self.start,
                                  self.end,'none' if self.provider.basis=='unadjusted' else 'qfq',now=now or self.now)

    def test_incremental_refresh_keeps_full_recursive_indicator_prefix(self):
        first=self.collect()[1]['collection_refresh_contract']
        second=self.collect(now=self.now+timedelta(hours=1))[1]['collection_refresh_contract']
        self.assertEqual(first['mode'],'full')
        self.assertEqual(second['mode'],'incremental')
        self.assertGreater(self.provider.calls[1][0],self.start)
        self.assertEqual(second['indicator_input_rows'],80)
        self.assertLess(second['source_rows'],80)
        self.assertFalse(second['atomic_publisher_revision_verified'])
        run=self.root/'run';prepare_research(self.pipeline.store,run,profile='allocation')
        self.assertEqual(verify_research(run)['status'],'ok')

    def test_adjusted_source_always_uses_full_requested_window(self):
        self.provider=Source('qfq')
        self.collect();result=self.collect(now=self.now+timedelta(hours=1))[1]['collection_refresh_contract']
        self.assertEqual(result['mode'],'full')
        self.assertEqual(result['reason'],'adjusted_history_requires_full_source_refresh')
        self.assertEqual(self.provider.calls[-1][0],self.start)

    def test_baseline_deletion_causes_full_recovery(self):
        self.collect()
        with self.pipeline.store.connect() as db:
            db.execute("DELETE FROM bars WHERE timestamp='2026-02-01'")
        result=self.collect(now=self.now+timedelta(hours=1))[1]['collection_refresh_contract']
        self.assertEqual(result['mode'],'full')
        self.assertEqual(result['reason'],'baseline_changed_missing_or_scope_expanded')
        self.assertEqual(len(self.pipeline.store.get_bars('sh000300','1d',provider=self.provider.name)),80)

    def test_periodic_full_refresh_and_moving_window_are_distinct(self):
        self.collect()
        moving=self.collect(now=self.now+timedelta(hours=1),start='2026-01-02')[1]['collection_refresh_contract']
        self.assertEqual(moving['mode'],'incremental')
        self.assertEqual(moving['indicator_input_rows'],79)
        periodic=self.collect(now=self.now+timedelta(days=8),start='2026-01-02')[1]['collection_refresh_contract']
        self.assertEqual(periodic['mode'],'full')
        self.assertEqual(periodic['reason'],'periodic_full_refresh_due')

    def test_failed_incremental_fetch_does_not_advance_checkpoint_or_replace_data(self):
        self.collect()
        before=self.pipeline.store.get_observations('history_collection_checkpoint',limit=1)
        old=self.pipeline.store.get_bars('sh000300','1d',provider=self.provider.name)
        self.provider.fail=True
        with self.assertRaisesRegex(RuntimeError,'network failure'):self.collect(now=self.now+timedelta(hours=1))
        self.assertEqual(before,self.pipeline.store.get_observations('history_collection_checkpoint',limit=1))
        self.assertEqual([r.to_dict() for r in old],[r.to_dict() for r in self.pipeline.store.get_bars('sh000300','1d',provider=self.provider.name)])

    def test_full_response_omitting_prior_dates_is_refused_without_writes(self):
        self.collect();before=self.pipeline.store.get_observations('history_collection_checkpoint',limit=1)
        self.provider.rows=self.provider.rows[20:]
        with self.assertRaisesRegex(ValueError,'omitted previously stored dates'):
            self.collect(now=self.now+timedelta(days=8))
        self.assertEqual(before,self.pipeline.store.get_observations('history_collection_checkpoint',limit=1))

    def test_corrupted_normalized_baseline_forces_full_and_preserves_damage(self):
        self.collect()
        state=self.pipeline.store.get_observations('history_collection_checkpoint',limit=1)[-1]['value']
        path=self.pipeline.database.parent/'history-baselines'/state['normalized_baseline_reference']['path']
        path.write_bytes(b'corrupted baseline bytes')
        result=self.collect(now=self.now+timedelta(hours=1))[1]['collection_refresh_contract']
        self.assertEqual(result['mode'],'full')
        self.assertEqual(result['reason'],'baseline_source_archive_missing_or_invalid')
        self.assertEqual(len(list((self.pipeline.database.parent/'history-baselines/quarantine').glob('*.gz'))),1)
        self.assertEqual(self.collect(now=self.now+timedelta(hours=2))[1]['collection_refresh_contract']['mode'],'incremental')

    def test_corrupted_raw_dependency_refetches_full_before_incremental_reuse(self):
        config={'database':'http.sqlite3','profiles':{},'providers':{},'collection_transport':{'archive_enabled':True}}
        pipeline=MarketPipeline(config,config_path=self.root/'http-config.json')
        provider=pipeline._http(TencentHistoryProvider(HttpClient(retries=0)))
        records=[[r.timestamp,r.open,r.close,r.high,r.low,r.volume] for r in self.provider.rows]
        body=json.dumps({'data':{'sh000300':{'day':records}}}).encode()
        with patch('urllib.request.urlopen',side_effect=[Reply(body),Reply(body)]):
            collect_cn_history(pipeline,provider,'sh000300',{},self.start,self.end,'none',now=self.now)
            first=pipeline.store.get_bars('sh000300','1d',provider=provider.name)[0]
            ref=first.source_receipts[0]
            receipt=json.loads((pipeline.response_vault.directory/ref['receipt_path']).read_bytes())
            path=pipeline.response_vault.directory/receipt['decoded']['path']
            path.write_bytes(gzip.compress(b'corrupted raw response'))
            result=collect_cn_history(pipeline,provider,'sh000300',{},self.start,self.end,'none',now=self.now+timedelta(hours=1))[1]
        self.assertEqual(result['collection_refresh_contract']['mode'],'full')
        self.assertEqual(result['collection_refresh_contract']['reason'],'baseline_source_archive_missing_or_invalid')
        self.assertEqual(pipeline.store.source_trace('bar','sh000300',provider=provider.name)['status'],'verified')
        self.assertEqual(len(list((pipeline.response_vault.directory/'quarantine').glob('*.gz'))),1)

    def test_missing_overlap_date_uses_one_full_retry_not_old_row_as_success(self):
        self.collect();original=self.provider.fetch_bars
        def incomplete_overlap(symbol,**kwargs):
            values=original(symbol,**kwargs)
            return values[:-1] if kwargs['start_date']>self.start else values
        self.provider.fetch_bars=incomplete_overlap
        result=self.collect(now=self.now+timedelta(hours=1))[1]['collection_refresh_contract']
        self.assertEqual(result['mode'],'full')
        self.assertEqual(result['reason'],'incremental_response_omitted_baseline_dates')
        self.assertEqual(result['bounded_full_recovery']['missing_previously_stored_overlap_dates'],['2026-03-21'])
        self.assertEqual(len(self.provider.calls),3)
        self.assertEqual(result['source_rows'],80)


if __name__=='__main__':unittest.main()
