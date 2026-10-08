import copy,json,hashlib,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from datetime import date,timedelta,datetime,timezone
from market_core.fund_costs import forward_share_cost_comparison,subscription_cost
from market_core.fund_fee_contracts import load_fee_contract
from market_core.fund_research import resolve_fund_identifier,matched_price_comparisons,create_fund_research,collect_fund_inputs,specialized_underlying_action
from market_core.providers.fund_chinaamc_status import parse_business_table
from market_core.providers.csi_valuation import CsiValuationProvider
from market_core.http import DataSourceError
from market_core.models import Observation,Bar
from market_core.store import MarketStore
from market_core.fund_nav import create_fund_nav_chart


def fee_fixture():
    path=Path(__file__).parents[1]/'assets/fund-fee-contracts.json'
    c=copy.deepcopy(json.loads(path.read_text(encoding='utf-8'))['families']['chinaamc-csi300-feeder'])
    c['verified_against_current_source_bytes']=True
    return c


class FundResearchTests(unittest.TestCase):
    def test_nonstock_underlying_routes_do_not_imply_equity_price_signals(self):
        self.assertEqual(specialized_underlying_action('bond_ETF'),'review_rates_credit_duration_and_funding')
        self.assertEqual(specialized_underlying_action('fof'),'review_child_fund_allocation_and_overlap')
        self.assertEqual(specialized_underlying_action('money_market'),'review_cash_yields_liquidity_and_fees')

    def test_bond_collection_continues_into_dated_official_rate_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);registry=root/'sources.json';registry.write_text('{"funds":{}}',encoding='utf-8')
            product={'provider':'fixture','as_of':'2026-06-30','source_url':'https://example.test/source',
                     'value':{'fund_name':'Bond A','fund_type':'bond','underlying_identity':'unknown','target_etf':'unknown'}}
            store=SimpleNamespace(path=root/'x.sqlite3',response_vault=SimpleNamespace(events=[]),
                get_observations=lambda dataset,*args,**kwargs:[product] if dataset=='fund_product' else [],
                upsert_observations=lambda rows:len(rows),record_run=lambda *args,**kwargs:None)
            nav=SimpleNamespace(name='fixture_NAV',client=None,fetch_evidence=lambda *args,**kwargs:[])
            rates=SimpleNamespace(name='fixture_rates',client=None,fetch_evidence=lambda:[])
            with patch('market_core.fund_research.verified_nav_currency',return_value={'currency':'CNY'}), \
                 patch('market_core.fund_research.EastmoneyFundProvider',return_value=nav), \
                 patch('market_core.fund_research.ChinaBondCurveProvider',return_value=rates), \
                 patch('market_core.fund_research.YahooProvider') as foreign:
                result=collect_fund_inputs(store,'007714',registry_path=registry)
            foreign.assert_not_called()
            self.assertTrue(any(r['step']=='fund_rates_context:007714' for r in result))
    def test_unknown_composite_proxy_is_not_sent_as_a_foreign_ticker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);registry=root/'sources.json';registry.write_text('{"funds":{}}',encoding='utf-8')
            product={'provider':'fixture','as_of':'2026-06-30','source_url':'https://example.test/source',
                     'value':{'fund_name':'Global active C','underlying_identity':'unknown','target_etf':'unknown'}}
            store=SimpleNamespace(path=root/'x.sqlite3',response_vault=SimpleNamespace(events=[]),
                get_observations=lambda dataset,*args,**kwargs:[product] if dataset=='fund_product' else [],
                upsert_observations=lambda rows:len(rows),record_run=lambda *args,**kwargs:None)
            nav=SimpleNamespace(name='fixture_NAV',client=None,fetch_evidence=lambda *args,**kwargs:[])
            with patch('market_core.fund_research.verified_nav_currency',return_value={'currency':'CNY'}), \
                 patch('market_core.fund_research.EastmoneyFundProvider',return_value=nav), \
                 patch('market_core.fund_research.YahooProvider') as foreign:
                runs=collect_fund_inputs(store,'021277',registry_path=registry)
            foreign.assert_not_called()
            self.assertFalse(any('unknown' in r['step'] for r in runs))

    def test_short_horizon_C_cost_and_long_horizon_A_discount_are_conditional(self):
        c=fee_fixture()
        short=forward_share_cost_comparison(c,holding_fee_age_days=90,A_subscription_rate_scenario=.0012)
        self.assertEqual(short['lower_relative_cost_code'],'005658')
        self.assertAlmostEqual(short['classes'][0]['ending_comparison_cash'],10000/1.0012*.995)
        self.assertAlmostEqual(short['classes'][1]['ending_comparison_cash'],10000*(1-.003/365)**90)
        long=forward_share_cost_comparison(c,holding_fee_age_days=730,A_subscription_rate_scenario=.0012,one_year_tier_reached=True)
        self.assertEqual(long['lower_relative_cost_code'],'000051')
        boundary=forward_share_cost_comparison(c,holding_fee_age_days=365)
        self.assertIsNone(boundary['lower_relative_cost_code']);self.assertFalse(short['historical_NAV_fees_charged_again'])
        self.assertFalse(short['personal_portfolio_used']);self.assertFalse(short['platform_A_rate_verified'])
    def test_cost_bands_leap_year_and_conflicting_fee_age(self):
        c=fee_fixture();tiers=c['classes']['A']['subscription_tiers']
        self.assertAlmostEqual(subscription_cost(1000000,tiers)['applied_fraction'],.009)
        self.assertEqual(subscription_cost(10000000,tiers)['fee'],1000)
        leap=forward_share_cost_comparison(c,holding_fee_age_days=60,start_date='2028-01-01')
        self.assertAlmostEqual(leap['classes'][1]['sales_service_factor'],(1-.003/366)**60)
        with self.assertRaisesRegex(ValueError,'conflicts'):
            forward_share_cost_comparison(c,holding_fee_age_days=6,one_year_tier_reached=True)
        with self.assertRaisesRegex(ValueError,'finite'):subscription_cost(float('nan'),tiers)
    def test_dated_business_header_and_dash_do_not_become_current_availability(self):
        headers=['产品份额代码','产品份额简称','申购-当日可否交易','赎回-当日可否交易','转换转入-当日可否交易','转换转出-当日可否交易','定期定额申购-当日可否交易','限制-当日可否交易']
        page='<h1>华夏基金旗下基金开放状态一览表</h1><div>更新日期:2026-04-22</div><table><tr>'+''.join('<th>'+x+'</th>' for x in headers)+'</tr><tr>'+''.join('<td>'+x+'</td>' for x in ['005658','华夏沪深300ETF联接C','开放','开放','开放','开放','开放','-'])+'</tr></table>'
        r=parse_business_table(page,['005658'])[0]
        self.assertEqual(r['source_update_date'],'2026-04-22');self.assertFalse(r['current_subscription_verified'])
        self.assertTrue(r['restriction_dash_is_not_unlimited_today'])
        with self.assertRaisesRegex(DataSourceError,'header'):
            parse_business_table(page.replace('申购-当日可否交易','错误业务栏目'),['005658'])
        with self.assertRaisesRegex(DataSourceError,'absent'):parse_business_table(page,['000051'])
    def test_name_resolution_uses_exact_public_share_identity_and_excludes_future(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=MarketStore(Path(tmp)/'x.sqlite3')
            s.upsert_observations([Observation('fixture','instrument_listing','005658','2026-01-01',{'name':'示例C','scope':'funds'}),
                Observation('fixture','instrument_listing','000051','2099-01-01',{'name':'示例C','scope':'funds'})])
            self.assertEqual(resolve_fund_identifier(s,'示例C',allow_network=False),'005658')
            self.assertEqual(resolve_fund_identifier(s,'000051',allow_network=False),'000051')
    def test_price_comparison_uses_exact_dates_and_does_not_claim_policy_tracking(self):
        rows=[{'as_of':(date(2026,1,1)+timedelta(days=i)).isoformat(),'value':1+i/1000,'currency':'CNY'} for i in range(70)]
        bars=[Bar('fixture','sh000300','1d',r['as_of'],100,101,99,100,volume=1,currency='CNY',price_basis='unadjusted') for r in rows]
        r=matched_price_comparisons(rows,bars)
        self.assertEqual(len(r),3);self.assertFalse(r[0]['actual_policy_benchmark_tracking_measure'])
        self.assertAlmostEqual(r[0]['fund_unit_NAV_return'],rows[-1]['value']/rows[-6]['value']-1)
        self.assertEqual(matched_price_comparisons(rows,bars[:-1]),[])
    def test_csi_same_source_percentiles_keep_raw_PE_field_and_reject_wrong_index(self):
        data=[{'indexCode':'000300','tradeDate':(date(2026,1,1)+timedelta(days=i)).strftime('%Y%m%d'),'peg':10+i/100} for i in range(100)]
        class Client:
            def get_json(self,url):return {'code':200,'data':data},url
            def bind_rows(self,rows):return rows
        r=CsiValuationProvider(Client()).fetch_evidence('000300',end_date='2026-10-06')[0]
        self.assertEqual(r.value['PE_TTM'],10.99);self.assertEqual(r.value['source_field'],'peg')
        self.assertFalse(r.value['automatic_buy_level_supported']);self.assertFalse(r.value['historical_vintage_availability_verified'])
        self.assertTrue(r.value['date_audit']['nonweekday_source_rows'])
        self.assertFalse(r.value['date_audit']['full_historical_exchange_calendar_verified'])
        data[-1]['indexCode']='000905'
        with self.assertRaisesRegex(DataSourceError,'different index'):CsiValuationProvider(Client()).fetch_evidence('000300',end_date='2026-10-06')
    def test_fee_loader_refuses_numeric_edit_even_with_matching_original_passages(self):
        c=fee_fixture();pages=['']*199
        for r in c['reviewed_passages']:pages[r['page']-1]+=r['text']+'\n'
        pages[0]=c['fund_family_name']+'\n000051 005658'
        pages[142]+='本基金的管理费0.15%年费率\n本基金的托管费0.05%的年费率\nA类、Y类不收取销售服务费\n若为负数,则E取0'
        pages[95]+='7天以内 1.5%\n赎回时份额持有不满7天的，收取1.5%的赎回费'
        body=b'%PDF-synthetic-fee-contract';digest=hashlib.sha256(body).hexdigest();c['source']['sha256']=digest
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/(digest+'.pdf')).write_bytes(body);reg=root/'registry.json'
            reg.write_text(json.dumps({'families':{'fixture':c}},ensure_ascii=False),encoding='utf-8')
            reader=SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda text=t:text) for t in pages])
            with patch('pypdf.PdfReader',return_value=reader):
                self.assertTrue(load_fee_contract('000051',root,reg)['verified_against_current_source_bytes'])
                c['classes']['C']['sales_service_annual_fraction']=.03
                reg.write_text(json.dumps({'families':{'fixture':c}},ensure_ascii=False),encoding='utf-8')
                with self.assertRaisesRegex(ValueError,'source rates'):load_fee_contract('000051',root,reg)
    def test_one_fund_packet_excludes_future_NAV_and_incomplete_daily_bar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);s=MarketStore(root/'x.sqlite3');start=date(2026,1,1);rows=[];bars=[]
            for i in range(273):
                day=(start+timedelta(days=i)).isoformat();price=100+i/100
                rows.append(Observation('fixture','fund_unit_nav','005658',day,1+i/1000,currency='CNY',price_basis='unit_nav_price_return'))
                bars.append(Bar('fixture','sh000300','1d',day,price,price+1,price-1,price,volume=1000,currency='CNY',price_basis='unadjusted'))
            rows.append(Observation('fixture','fund_unit_nav','005658','2099-01-01',999,currency='CNY',price_basis='unit_nav_price_return'))
            bars.append(Bar('fixture','sh000300','1d','2026-10-08',200,202,198,200,volume=1000,currency='CNY',price_basis='unadjusted'))
            s.upsert_observations(rows);s.upsert_bars(bars)
            s.upsert_observations([Observation('chinaamc_official','fund_product','005658','2026-01-01',
                {'fund_name':'测试C','currency':'CNY','underlying_identity':'sh000300','field_sources':{'currency':'https://www.chinaamc.com/fund/005658/'}},source_url='https://www.chinaamc.com/fund/005658/')])
            fixed_clock=SimpleNamespace(now=lambda *a,**k:datetime(2026,10,8,3,0,tzinfo=timezone.utc))
            with patch('market_core.fund_research.datetime',fixed_clock),patch('market_core.fund_research.expected_closed_session',return_value='2026-09-30'),patch('market_core.fund_research.load_fee_contract',side_effect=ValueError('fixture not reviewed')):
                create_fund_research(s,'005658',root/'packet',collect=False)
            packet=json.loads((root/'packet/fund-research.json').read_text(encoding='utf-8'))
            self.assertEqual(packet['NAV_chart']['NAV_rows'],273)
            self.assertEqual(packet['underlying']['source_session'],'2026-09-30')
            self.assertFalse(packet['full_fund_investment_decision_complete'])
            self.assertFalse(packet['personal_portfolio_used'])
            self.assertTrue(any(x['task']=='exact_share_fee_comparison' for x in packet['material_followups']))


if __name__=='__main__':unittest.main()
