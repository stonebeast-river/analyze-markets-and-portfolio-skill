import json
import tempfile
import unittest
from pathlib import Path

from market_core.models import Quote, Observation, IndicatorValue
from market_core.store import MarketStore
from market_core.workflow import prepare_research,lock_market_view,load_portfolio_after_view
from market_core.indicators import series_indicator_rows


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.store=MarketStore(self.root/'test.sqlite3')
        self.store.upsert_quotes([Quote('fixture','sh600519','2026-09-30T15:00:00+08:00',asset_class='equity',last=11,previous_close=10)])
        self.run=self.root/'run';prepare_research(self.store,self.run,profile='allocation')
        data=json.loads((self.run/'research-inputs.json').read_text(encoding='utf-8'))
        self.ids=list(data['evidence_register'])

    def tearDown(self):self.temp.cleanup()

    def view(self,opportunities=None):
        value={'market_summary':'Evidence is insufficient for a promoted opportunity.','theses':[{'evidence_ids':self.ids,'countercase':'Data remain incomplete','invalidation':'New contradictory issuer evidence'}],
               'opportunities':opportunities or [],'alternatives':['wait'],'waiting_case':'Core evidence is missing'}
        path=self.root/'view.json';path.write_text(json.dumps(value),encoding='utf-8');return path

    def portfolio(self):
        path=self.root/'portfolio.json';path.write_text(json.dumps({'authoritative_source':'fixture_user_record','positions':[{'code':'000051','cost':12345}]}),encoding='utf-8');return path

    def test_holdings_cannot_load_before_locked_market_view(self):
        with self.assertRaises(ValueError):load_portfolio_after_view(self.run,self.portfolio())
        self.assertFalse((self.run/'portfolio-inputs.private.json').exists())

    def test_price_only_evidence_cannot_promote_opportunity(self):
        candidate={'status':'worth dedicated research','opportunity_type':'fundamental improvement','evidence_ids':self.ids,
                   'countercase':'Price alone lacks earnings evidence','invalidation':'Issuer data contradict the hypothesis','core_missing':[]}
        with self.assertRaises(ValueError):lock_market_view(self.run,self.view([candidate]))

    def test_view_seal_prevents_hindsight_rewrite(self):
        lock_market_view(self.run,self.view())
        path=self.run/'market-view.json';view=json.loads(path.read_text(encoding='utf-8'));view['view']['market_summary']='hindsight change';path.write_text(json.dumps(view),encoding='utf-8')
        with self.assertRaises(ValueError):load_portfolio_after_view(self.run,self.portfolio())

    def test_no_holdings_amount_is_returned_from_overlay_interface(self):
        lock_market_view(self.run,self.view());result=load_portfolio_after_view(self.run,self.portfolio())
        self.assertEqual(result['positions_loaded'],1)
        self.assertNotIn('12345',json.dumps(result))
        self.assertTrue(result['market_view_unchanged'])

    def test_original_numerical_inputs_are_not_overwritten(self):
        before=(self.run/'research-inputs.json').read_bytes()
        with self.assertRaises(ValueError):prepare_research(self.store,self.run,profile='allocation')
        self.assertEqual((self.run/'research-inputs.json').read_bytes(),before)

    def test_unknown_evidence_id_is_rejected(self):
        path=self.view();value=json.loads(path.read_text(encoding='utf-8'));value['theses'][0]['evidence_ids']=['fabricated'];path.write_text(json.dumps(value),encoding='utf-8')
        with self.assertRaises(ValueError):lock_market_view(self.run,path)

    def promote_fixture(self,opportunity_type,target,core):
        self.store.upsert_observations([
            Observation('fixture','macro_series','UNRATE','2026-09-01',4.2,unit='percent',quality='source_verified',source_url='https://example.com/fixture'),
            Observation('fixture','exposure_measure','TLT','2026-09-30',
                        {'measurement':'stress_period_return','value':0.08,'unit':'fraction','window':'fixture_stress_period'},
                        quality='source_verified',source_url='https://example.com/fixture')])
        self.run=self.root/'promote';prepare_research(self.store,self.run,profile='allocation')
        register=json.loads((self.run/'research-inputs.json').read_text(encoding='utf-8'))['evidence_register']
        self.ids=list(register)
        by_identity={fact['identity']:key for key,fact in register.items()}
        candidate={'status':'watch','opportunity_type':opportunity_type,'target_identity':target,
                   'core_evidence':{role:[by_identity[identity]] for role,identity in core.items()},
                   'evidence_ids':list(register),'countercase':'Fixture stress regime may not repeat',
                   'invalidation':'Matched instrument ceases to satisfy the reviewed stress condition','core_missing':[]}
        return candidate

    def test_unknown_opportunity_type_cannot_bypass_core_gate(self):
        candidate=self.promote_fixture('undefined type','TLT',{})
        with self.assertRaisesRegex(ValueError,'four documented'):
            lock_market_view(self.run,self.view([candidate]))

    def test_price_and_macro_cannot_substitute_for_valuation(self):
        candidate=self.promote_fixture('valuation mean reversion with catalyst','TLT',{'valuation':'TLT','catalyst':'UNRATE'})
        with self.assertRaisesRegex(ValueError,'wrong evidence type'):
            lock_market_view(self.run,self.view([candidate]))

    def test_defensive_measure_requires_exact_exposure(self):
        candidate=self.promote_fixture('defensive or diversification value','CNY_short_bond',{'exposure_measure':'TLT','risk_scenario':'UNRATE'})
        with self.assertRaisesRegex(ValueError,'does not match target'):
            lock_market_view(self.run,self.view([candidate]))

    def test_matching_defensive_measure_can_pass_structural_gate(self):
        candidate=self.promote_fixture('defensive or diversification value','TLT',{'exposure_measure':'TLT','risk_scenario':'UNRATE'})
        result=lock_market_view(self.run,self.view([candidate]))
        self.assertEqual(result['opportunity_count'],1)

    def test_boolean_core_missing_does_not_claim_reviewed_empty_list(self):
        candidate=self.promote_fixture('defensive or diversification value','TLT',{'exposure_measure':'TLT','risk_scenario':'UNRATE'})
        candidate['core_missing']=False
        with self.assertRaisesRegex(ValueError,'explicit empty'):
            lock_market_view(self.run,self.view([candidate]))

    def test_derived_indicators_remain_price_evidence(self):
        self.store.upsert_indicators([IndicatorValue('sh600519','1d','2026-09-30','return_20period',0.05,
                        {'periods':20},'fixture',price_basis='unadjusted',unit='fraction'),
                        IndicatorValue('sh600519','1d','2026-09-30','volume_ratio_vendor',1.8,{},'fixture',
                                       quality='vendor_derived',price_basis='unadjusted',unit='ratio')])
        run=self.root/'derived';prepare_research(self.store,run,profile='allocation')
        register=json.loads((run/'research-inputs.json').read_text(encoding='utf-8'))['evidence_register']
        indicators=[fact for fact in register.values() if fact['record'].get('measurement')=='locally_derived_price_or_trading_metric']
        self.assertEqual(len(indicators),1)
        self.assertEqual(indicators[0]['kind'],'market_price')
        self.assertIs(indicators[0]['record']['independent_evidence_type'],False)
        vendor=[fact for fact in register.values() if fact['record'].get('measurement')=='vendor_derived_trading_metric']
        self.assertEqual(len(vendor),1)
        self.assertEqual(vendor[0]['record']['quality'],'vendor_derived')
        self.assertEqual(vendor[0]['kind'],'market_price')

    def test_unmeasured_exposure_is_ineligible_even_if_quality_is_verified(self):
        self.store.upsert_observations([Observation('fixture','exposure_measure','TLT','2026-09-30',
                    {'measurement':'stress_return','value':'unknown','unit':'fraction','window':'fixture'},quality='source_verified')])
        run=self.root/'unmeasured';prepare_research(self.store,run,profile='allocation')
        register=json.loads((run/'research-inputs.json').read_text(encoding='utf-8'))['evidence_register']
        exposure=[fact for fact in register.values() if fact['kind']=='exposure_measure']
        self.assertEqual(len(exposure),1)
        self.assertIs(exposure[0]['eligible'],False)

    def test_empty_fund_valuation_columns_do_not_become_valuation_evidence(self):
        self.store.upsert_observations([Observation('fixture','cn_daily_valuation_liquidity','sh510300','2026-09-30',
                                      {'pe_ttm':None,'pb_mrq':None,'ps_ttm':None,'pcf_ncf_ttm':None})])
        run=self.root/'empty-valuation';prepare_research(self.store,run,profile='allocation')
        register=json.loads((run/'research-inputs.json').read_text(encoding='utf-8'))['evidence_register']
        valuations=[fact for fact in register.values() if fact['kind']=='valuation_measure']
        self.assertEqual(len(valuations),1);self.assertIs(valuations[0]['eligible'],False)

    def test_reproduced_nav_return_does_not_verify_unknown_currency(self):
        rows=[Observation('fixture','fund_unit_nav','000051',day,value,price_basis='unit_nav',currency='unknown')
              for day,value in [('2026-09-29',1.0),('2026-09-30',1.2)]]
        self.store.upsert_observations(rows);self.store.upsert_indicators(series_indicator_rows(rows))
        run=self.root/'nav-currency';prepare_research(self.store,run,profile='allocation')
        register=json.loads((run/'research-inputs.json').read_text(encoding='utf-8'))['evidence_register']
        fact=next(fact for fact in register.values() if fact['record'].get('name')=='return_1period')
        self.assertTrue(fact['record']['lineage']['recomputed_matches'])
        self.assertIs(fact['eligible'],False)



if __name__=='__main__':unittest.main(verbosity=2)
