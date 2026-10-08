import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from market_core.fund_holdings import parse_equity_report,look_through_feeder,stored_lookthrough
from market_core.providers.fund_holdings import ChinaAMCHoldingsProvider
from market_core.http import DataSourceError
from market_core.store import MarketStore
from market_core.models import Observation
from market_core.fund_nav import nav_curves,create_fund_nav_chart


def report(feeder=True):
    name='示例股票基金'+('联接基金' if feeder else '')
    code='000051' if feeder else '510330';equity=100 if feeder else 990;fund=800 if feeder else 0;total=1000 if feeder else 1200
    target='2.1.1 目标基金基本情况\n基金主代码 510330\n2.1.2 目标基金产品说明\n' if feeder else ''
    values=[equity,fund,0,0,0,0,100 if feeder else 110,0 if feeder else 100]
    names=['权益投资','基金投资','固定收益投资','贵金属投资','金融衍生品投资','买入返售金融资产','银行存款和结算备付金合计','其他各项资产']
    assets='\n'.join(f'{i+1} {n} {v:.2f} {100*v/total:.2f}' for i,(n,v) in enumerate(zip(names,values)))
    industry='\n'.join(f'{c} 行业{c} '+(f'{equity:.2f} {equity/10:.2f}' if c=='C' else '- -') for c in 'ABCDEFGHIJKLMNOPQRS')
    stocks=f'1 600001 股票甲 100 {equity/2:.2f} {equity/20:.2f}\n2 000002 股票乙 100 {equity/2:.2f} {equity/20:.2f}'
    return name,[f'{name}2026年中期报告\n2026年6月30日\n2.1 基金基本情况\n基金主代码 {code}\n{target}2.2 基金产品说明\n6.1 资产负债表\n单位：人民币元\n本期末\n2026年6月30日\n上年度末\n2025年12月31日\n资产总计 {total:.2f} {total:.2f}\n净资产合计 1000.00 1000.00\n6.2 利润表\n7.1 期末基金资产组合情况\n占基金总资产的比例\n{assets}\n9 合计 {total:.2f} 100.00\n7.2 报告期末按行业分类的股票投资组合\n7.2.1 报告期末按行业分类的境内股票投资组合\n占基金资产净值比例\n{industry}\n合计 {equity:.2f} {equity/10:.2f}\n7.3 期末按公允价值占基金资产净值比例大小排序的股票投资明细\n7.3.1 期末按公允价值占基金资产净值比例大小排序的所有股票投资明细\n数量（股） 公允价值 占基金资产净值比例\n{stocks}\n7.4 报告期内股票投资组合的重大变动\n7.12.1 报告期末按公允价值占基金资产净值比例大小排序的所有基金投资明细\n占基金资产净值比例\n1 示例ETF {fund:.2f} {fund/10:.2f}\n7.13 投资组合报告附注']


def parsed(feeder=True):
    name,pages=report(feeder)
    return parse_equity_report(pages,fund_code='000051' if feeder else '510330',expected_name=name,
        publication_date='2026-08-31',source_url='https://www.chinaamc.com/sample.pdf',document_sha256='a'*64)


class FundHoldingsTests(unittest.TestCase):
    def test_net_asset_denominator_and_direct_indirect_overlap(self):
        f=parsed();t=parsed(False);result=look_through_feeder(f,t)
        self.assertAlmostEqual(t['asset_composition'][0]['reported_percent'],82.5)
        self.assertAlmostEqual(t['asset_composition'][0]['weight_of_net_assets'],.99)
        self.assertAlmostEqual(result['coverage']['security_detail_of_feeder_NAV'],.892)
        self.assertEqual(len(result['securities']),2)
        self.assertAlmostEqual(result['securities'][0]['estimated_weight_of_feeder_NAV'],.446)
        self.assertEqual(len(result['securities'][0]['paths']),2)
        self.assertFalse(result['today_holdings_reconstructed'])
    def test_missing_detail_not_renormalized_and_mixed_dates_remain(self):
        f=parsed();t=parsed(False);t['stocks']=t['stocks'][:1];t['report_date']='2025-12-31'
        r=look_through_feeder(f,t)
        self.assertAlmostEqual(r['coverage']['security_detail_of_feeder_NAV'],.496)
        self.assertLess(r['coverage']['security_detail_of_equity'],1)
        self.assertTrue(r['mixed_report_dates'])
        with self.assertRaisesRegex(ValueError,'identity mismatch'):
            look_through_feeder(f,{**t,'fund_code':'510300'})
    def test_changed_weight_missing_rank_and_wrong_share_refuse(self):
        f=parsed();t=parsed(False);t['stocks'][0]['weight_of_net_assets']=.8
        with self.assertRaisesRegex(ValueError,'Unmatched'):look_through_feeder(f,t)
        name,pages=report()
        for body,error in ((pages[0].replace('2 000002','3 000002'),'ranks'),(pages[0].replace('数量（股）','数量（手）'),'header')):
            with self.assertRaisesRegex(ValueError,error):
                parse_equity_report([body],fund_code='000051',expected_name=name,publication_date='2026-08-31',source_url='https://www.chinaamc.com/sample.pdf',document_sha256='a'*64)
        reversed_header=pages[0].replace('本期末\n2026年6月30日\n上年度末\n2025年12月31日','上年度末\n2025年12月31日\n本期末\n2026年6月30日')
        with self.assertRaisesRegex(ValueError,'Current balance column'):
            parse_equity_report([reversed_header],fund_code='000051',expected_name=name,publication_date='2026-08-31',source_url='https://www.chinaamc.com/sample.pdf',document_sha256='a'*64)
        with self.assertRaisesRegex(ValueError,'Requested share'):
            parse_equity_report(pages,fund_code='510330',expected_name=name,publication_date='2026-08-31',source_url='https://www.chinaamc.com/sample.pdf',document_sha256='a'*64)
        bse=parse_equity_report([pages[0].replace('600001','920136')],fund_code='000051',expected_name=name,
            publication_date='2026-08-31',source_url='https://www.chinaamc.com/sample.pdf',document_sha256='a'*64)
        self.assertEqual(bse['stocks'][0]['identity'],'bj920136')
        shared=pages[0].replace('基金主代码 000051','基金主代码 000051\n下属份额交易代码 000051 005658 022983')
        c=parse_equity_report([shared],fund_code='005658',expected_name=name,publication_date='2026-08-31',
            source_url='https://www.chinaamc.com/sample.pdf',document_sha256='a'*64)
        self.assertEqual(c['fund_code'],'005658');self.assertEqual(c['holdings_scope'],'shared_fund_family_portfolio')
    def test_reported_section_difference_preserved_without_invented_cause(self):
        name,pages=report(False)
        body=pages[0].replace('1 权益投资 990.00','1 权益投资 989.99').replace('8 其他各项资产 100.00','8 其他各项资产 100.01')
        r=parse_equity_report([body],fund_code='510330',expected_name=name,publication_date='2026-08-31',source_url='https://www.chinaamc.com/sample.pdf',document_sha256='a'*64)
        self.assertAlmostEqual(r['industry_vs_asset_composition_gap_CNY'],.01)
        self.assertTrue(r['stock_detail_reconciled']);self.assertEqual(r['stock_detail_reconciliation_gap_CNY'],0)
    def test_cross_layer_share_amount_difference_has_sensitivity_and_date_guard(self):
        f=parsed();t=parsed(False);f['target_funds'][0]['quantity_ETF_shares']=80
        t['total_fund_shares']=200;t['reported_unit_NAV_CNY']=5;t['reported_unit_NAV_decimal_places']=4
        r=look_through_feeder(f,t);b=r['cross_layer_value_bridge']
        self.assertEqual(b['status'],'unresolved_cross_layer_amount_difference')
        self.assertEqual(b['booked_minus_quantity_value_CNY'],400)
        self.assertAlmostEqual(b['quantity_based_equity_of_feeder_NAV_sensitivity'],.496)
        self.assertAlmostEqual(r['coverage']['estimated_CN_listed_equity_of_feeder_NAV'],.892)
        t['report_date']='2025-12-31'
        self.assertEqual(look_through_feeder(f,t)['cross_layer_value_bridge']['status'],'different_report_dates_not_comparable')
    def test_reported_futures_are_separate_from_book_assets_and_short_sign_is_retained(self):
        name,pages=report()
        future='6.4.7.3.2 期末基金持有的期货合约情况\n单位：人民币元\n代码 名称 持仓量（买/卖） 合约市值 公允价值变动\nIF2609\n沪深300期货IF2609合约\n-2 100.00 3.00\n合计 - - - 3.00\n6.4.7.4 买入返售金融资产\n'
        p=parse_equity_report([pages[0].replace('6.2 利润表','6.2 利润表\n'+future)],fund_code='000051',expected_name=name,
            publication_date='2026-08-31',source_url='https://www.chinaamc.com/sample.pdf',document_sha256='a'*64)
        r=look_through_feeder(p,parsed(False))
        self.assertEqual(p['futures_contracts'][0]['position_contracts_signed'],-2)
        self.assertAlmostEqual(r['futures_exposure']['known_disclosed_contract_subtotal_fraction_of_feeder_NAV'],-.1)
        self.assertIsNone(r['futures_exposure']['estimated_signed_contract_market_exposure_fraction_of_feeder_NAV'])
        self.assertAlmostEqual(r['coverage']['security_detail_of_feeder_NAV'],.892)
        self.assertFalse(r['futures_exposure']['added_to_stock_or_asset_weights'])
    def test_stored_reader_excludes_future_publication_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'x.sqlite3';s=MarketStore(db)
            for code,v in (('000051',parsed()),('510330',parsed(False))):
                s.upsert_observations([Observation('chinaamc_disclosed_holdings','fund_holdings',code,'2026-06-30',v,
                    publication='2026-08-31',quality='primary_report_parsed_with_explicit_reconciliation')])
            with self.assertRaisesRegex(ValueError,'No supported'):stored_lookthrough(s,'000051',as_of='2026-07-01')
            readonly=MarketStore(db,read_only=True)
            self.assertAlmostEqual(stored_lookthrough(readonly,'000051',as_of='2026-10-06')['coverage']['security_detail_of_feeder_NAV'],.892)
    def test_dynamic_report_selection_ignores_future_notice_and_binds_sources(self):
        name,pages=report()
        class Client:
            archive=None;last_response_receipt=None
            def __init__(self):self.calls=[]
            def get_text(self,url):
                self.calls.append(url)
                if 'publishGgList' in url:
                    return f'<a href="/c/2026-08-31/one.shtml">{name}2026年中期报告</a><a href="/c/2099-08-31/two.shtml">{name}2099年中期报告</a><a href="/c/2026-10-31/quarter.shtml">{name}2026年第3季度报告</a>',url
                return '<a href="/sample.pdf">报告</a>',url
            def get_bytes(self,url):self.calls.append(url);return b'%PDF-fixture',url
            def source_receipts(self):return [{'source_test_call':self.calls[-1]}]
            def bind_rows(self,rows,refs):
                for row in rows:row.source_receipts=refs
                return rows
        client=Client()
        with tempfile.TemporaryDirectory() as tmp,patch('pypdf.PdfReader',return_value=SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda:pages[0])])):
            row=ChinaAMCHoldingsProvider(tmp,client=client).fetch_evidence('000051',as_of='2026-10-06')[0]
            self.assertEqual(row.value['report_date'],'2026-06-30');self.assertEqual(len(row.source_receipts),3)
            self.assertFalse(row.value['issuer_report_selection']['historical_PIT_verified'])
            self.assertEqual(row.value['issuer_report_selection']['newer_unparsed_quarterly_reports'],[])
            self.assertTrue(all('2099' not in x for x in client.calls))
            later=ChinaAMCHoldingsProvider(tmp,client=client).fetch_evidence('000051',as_of='2026-11-01')[0]
            self.assertEqual(len(later.value['issuer_report_selection']['newer_unparsed_quarterly_reports']),1)
            with self.assertRaisesRegex(DataSourceError,'domain'):ChinaAMCHoldingsProvider._host('https://evilchinaamc.com/x.pdf')
    def test_nav_prefix_is_causal_and_has_no_invented_price_or_volume(self):
        from datetime import date,timedelta
        rows=[{'provider':'fixture','dataset':'fund_unit_nav','identity':'000051','as_of':(date(2026,1,1)+timedelta(days=i)).isoformat(),
            'currency':'CNY','price_basis':'unit_nav_price_return','value':1+i/1000} for i in range(100)]
        original=nav_curves(rows);changed=copy.deepcopy(rows)
        for row in changed[70:]:row['value']*=2
        self.assertEqual(original[:70],nav_curves(changed)[:70])
        self.assertNotIn('volume',original[-1]);self.assertNotIn('open',original[-1])
        self.assertAlmostEqual(original[19]['boll_middle'],1.0095)
        rows[-1]['identity']='005658'
        with self.assertRaisesRegex(ValueError,'exact NAV'):nav_curves(rows)
    def test_invalid_or_duplicate_nav_is_refused(self):
        row={'provider':'fixture','dataset':'fund_unit_nav','identity':'000051','as_of':'2026-06-30',
            'currency':'CNY','price_basis':'unit_nav_price_return','value':1.1}
        for value in (0,float('nan'),True):
            with self.assertRaisesRegex(ValueError,'finite'):nav_curves([{**row,'value':value}])
        with self.assertRaisesRegex(ValueError,'unique'):nav_curves([row,row])
        with self.assertRaisesRegex(ValueError,'currency'):nav_curves([{**row,'currency':'unknown'}])
    def test_nav_chart_freezes_inputs_and_refuses_overwrite(self):
        from datetime import date,timedelta
        import hashlib
        rows=[{'provider':'fixture','dataset':'fund_unit_nav','identity':'000051','as_of':(date(2026,1,1)+timedelta(days=i)).isoformat(),
            'currency':'CNY','price_basis':'unit_nav_price_return','value':1+i/1000,'raw':{'fund_name':'示例联接A'}} for i in range(100)]
        store=SimpleNamespace(get_observations=lambda *a,**k:rows if k.get('limit',0)>=len(rows) else rows[-1:])
        with tempfile.TemporaryDirectory() as tmp,patch('market_core.fund_nav.verified_nav_currency',return_value={'verified':True,'currency':'CNY'}):
            out=Path(tmp)/'chart';result=create_fund_nav_chart(store,'000051',out)
            self.assertEqual(result['NAV_rows'],100);self.assertFalse(result['final_investment_decision_complete'])
            frozen=(out/'nav-inputs.json').read_bytes();self.assertEqual(hashlib.sha256(frozen).hexdigest(),result['input_sha256'])
            with self.assertRaisesRegex(ValueError,'new fund'):create_fund_nav_chart(store,'000051',out)
            self.assertEqual((out/'nav-inputs.json').read_bytes(),frozen)


if __name__=='__main__':unittest.main()
