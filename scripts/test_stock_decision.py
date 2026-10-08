import copy,tempfile,unittest,math,json
from pathlib import Path
from unittest.mock import patch
from market_core.stock_decision import decide_stock
from market_core.stock_execution import paper_stock_strategy
from market_core.models import Bar
from market_core.http import HttpClient
from market_core.responses import ResponseVault

class StockDecisionTests(unittest.TestCase):
    def facts(self,growth):
        return {'primary_fields':[{'identity':'sh600519','unit':'CNY_yuan','period_kind':'flow_YTD','name':name,'usable':True,'period_end':'2026-06-30','value':100*(1+growth),'prior_reported_decimal':'100'} for name in ('net_profit_parent','operating_revenue')]}
    def test_supported_breakout_can_build_or_add_without_fixed_waiting(self):
        context={'trend':'upward_trend','price_phase':'breakout','volume_ratio_previous5':1.5,'support_previous20':90}
        events={'catalogue_window_complete':True,'reviewed_events':[],'upcoming_material_catalysts':[]}
        fresh=decide_stock(context,self.facts(.12),events,symbol='sh600519',position_state='unheld')
        held=decide_stock(context,self.facts(.12),events,symbol='sh600519',position_state='held')
        self.assertEqual(fresh['action'],'build_next_session_conditionally');self.assertEqual(held['action'],'add_conditionally')
        self.assertEqual(fresh['directional_judgment'],held['directional_judgment'])
        self.assertAlmostEqual(sum(t['fraction'] for t in fresh['plan']['tranches']),1)
        self.assertFalse(fresh['trade_authorized']);self.assertFalse(fresh['statistical_probability_used'])
    def test_declining_trend_and_profit_oppose_addition(self):
        result=decide_stock({'trend':'downward_trend','price_phase':'range_or_trend'},self.facts(-.03),{'reviewed_events':[]},symbol='sh600519',position_state='held')
        self.assertEqual(result['action'],'do_not_add');self.assertTrue(result['counter_evidence'])
        self.assertFalse(result['user_buy_preference_affects_confidence'])
    def test_risk_veto_overrides_supported_buy_and_invalid_budget_refuses(self):
        context={'trend':'upward_trend','price_phase':'breakout','volume_ratio_previous5':2}
        events={'catalogue_window_complete':True,'reviewed_events':[{'decision_veto':True}]}
        self.assertEqual(decide_stock(context,self.facts(.2),events,symbol='sh600519',position_state='held')['action'],'review_reduce')
        for budget in (-1,0,float('nan'),float('inf'),True,'1000'):
            with self.assertRaisesRegex(ValueError,'Risk budget'):
                decide_stock(context,self.facts(.2),events,symbol='sh600519',risk_budget_CNY=budget)
    def test_warmup_permits_first_period_signal_and_no_fills_is_cash(self):
        from datetime import date,timedelta
        bars=[]
        for i in range(70):
            p=100 if i<60 else 120
            bars.append(Bar('fixture','sh600519','1d',(date(2026,1,1)+timedelta(days=i)).isoformat(),p,p+2,p-2,p,
                volume=20000 if i==60 else 10000,currency='CNY',price_basis='unadjusted'))
        result=paper_stock_strategy(bars[60:],warmup_bars=bars[:60],side_cost_fraction=0,slippage_fraction=0)
        self.assertEqual(result['signals'][0]['date'],bars[60].timestamp)
        self.assertEqual(result['fills'][0]['date'],bars[61].timestamp)
        no_trades=paper_stock_strategy(bars[:60])
        self.assertEqual(no_trades['fills_count'],0)
        self.assertEqual(no_trades['strategy_result']['return'],0)
        self.assertTrue(no_trades['zero_fills_is_cash_holding_not_predictive_advantage'])
    def test_credible_early_setup_is_assessed_without_forcing_wait_or_auto_buy(self):
        events={'catalogue_window_complete':True,'reviewed_events':[],'upcoming_material_catalysts':[{'event_date':'2026-10-20'}]}
        result=decide_stock({'trend':'mixed_or_range','price_phase':'compressed_range'},self.facts(.1),events,symbol='sh600519')
        self.assertEqual(result['action'],'assess_early_entry');self.assertEqual(result['plan']['tranches'],[])
        self.assertTrue(result['independent_final_judgment_required'])
    def test_stale_data_and_unverified_finance_cannot_qualify_purchase(self):
        context={'trend':'upward_trend','price_phase':'breakout','volume_ratio_previous5':2}
        self.assertEqual(decide_stock(context,self.facts(.1),{'catalogue_window_complete':True},symbol='sh600519',current=False)['action'],'refresh_required')
        finance=self.facts(.1)
        for f in finance['primary_fields']:f['usable']=False
        self.assertEqual(decide_stock(context,finance,{'catalogue_window_complete':True},symbol='sh600519')['action'],'independent_assessment_required')
        finance=self.facts(.1)
        for f in finance['primary_fields']:f['identity']='sz000858'
        self.assertEqual(decide_stock(context,finance,{'catalogue_window_complete':True},symbol='sh600519')['action'],'independent_assessment_required')
    def test_dividend_entitlement_uses_record_date_and_not_cum_dividend_double_count(self):
        bars=[Bar('fixture','sh600519','1d',f'2026-06-{day:02d}',100,102,98,100,volume=10000,currency='CNY',price_basis='unadjusted') for day in (24,25,26,29)]
        bars[2].open=90;bars[2].high=92;bars[2].low=88;bars[2].close=90
        bars[3].open=90;bars[3].high=92;bars[3].low=88;bars[3].close=90
        dividend={'record_date':'2026-06-25','ex_date':'2026-06-26','payment_date':'2026-06-29','cash_per_share_CNY':10}
        result=paper_stock_strategy(bars,initial_cash=100000,side_cost_fraction=0,slippage_fraction=0,dividends=[dividend])
        self.assertEqual(result['passive_curve'][1]['equity'],100000)
        self.assertEqual(result['passive_curve'][2]['equity'],100000)
        self.assertEqual(result['passive_curve'][3]['equity'],100000)
    def test_signal_cannot_fill_on_its_own_bar_and_lots_costs_are_applied(self):
        bars=[]
        for i in range(85):
            price=100 if i<60 else 120
            bars.append(Bar('fixture','sh600519','1d',f'2026-{1+i//28:02d}-{1+i%28:02d}',price,price+2,price-2,price,
                volume=20000 if i==60 else 10000,currency='CNY',price_basis='unadjusted'))
        result=paper_stock_strategy(bars,initial_cash=1000000,holding_bars=2,side_cost_fraction=.001,slippage_fraction=.001)
        buys=[r for r in result['fills'] if r['side']=='buy'];self.assertTrue(buys)
        self.assertGreater(buys[0]['date'],result['signals'][0]['date']);self.assertEqual(buys[0]['quantity']%100,0)
        self.assertGreater(buys[0]['fee'],0)
        sells=[r for r in result['fills'] if r['side']=='sell'];self.assertTrue(sells);self.assertGreater(sells[0]['date'],buys[0]['date'])
    def test_post_body_is_in_cache_identity_and_credentials_are_not_archived(self):
        from types import SimpleNamespace
        class Response:
            status=200;headers={}
            def __init__(self,body):self.body=body
            def read(self,*args):return self.body
            def geturl(self):return 'https://example.test/query'
            def __enter__(self):return self
            def __exit__(self,*args):pass
        with tempfile.TemporaryDirectory() as tmp:
            client=HttpClient(retries=0,archive=ResponseVault(Path(tmp)/'responses'))
            with patch('urllib.request.urlopen',return_value=Response(b'{"rows":[]}')) as open_request:
                client.post_form_json('https://example.test/query',{'page':'1'});first=client.source_receipts()[0]['request_id']
                self.assertEqual(open_request.call_args[0][0].get_method(),'POST')
                client.post_form_json('https://example.test/query',{'page':'2'});second=client.source_receipts()[0]['request_id']
            self.assertNotEqual(first,second)
            with patch('urllib.request.urlopen',return_value=Response(b'{"api_key":"private-fixture"}')):
                client.post_form_json('https://example.test/query',{'api_key':'private-fixture'})
            self.assertEqual(client.source_receipts(),[])

if __name__=='__main__':unittest.main()
