import copy,json,math,tempfile,unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
from market_core.models import Bar
from market_core.stock_technicals import bollinger,technical_series,technical_context
from market_core.directional_forecast import analogue_at,chronological_forecast
from market_core.stock_research import create_stock_research,collect_stock_inputs,entry_scenarios,expected_closed_session,resolve_stock_identifier,verify_stock_research
from market_core.store import MarketStore
from market_core.stock_conditions import chart_condition_plan,evaluate_chart_conditions

def sample_bars(n=900):
    from datetime import date,timedelta
    start=date(2022,1,1);bars=[]
    for i in range(n):
        close=100*math.exp(.0002*i+.04*math.sin(i/17)+.01*math.sin(i/3))
        bars.append(Bar('fixture','sh600519','1d',(start+timedelta(days=i)).isoformat(),close*.998,close*1.015,close*.985,close,
                        volume=1000+100*math.sin(i/9),currency='CNY',volume_unit='share',price_basis='unadjusted'))
    return bars

class StockResearchTests(unittest.TestCase):
    def test_boll_population_std_and_warmup(self):
        b=bollinger([1,2,3,4],period=4)
        self.assertEqual(b['middle'][:3],[None]*3);self.assertEqual(b['middle'][-1],2.5)
        self.assertAlmostEqual(b['upper'][-1],2.5+2*math.sqrt(1.25))
        self.assertAlmostEqual(b['lower'][-1],2.5-2*math.sqrt(1.25))
    def test_future_prices_cannot_change_old_features_forecast_or_training_cutoff(self):
        bars=sample_bars();rows=technical_series(bars);a=analogue_at(rows,700)
        altered=copy.deepcopy(bars)
        for b in altered[701:]:b.open*=3;b.close*=3;b.high*=3;b.low*=3
        new=technical_series(altered)
        self.assertEqual(rows[:701],new[:701]);self.assertEqual(a,analogue_at(new,700))
        self.assertLessEqual(a['latest_training_outcome_date'],rows[700]['date'])
        self.assertTrue(all(r['outcome_date']<=a['forecast_as_of'] for r in a['analogues']))
    def test_short_validation_withholds_probabilities_and_preserves_nonoverlapping_outcomes(self):
        r=chronological_forecast(technical_series(sample_bars(650)),horizon=20)
        self.assertFalse(r['latest']['probability_publication_allowed']);self.assertIsNone(r['latest']['published_up_probability'])
        records=r['evaluation']['records']
        self.assertTrue(all(a['outcome_date']<=b['signal_date'] for a,b in zip(records,records[1:])))
        self.assertTrue(all(r['latest_training_outcome_date']<=r['signal_date'] for r in records))
    def test_invalid_volume_or_mixed_basis_is_refused(self):
        bars=sample_bars(130);bars[-1].volume=-1
        with self.assertRaisesRegex(ValueError,'volume'):technical_series(bars)
        bars[-1].volume=1;bars[-1].price_basis='qfq'
        with self.assertRaisesRegex(ValueError,'one daily source'):technical_series(bars)
    def test_intraday_uses_previous_completed_daily_session(self):
        self.assertEqual(expected_closed_session('2026-10-08T10:30:00+08:00'),'2026-09-30')
        self.assertEqual(expected_closed_session('2026-10-08T16:00:00+08:00'),'2026-10-08')
    def test_breakdown_has_no_reversed_pullback_zone(self):
        context={'state':'measured','atr14':2,'support_previous20':100,'resistance_previous20':120,'close':95}
        plan=entry_scenarios(context,{})
        self.assertFalse(any('entry_zone' in r for r in plan['scenarios']))
        self.assertFalse(plan['final_investment_decision_complete'])
    def test_report_freezes_real_inputs_and_refuses_overwrite(self):
        from market_core.models import Observation
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);s=MarketStore(root/'data.sqlite3');bars=sample_bars(650);s.upsert_bars(bars)
            s.upsert_observations([
                Observation('fixture','announcement_catalogue_entry','sh600519|123','2024-01-01',{'symbol':'sh600519','announcement_id':'123','title':'Annual report'}),
                Observation('fixture','issuer_announcement_document','sh600519|123','2024-01-01',{'symbol':'sh600519','announcement_id':'123','title':'Annual report','local_text':'original.txt'}),
                Observation('fixture','issuer_announcement_document','sh600276|124','2024-01-01',{'symbol':'sh600276','announcement_id':'124','title':'Annual report'})])
            out=root/'stock';result=create_stock_research(s,'sh600519',out,collect=False,provider='fixture')
            self.assertEqual(result['daily_bars'],650)
            self.assertTrue((out/'chart.html').is_file());self.assertTrue((out/'daily-inputs.json').is_file())
            self.assertFalse(result['complete_stock_decision_verified'])
            data=json.loads((out/'stock-research.json').read_text(encoding='utf-8'))
            self.assertEqual(len(data['announcement_catalogue_records']),1)
            self.assertEqual([r['value']['local_text'] for r in data['primary_document_records']],['original.txt'])
            self.assertFalse(data['daily_history_current']);self.assertFalse(data['directional_forecast']['latest']['probability_publication_allowed'])
            verified=verify_stock_research(out)
            self.assertEqual(verified['status'],'ok');self.assertTrue(verified['conditional_opinion_replayed'])
            original=(out/'stock-research.json').read_bytes();seal_file=out/'artifact-seal.json';original_seal=seal_file.read_bytes()
            changed=copy.deepcopy(data);changed['investment_opinion']['action']='build_next_session_conditionally'
            (out/'stock-research.json').write_text(json.dumps(changed),encoding='utf-8')
            import hashlib
            seal=json.loads(original_seal);seal['files']['stock-research.json']=hashlib.sha256((out/'stock-research.json').read_bytes()).hexdigest()
            seal_file.write_text(json.dumps(seal),encoding='utf-8')
            self.assertIn('investment_opinion',verify_stock_research(out)['failures'])
            (out/'stock-research.json').write_bytes(original);seal_file.write_bytes(original_seal)
            raw=(out/'daily-inputs.json').read_bytes();(out/'daily-inputs.json').write_bytes(raw+b' ')
            self.assertEqual(verify_stock_research(out)['status'],'failed')
            (out/'daily-inputs.json').write_bytes(raw)
            with self.assertRaisesRegex(ValueError,'new stock research directory'):create_stock_research(s,'sh600519',out,collect=False,provider='fixture')
    def test_stock_name_resolves_exact_quote_identity_without_network(self):
        from market_core.models import Quote
        with tempfile.TemporaryDirectory() as tmp:
            s=MarketStore(Path(tmp)/'data.sqlite3');s.upsert_quotes([Quote('fixture','sh600519','2026-09-30',name='贵州茅台')])
            s.upsert_quotes([Quote('fixture','sh600590','2099-09-30',name='贵州茅台')])
            self.assertEqual(resolve_stock_identifier(s,'贵州茅台',allow_network=False),'sh600519')
            with self.assertRaisesRegex(ValueError,'not been resolved'):resolve_stock_identifier(s,'不存在的股票',allow_network=False)

    def test_benchmark_inputs_replay_and_resealed_false_relative_return_refuses(self):
        from dataclasses import replace
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=MarketStore(root/'data.sqlite3');bars=sample_bars(180)
            store.upsert_bars(bars+[replace(b,symbol='sh000300') for b in bars])
            out=root/'stock';create_stock_research(store,'sh600519',out,collect=False,provider='fixture')
            data=json.loads((out/'stock-research.json').read_text(encoding='utf-8'))
            self.assertEqual(len(data['benchmark_comparisons']),3)
            self.assertTrue(all(r['relative_return']==0 for r in data['benchmark_comparisons']))
            verified=verify_stock_research(out)
            self.assertEqual(verified['status'],'ok');self.assertTrue(verified['benchmark_comparisons_replayed'])
            frozen=json.loads((out/'benchmark-inputs.json').read_text(encoding='utf-8'))
            self.assertTrue(all(r['symbol']=='sh000300' for r in frozen))
            data['benchmark_comparisons'][0]['relative_return']=.9
            target=out/'stock-research.json';target.write_text(json.dumps(data),encoding='utf-8')
            seal_path=out/'artifact-seal.json';seal=json.loads(seal_path.read_text(encoding='utf-8'))
            seal['files'][target.name]=hashlib.sha256(target.read_bytes()).hexdigest()
            seal_path.write_text(json.dumps(seal),encoding='utf-8')
            self.assertIn('benchmark_comparisons',verify_stock_research(out)['failures'])

    def test_paper_execution_replays_from_frozen_history_and_detects_false_performance(self):
        from market_core.models import Observation
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);s=MarketStore(root/'data.sqlite3');bars=sample_bars(650);s.upsert_bars(bars)
            s.upsert_observations([Observation('fixture','issuer_announcement_audit','sh600519','2026-09-30',
                {'status':'complete_catalogue_window','start_date':bars[-120].timestamp,'end_date':bars[-1].timestamp})])
            out=root/'stock';create_stock_research(s,'sh600519',out,collect=False,provider='fixture')
            verified=verify_stock_research(out)
            self.assertEqual(verified['status'],'ok');self.assertTrue(verified['paper_execution_replayed'])
            data_file=out/'stock-research.json';data=json.loads(data_file.read_text(encoding='utf-8'))
            self.assertEqual(data['paper_execution_sample']['warmup_daily_bars'],530)
            data['paper_execution_sample']['strategy_result']['return']+=.5
            data_file.write_text(json.dumps(data),encoding='utf-8')
            seal_file=out/'artifact-seal.json';seal=json.loads(seal_file.read_text(encoding='utf-8'))
            seal['files']['stock-research.json']=hashlib.sha256(data_file.read_bytes()).hexdigest()
            seal_file.write_text(json.dumps(seal),encoding='utf-8')
            self.assertIn('paper_execution_sample',verify_stock_research(out)['failures'])

    def test_operational_conditions_wait_for_new_bar_and_check_source(self):
        context={'state':'measured','as_of':'2026-09-30','atr14':2,'support_previous20':90,'resistance_previous20':110,'close':100}
        source={'symbol':'sh600519','provider':'fixture','interval':'1d','price_basis':'unadjusted','currency':'CNY'}
        plan=chart_condition_plan(context,source)
        self.assertEqual(plan['conditions'][0]['predicates'][0]['next_review'],'2026-10-08T15:10:00+08:00')
        rows=[{'date':'2026-09-30','close':111,'volume_ratio5':1.3,'macd_histogram':1}]
        review=evaluate_chart_conditions(plan,rows,source)
        self.assertEqual(review['results'][0]['state'],'pending')
        rows.append({'date':'2026-10-08','close':111,'volume_ratio5':1.3,'macd_histogram':2})
        self.assertEqual(evaluate_chart_conditions(plan,rows,source,as_of='2026-10-08T16:00:00+08:00')['results'][0]['state'],'passed')
        self.assertEqual(evaluate_chart_conditions(plan,rows,source,as_of='2026-10-06T16:00:00+08:00')['results'][0]['state'],'unknown')
        wrong={**source,'provider':'other'}
        self.assertEqual(evaluate_chart_conditions(plan,rows,wrong,as_of='2026-10-08T16:00:00+08:00')['results'][0]['state'],'unknown')
        self.assertFalse(review['trade_authorized'])

    def test_future_observations_and_publications_are_excluded_from_stock_dossier(self):
        from market_core.models import Observation
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);s=MarketStore(root/'data.sqlite3');s.upsert_bars(sample_bars(650))
            s.upsert_observations([
                Observation('fixture','stock_order_size_flow_1d','sh600519','2099-01-01',{'main_net':100}),
                Observation('fixture','industry_classification','sh600519','2026-01-01',{'industry':'future'},publication='2099-01-01'),
                Observation('fixture','industry_classification','sh600519','2026-01-01',{'industry':'known'},revision='known')])
            create_stock_research(s,'sh600519',root/'report',collect=False,provider='fixture')
            d=json.loads((root/'report/stock-research.json').read_text(encoding='utf-8'))
            self.assertEqual(d['available_vendor_flows'],[])
            self.assertEqual([r['value']['industry'] for r in d['industry_classification']],['known'])

    def test_collection_links_failed_response_without_rejecting_prior_quote(self):
        from market_core.models import Quote,Observation
        from market_core.http import HttpClient
        from market_core.responses import ResponseVault
        with tempfile.TemporaryDirectory() as tmp:
            s=MarketStore(Path(tmp)/'data.sqlite3');s.response_vault=ResponseVault(Path(tmp)/'responses')
            quote_client=HttpClient();minute_client=HttpClient()
            def response(client,url,body):
                vault=client.archive;event=vault.store(vault.request_id(url,{}),url,url,body,body,headers={},status=200)
                client.last_response_receipt=event;return event
            def quotes(_):
                response(quote_client,'https://example.test/quote',b'actual-quote-fixture')
                return quote_client.bind_rows([Quote('tencent_web_quote','sh600519','2026-09-30',last=100,currency='CNY')])
            def minutes(*args,**kwargs):
                response(minute_client,'https://example.test/bad-minute',b'unusable-minute-fixture')
                raise ValueError('malformed minute payload')
            quote_provider=SimpleNamespace(name='tencent_web_quote',client=quote_client,fetch_quotes=quotes)
            minute_provider=SimpleNamespace(name='tencent_public_intraday',client=minute_client,fetch_bars=minutes)
            bars=sample_bars(3)
            sdk=SimpleNamespace(name='baostock_free_history',fetch_bars=lambda *a,**k:bars,
                fetch_daily_metrics=lambda *a,**k:[Observation('baostock_free_history','cn_daily_valuation_liquidity','sh600519','2026-09-30',{'pe_ttm':20})],
                fetch_financials=lambda *a,**k:[Observation('baostock_free_history','financials','sh600519','2026-06-30',{})])
            flow=SimpleNamespace(name='eastmoney_provider_derived',fetch_stock_flow=lambda *a,**k:[])
            audit=Observation('cninfo_primary_announcements','issuer_announcement_audit','sh600519','2026-09-30',{'status':'complete_catalogue_window'})
            announcer=SimpleNamespace(name='cninfo_primary_announcements',fetch_catalogue=lambda *a,**k:([],audit))
            with patch('market_core.stock_research.TencentProvider',return_value=quote_provider),patch('market_core.stock_research.BaoStockProvider',return_value=sdk),patch('market_core.stock_research.TencentIntradayProvider',return_value=minute_provider),patch('market_core.stock_research.EastmoneyProvider',return_value=flow),patch('market_core.stock_research.CninfoAnnouncementsProvider',return_value=announcer):
                collect_stock_inputs(s,'sh600519')
            with s.connect() as db:
                runs=[dict(r) for r in db.execute('SELECT dataset,status,details_json FROM provider_runs')]
            minute=next(r for r in runs if r['dataset'].startswith('stock_research_minutes'))
            events=json.loads(minute['details_json'])['response_receipts']
            self.assertTrue(any(r['status']=='response_rejected_by_parser_or_contract' for r in events))
            self.assertTrue(all('quote' not in r.get('request_url','') for r in events))
            qrun=next(r for r in runs if r['dataset'].startswith('stock_research_quote'))
            self.assertTrue(json.loads(qrun['details_json'])['response_receipts'])
            self.assertEqual(s.source_trace('quote','sh600519')['status'],'verified')

if __name__=='__main__':unittest.main()
