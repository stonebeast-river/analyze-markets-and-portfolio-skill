import math,tempfile,json,hashlib,unittest
from pathlib import Path
from unittest.mock import patch
from market_core.models import Bar,Observation
from market_core.indicators import kdj,indicator_rows
from market_core.chips import estimate_chips,create_chip_research,verify_chip_research
from market_core.store import MarketStore
from market_core.http import HttpClient,DataSourceError
from market_core.providers.eastmoney_history import EastmoneyHistoryProvider

def sample(n=80):
    from datetime import date,timedelta
    return [Bar('fixture','sh600276','1d',(date(2026,1,1)+timedelta(days=i)).isoformat(),10,11,9,10,
        currency='CNY',price_basis='qfq') for i in range(n)]

class KdjChipTests(unittest.TestCase):
    def test_full_window_and_recursive_seed(self):
        bars=sample(10);bars[-2].close=11;bars[-1].close=11
        k,d,j=kdj(bars)
        self.assertTrue(all(v is None for v in k[:8]))
        self.assertAlmostEqual(k[8],200/3);self.assertAlmostEqual(d[8],500/9)
        self.assertAlmostEqual(j[8],800/9)
        self.assertAlmostEqual(k[9],700/9)
    def test_flat_and_unbounded_j(self):
        bars=sample(9)
        for b in bars:b.open=b.high=b.low=b.close=10
        self.assertEqual(kdj(bars)[2][-1],50)
        bars=sample(30)
        for b in bars[8:]:b.close=11
        self.assertGreater(max(v for v in kdj(bars)[2] if v is not None),100)
        for b in bars[8:]:b.close=9
        self.assertLess(min(v for v in kdj(bars)[2] if v is not None),0)
    def test_kdj_indicator_basis_and_units(self):
        rows=indicator_rows(sample())
        self.assertEqual({r.name for r in rows if r.name.startswith('kdj')},{'kdj_k','kdj_d','kdj_j'})
        self.assertTrue(all(r.unit=='oscillator_unbounded' and r.price_basis=='qfq' for r in rows if r.name=='kdj_j'))
    def test_chip_mass_regions_and_unknown_seed(self):
        result=estimate_chips(sample(),[1]*80)
        self.assertAlmostEqual(sum(r['weight'] for r in result['distribution']),1)
        self.assertAlmostEqual(result['unknown_initial_weight_fraction'],.99**79)
        self.assertAlmostEqual(result['mean_cost'],10)
        self.assertLessEqual(result['cost_regions']['90']['low'],result['cost_regions']['70']['low'])
        self.assertGreaterEqual(result['cost_regions']['90']['high'],result['cost_regions']['70']['high'])
    def test_flat_chips_and_zero_turnover(self):
        bars=sample()
        for b in bars:b.open=b.high=b.low=b.close=10
        result=estimate_chips(bars,[0]*80)
        self.assertEqual(result['mean_cost'],10);self.assertEqual(result['unknown_initial_weight_fraction'],1)
        self.assertEqual(result['profit_fraction'],1)
    def test_missing_turnover_and_mixed_series_refused(self):
        bars=sample();turns=[1]*80;turns[5]=None
        with self.assertRaises(ValueError):estimate_chips(bars,turns)
        bars[5].provider='other'
        with self.assertRaises(ValueError):estimate_chips(bars,[1]*80)
    def test_over_100_turnover_recorded_and_replaces_mass(self):
        result=estimate_chips(sample(),[1]*79+[150])
        self.assertEqual(result['turnover_over_100pct_capped_days'],1)
        self.assertEqual(result['unknown_initial_weight_fraction'],0)
    def test_frozen_replay_and_resealed_false_mean(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=MarketStore(Path(tmp)/'data.sqlite3');bars=sample();store.upsert_bars(bars)
            store.upsert_observations([Observation('fixture','cn_daily_valuation_liquidity','sh600276',b.timestamp,
                {'turnover_pct':1},unit='percent') for b in bars])
            out=Path(tmp)/'chips';create_chip_research(store,'sh600276',out,collect=False,end=bars[-1].timestamp)
            self.assertEqual(verify_chip_research(out)['status'],'ok')
            original=json.loads((out/'chips.json').read_text(encoding='utf-8'))
            store.upsert_bars([Bar('fixture','sh600276','1d','2026-04-01',100,110,90,100,currency='CNY',price_basis='qfq')])
            earlier=Path(tmp)/'same-cutoff';create_chip_research(store,'sh600276',earlier,collect=False,end=bars[-1].timestamp)
            self.assertEqual(original,json.loads((earlier/'chips.json').read_text(encoding='utf-8')))
            data=json.loads((out/'chips.json').read_text(encoding='utf-8'));data['mean_cost']+=1
            (out/'chips.json').write_text(json.dumps(data),encoding='utf-8')
            seal=json.loads((out/'seal.json').read_text());seal['chips.json']=hashlib.sha256((out/'chips.json').read_bytes()).hexdigest()
            (out/'seal.json').write_text(json.dumps(seal))
            self.assertIn('mean_cost',verify_chip_research(out)['failures'])
            with self.assertRaises(ValueError):create_chip_research(store,'sh600276',out,collect=False,end=bars[-1].timestamp)
    def test_eastmoney_contract_and_date_cutoff(self):
        client=HttpClient();source=EastmoneyHistoryProvider(client)
        payload={'data':{'code':'600276','klines':['2026-09-30,10,10,11,9,100,100000,20,0,0,2']}}
        with patch.object(client,'get_json',return_value=(payload,'https://example.test')):
            bars,turns=source.fetch_inputs('sh600276',start='2026-09-01',end='2026-09-30')
            self.assertEqual(turns[0].value['turnover_pct'],2);self.assertEqual(bars[0].price_basis,'qfq')
            with self.assertRaises(DataSourceError):source.fetch_inputs('sz000001',start='2026-09-01',end='2026-09-30')
            with self.assertRaises(DataSourceError):source.fetch_inputs('sh600276',start='2026-09-01',end='2026-09-29')
    def test_dividend_original_units_and_identity(self):
        from market_core.providers.baostock_provider import BaoStockProvider
        import baostock as bs
        from types import SimpleNamespace
        source=BaoStockProvider()
        factor={'code':'sh.600276','dividOperateDate':'2026-05-27','foreAdjustFactor':'1.000000'}
        dividend={'code':'sh.600276','dividOperateDate':'2026-05-27','dividPlanAnnounceDate':'2026-03-26',
            'dividCashPsBeforeTax':'0.2','dividCashStock':'10派2元','dividCashPsAfterTax':'0.18或0.2'}
        with patch.object(bs,'login',return_value=SimpleNamespace(error_code='0')),patch.object(bs,'logout'), \
             patch.object(bs,'query_adjust_factor'),patch.object(bs,'query_dividend_data'), \
             patch.object(source,'_records',side_effect=[[factor],[dividend],[]]):
            rows=source.fetch_corporate_actions('sh600276',start_date='2024-01-01',end_date='2026-09-30')
            record=next(r for r in rows if r.dataset=='corporate_dividend_record')
            self.assertEqual(record.value['dividCashPsBeforeTax'],'0.2')
            self.assertEqual(record.value['dividCashPsAfterTax'],'0.18或0.2')
            self.assertEqual(record.publication,'2026-03-26')
            self.assertEqual(rows[-1].value['dividend_operate_years'],[2025,2026])

if __name__=='__main__':unittest.main()
