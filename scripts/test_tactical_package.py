import json
import tempfile
import unittest
from datetime import datetime,timedelta,date
from pathlib import Path

from market_core.models import Bar,Observation,Quote
from market_core.indicators import indicator_rows,quote_indicator_rows
from market_core.store import MarketStore
from market_core.workflow import prepare_research,read_prepared,verify_research
from market_core.lineage import read_frozen_inputs,canonical


class TacticalPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.store=MarketStore(self.root/'fixture.sqlite3')
        self.bars=[Bar('fixture_minute','sh600519','5m',
            (datetime.fromisoformat('2026-09-30T09:35:00+08:00')+timedelta(minutes=5*i)).isoformat(),
            100+i/10,102+i/10,99+i/10,101+i/10,volume=1000+i,currency='CNY',price_basis='unadjusted') for i in range(40)]
        self.store.upsert_bars(self.bars);self.store.upsert_indicators(indicator_rows(self.bars))
        quote=Quote('fixture_quote','sh600519','2026-09-30T15:00:00+08:00',last=105,previous_close=100,currency='CNY')
        self.store.upsert_quotes([quote]);self.store.upsert_indicators(quote_indicator_rows([quote]))
        self.config={'profiles':{'tactical':{'cn_symbols':['sh600519'],'intraday_interval':'5m','tick_symbols':['sh600519']}},'providers':{}}

    def tearDown(self):self.temp.cleanup()

    def test_profile_targets_survive_a_global_snapshot_cap(self):
        for index in range(30):
            rows=[Bar('global_fixture',f'A{index:02d}','1d',(date(2026,9,30)-timedelta(days=79-i)).isoformat(),
                100+i/10,102+i/10,99+i/10,101+i/10,volume=1000+i,currency='USD',price_basis='unadjusted') for i in range(80)]
            self.store.upsert_bars(rows);self.store.upsert_indicators(indicator_rows(rows))
        self.assertEqual(len(self.store.snapshot()['latest_indicators']),300)
        self.assertFalse(any(r['symbol']=='sh600519' for r in self.store.snapshot()['latest_indicators']))
        run=self.root/'run';prepare_research(self.store,run,profile='tactical',config=self.config)
        _,inputs,_=read_prepared(run)
        targeted=[f for f in inputs['evidence_register'].values() if f['identity']=='sh600519' and 'input_provider' in f['record']]
        self.assertEqual(len(targeted),17)
        self.assertTrue(all(f['record']['lineage']['recomputed_matches'] for f in targeted))
        minute_refs=[ref for ref in inputs['input_references'] if ref['kind']=='bars' and
                     read_frozen_inputs(run,ref)[-1]['symbol']=='sh600519']
        self.assertEqual(len(read_frozen_inputs(run,minute_refs[0])),40)
        self.assertEqual(verify_research(run)['status'],'ok')

    def test_supplier_summary_has_replayable_input_rows_and_detects_wrong_total(self):
        rows=[Observation('fixture_aggregate','transaction_aggregate','sh600519#'+str(i),'2026-09-30T14:00:00+08:00',
              {'symbol':'sh600519','amount':amount,'direction':side}) for i,(amount,side) in
              enumerate(((100,'provider_buy'),(60,'provider_sell'),(40,'provider_buy')))]
        summary=Observation('fixture_aggregate','transaction_aggregate_summary','sh600519','2026-09-30T14:00:00+08:00',
            {'buy_amount':140,'sell_amount':60,'neutral_amount':0,'unknown_amount':0,'large_aggregate_buy_amount':0,
             'large_aggregate_sell_amount':0,'net_amount':80,'records':3,'order_size_threshold_CNY':200000,
             'status':'complete_supplier_window'})
        self.store.upsert_observations(rows+[summary]);run=self.root/'run'
        prepare_research(self.store,run,profile='tactical',config=self.config)
        self.assertEqual(verify_research(run)['tactical_aggregates_checked'],1)
        _,inputs,_=read_prepared(run)
        fact=next(f for f in inputs['evidence_register'].values() if f['record'].get('dataset')=='transaction_aggregate_summary')
        self.assertEqual(len(read_frozen_inputs(run,fact['record']['aggregate_input_reference'])),3)
        fact['record']['value']['net_amount']=800
        path=run/'research-inputs.json';path.write_bytes(canonical(inputs))
        import hashlib
        (run/'input-seal.json').write_text(json.dumps({'sha256':hashlib.sha256(canonical(inputs)).hexdigest()}),encoding='utf-8')
        result=verify_research(run)
        self.assertEqual(result['status'],'failed')
        self.assertTrue(any('aggregate_summary_mismatch' in reason for reason in result['failures']))


if __name__=='__main__':unittest.main()
