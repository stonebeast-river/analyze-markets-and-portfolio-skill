import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from market_core.stock_request import stock_route,research_stock_request


class StockRequestTests(unittest.TestCase):
    def test_native_routes_and_conflicts(self):
        self.assertEqual(stock_route('NVDA'),('US','NVDA'))
        self.assertEqual(stock_route('nvda'),('US','NVDA'))
        self.assertEqual(stock_route('HK:00700'),('HK','0700.HK'))
        self.assertEqual(stock_route('00700.hk'),('HK','0700.HK'))
        self.assertEqual(stock_route('SH600276'),('CN','SH600276'))
        self.assertEqual(stock_route('恒瑞医药'),('CN','恒瑞医药'))
        with self.assertRaisesRegex(ValueError,'disagree'):stock_route('US:NVDA','HK')

    def test_foreign_request_keeps_market_and_does_not_apply_cn_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'out'
            def price(store,records,directory,**kwargs):
                self.assertEqual(records[0]['market'],'US');self.assertEqual(records[0]['kind'],'stock')
                self.assertEqual(kwargs['lookback_days'],1830);self.assertFalse(kwargs['collect'])
                root.mkdir();return {'results':[{'status':'candidate_evidence_incomplete'}]}
            with patch('market_core.stock_request.research_candidates',side_effect=price), \
                 patch('market_core.stock_request.create_stock_research') as domestic:
                result=research_stock_request(object(),'NVDA',root,collect=False)
            domestic.assert_not_called()
            self.assertFalse(result['domestic_execution_rules_applied'])
            self.assertFalse(result['final_investment_decision_complete'])
            self.assertTrue((root/'stock-request.json').is_file())

    def test_domestic_options_are_not_silently_applied_to_foreign_sizes(self):
        with patch('market_core.stock_request.research_candidates') as collector:
            with self.assertRaisesRegex(ValueError,'CNY'):research_stock_request(object(),'NVDA','unused',risk_budget_CNY=100)
            with self.assertRaisesRegex(ValueError,'provider'):research_stock_request(object(),'NVDA','unused',provider='baostock')
            collector.assert_not_called()

    def test_foreign_stock_metadata_cannot_be_unknown_or_relabel_an_ETF(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for i,metadata in enumerate([{}, {'symbol':'NVDA','instrumentType':'ETF','exchangeTimezoneName':'America/New_York'},
                                         {'symbol':'NVDA','instrumentType':'EQUITY','exchangeTimezoneName':'Asia/Hong_Kong'},
                                         {'symbol':'NVDA','instrumentType':'EQUITY','exchangeTimezoneName':'America/New_York'}]):
                directory=root/str(i);directory.mkdir()
                (directory/'daily-inputs.json').write_text(json.dumps([{'raw':{'metadata':metadata}}]),encoding='utf-8')
                with patch('market_core.stock_request.research_candidates',return_value={'results':[{'status':'candidate_price_evidence_ready','directory':str(directory)}]}):
                    if i<3:
                        with self.assertRaisesRegex(ValueError,'metadata'):research_stock_request(object(),'NVDA',directory,collect=False)
                    else:
                        result=research_stock_request(object(),'NVDA',directory,collect=False)
                        self.assertEqual(result['source_instrument_metadata']['instrumentType'],'EQUITY')

    def test_domestic_request_retains_existing_collector(self):
        with patch('market_core.stock_request.resolve_stock_identifier',return_value='sh600276'), \
             patch('market_core.stock_request.create_stock_research',return_value={'status':'domestic'}) as call:
            result=research_stock_request(object(),'600276','unused',collect=False,horizon=40)
        self.assertEqual(result['status'],'domestic')
        self.assertEqual(call.call_args.kwargs['horizon'],40)
        self.assertFalse(call.call_args.kwargs['collect'])
