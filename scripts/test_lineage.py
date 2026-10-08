import gzip
import hashlib
import json
import tempfile
import unittest
from datetime import date,timedelta
from pathlib import Path

from market_core.indicators import indicator_rows,quote_indicator_rows,series_indicator_rows
from market_core.lineage import canonical
from market_core.models import Bar,Observation,Quote
from market_core.store import MarketStore
from market_core.workflow import prepare_research,read_prepared,verify_research,lock_market_view


class LineageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.store=MarketStore(self.root/'fixture.sqlite3')
        self.bars=[Bar('fixture','sh600519','1d',(date(2026,9,30)-timedelta(days=89-i)).isoformat(),
                       100+i/10,102+i/10,99+i/10,101+i/10+(i%7)/10,volume=1000+i,
                       currency='CNY',price_basis='unadjusted') for i in range(90)]

    def tearDown(self):self.temp.cleanup()

    def prepare_bars(self,name='run'):
        self.store.upsert_bars(self.bars);self.store.upsert_indicators(indicator_rows(self.bars))
        run=self.root/name;prepare_research(self.store,run,profile='allocation');return run

    def test_sealed_run_replays_after_live_inputs_are_revised(self):
        run=self.prepare_bars();self.bars[0].close+=0.5;self.store.upsert_bars([self.bars[0]])
        result=verify_research(run)
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['indicators_checked'],13)
        self.assertIs(result['live_database_used'],False)

    def test_changed_source_window_cannot_verify_old_indicator(self):
        self.prepare_bars();self.bars[0].close+=0.5;self.store.upsert_bars([self.bars[0]])
        run=self.root/'revised';prepare_research(self.store,run,profile='allocation')
        _,inputs,_=read_prepared(run)
        derived=[fact for fact in inputs['evidence_register'].values() if 'input_provider' in fact['record']]
        self.assertEqual(len(derived),13)
        self.assertTrue(all(not fact['eligible'] for fact in derived))
        self.assertTrue(all(fact['record']['lineage']['status']=='source_inputs_changed_or_missing' for fact in derived))

    def test_frozen_input_tamper_is_detected_even_when_top_json_is_unchanged(self):
        run=self.prepare_bars();_,inputs,_=read_prepared(run)
        reference=next(ref for ref in inputs['input_references'] if ref['kind']=='bars')
        path=run/reference['path'];payload=json.loads(gzip.decompress(path.read_bytes()))
        payload['inputs'][0]['close']+=0.5;path.write_bytes(gzip.compress(canonical(payload),mtime=0))
        with self.assertRaisesRegex(ValueError,'inputs were changed'):read_prepared(run)

    def test_vendor_quote_metric_freezes_the_actual_quote(self):
        quote=Quote('fixture','sh600519','2026-09-30T15:00:00+08:00',asset_class='equity',last=11,previous_close=10,
                    volume_ratio_vendor=1.8,currency='CNY',bid_book=[{'price':10,'volume':100}],ask_book=[{'price':11,'volume':200}])
        self.store.upsert_quotes([quote]);self.store.upsert_indicators(quote_indicator_rows([quote]))
        run=self.root/'quotes';prepare_research(self.store,run,profile='tactical')
        result=verify_research(run)
        self.assertEqual(result['status'],'ok');self.assertEqual(result['indicators_checked'],4)

    def test_nav_inputs_keep_later_publication_before_research_cutoff(self):
        rows=[Observation('fixture','fund_unit_nav','000051','2026-09-29',1.0,publication='2026-09-30T18:00:00+08:00',price_basis='unit_nav'),
              Observation('fixture','fund_unit_nav','000051','2026-09-30',1.1,publication='2026-10-01T18:00:00+08:00',price_basis='unit_nav')]
        self.store.upsert_observations(rows);self.store.upsert_indicators(series_indicator_rows(rows))
        run=self.root/'nav';prepare_research(self.store,run,profile='allocation')
        result=verify_research(run)
        self.assertEqual(result['status'],'ok');self.assertEqual(result['indicators_checked'],8)

    def test_series_rejects_provider_or_revision_mixing(self):
        with self.assertRaisesRegex(ValueError,'one provider'):
            series_indicator_rows([Observation('one','fund_unit_nav','000051','2026-09-29',1),
                                   Observation('two','fund_unit_nav','000051','2026-09-30',2)])

    def test_recursive_seed_is_part_of_indicator_identity(self):
        full=indicator_rows(self.bars)[-10:];short=indicator_rows(self.bars[-70:])[-10:]
        self.assertNotEqual(full[0].parameters['input_lineage']['sha256'],short[0].parameters['input_lineage']['sha256'])
        self.assertEqual(full[0].parameters['input_lineage']['row_count'],90)
        self.assertEqual(short[0].parameters['input_lineage']['row_count'],70)

    def test_read_only_store_does_not_write_receipts_before_refusal(self):
        store=MarketStore(self.store.path,read_only=True)
        before=set((self.root/'receipts').rglob('*')) if (self.root/'receipts').exists() else set()
        with self.assertRaises(PermissionError):store.upsert_bars(self.bars)
        after=set((self.root/'receipts').rglob('*')) if (self.root/'receipts').exists() else set()
        self.assertEqual(before,after)

    def test_registered_aggregate_must_match_frozen_inputs_after_resealing(self):
        self.store.upsert_quotes([Quote('fixture','sh600519','2026-09-30T15:00:00+08:00',asset_class='equity',last=11,previous_close=10)])
        self.store.upsert_observations([Observation('fixture','industry_classification','sh600519','2026-09-30',
                                      {'classification':'fixture','industry':'C27医药'})])
        from unittest.mock import patch
        from datetime import datetime,timezone
        run=self.root/'aggregate'
        # Freeze this dated fixture's read time rather than depending on today's session.
        with patch('market_core.workflow.datetime',wraps=datetime) as clock:
            clock.now.return_value=datetime(2026,9,30,7,20,tzinfo=timezone.utc)
            prepare_research(self.store,run,profile='allocation')
        _,inputs,_=read_prepared(run)
        key,fact=next((key,fact) for key,fact in inputs['evidence_register'].items()
                     if fact['record'].get('measurement')=='industry_price_breadth')
        fact['record']['median_change_fraction']+=0.5
        del inputs['evidence_register'][key]
        changed_key='E-'+hashlib.sha256(canonical(fact)).hexdigest()[:16]
        inputs['evidence_register'][changed_key]=fact
        (run/'research-inputs.json').write_bytes(canonical(inputs))
        (run/'input-seal.json').write_bytes(canonical({'sha256':hashlib.sha256(canonical(inputs)).hexdigest()}))
        result=verify_research(run)
        self.assertEqual(result['status'],'failed')
        self.assertIn(changed_key+':registered_aggregate',result['failures'])
        view=self.root/'view.json'
        view.write_text(json.dumps({'market_summary':'fixture','theses':[{'evidence_ids':[changed_key],
                          'countercase':'fixture countercase','invalidation':'fixture invalidation'}],
                          'opportunities':[],'alternatives':['wait'],'waiting_case':'fixture'}),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'recomputation failed'):
            lock_market_view(run,view)
        self.assertFalse((run/'market-view.json').exists())


if __name__=='__main__':unittest.main(verbosity=2)
