import hashlib,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from market_core.http import HttpClient,DataSourceError
from market_core.providers.issuer_financials import IssuerFinancialProvider
from market_core.models import Observation
from market_core.store import MarketStore
from market_core.workflow import prepare_research,read_prepared
from market_core.research import evidence_pack


class PrimaryFinancialTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.body=b'%PDF-financial-fixture'
        sha=hashlib.sha256(self.body).hexdigest()
        self.pages=['公司代码600519 FixtureCompany 2026年半年度报告 报告期2026年1月1日至2026年6月30日',
                    '合并利润表 单位：元 币种：人民币 项目 2026年半年度 2025年半年度\n'
                    '五、净利润（净亏损以“-”号填列） 100.00 80.00\n'
                    '少数股东损益 10.00 5.00\n归母净利润 90.00 75.00']
        self.entry={'identity':'sh600519','company_name':'FixtureCompany','period_start':'2026-01-01','period_end':'2026-06-30',
             'period_type':'H1','period_months':6,'publication_date':'2026-08-15','publication_precision':'date_only',
             'publication_date_source':'https://example.test/list','source_url':'https://example.test/report.pdf',
             'approved_hosts':['example.test'],'reviewed_sha256':sha,'audited':False,'contexts':[],
             'reviewed_fields':[{'name':'net_profit_total','source_label':'净利润','reported_decimal':'100.00','unit':'CNY_yuan',
                'page':2,'accounting_scope':'consolidated_including_noncontrolling_interests','period_kind':'flow_YTD',
                'table_schema':'consolidated_income','row_label':'五、净利润（净亏损以“-”号填列）',
                'prior_reported_decimal':'80.00','prior_basis':'2025-01-01_to_2025-06-30'}]}
        self.registry={'reports':{'sh600519|2026-06-30':self.entry}}

    def tearDown(self):self.temp.cleanup()

    def fetch(self):
        path=self.root/'sources.json';path.write_text(json.dumps(self.registry),encoding='utf-8')
        client=HttpClient()
        with (patch.object(client,'get_bytes',return_value=(self.body,'https://example.test/report.pdf')),
              patch('pypdf.PdfReader',return_value=SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda t=t:t) for t in self.pages]))):
            return IssuerFinancialProvider(path,self.root/'documents',client).fetch_evidence('sh600519','2026-06-30')

    def test_primary_fields_are_eligible_without_promoting_raw_vendor_record(self):
        rows=self.fetch();s=MarketStore(self.root/'data.sqlite3');s.upsert_observations(rows)
        raw=Observation('vendor','financials','sh600519','2026-06-30',{'netProfit':'100'},publication='2026-08-15',
                        quality='provider_financials_units_unverified')
        s.upsert_observations([raw]);run=self.root/'run';prepare_research(s,run,profile='allocation')
        _,inputs,_=read_prepared(run)
        facts=[f for f in inputs['evidence_register'].values() if f['kind']=='issuer_financial']
        self.assertEqual(len(facts),2)
        self.assertTrue(next(f['eligible'] for f in facts if f['record']['dataset']=='financials_primary'))
        self.assertFalse(next(f['eligible'] for f in facts if f['record']['dataset']=='financials'))

    def test_changed_PDF_bytes_cannot_keep_old_reviewed_financial_fields(self):
        self.body=b'%PDF-revised-financial-fixture';rows=self.fetch()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0].quality,'primary_document_needs_review')

    def test_wrong_issuer_code_or_report_period_is_rejected(self):
        self.pages[0]=self.pages[0].replace('600519','600000')
        with self.assertRaisesRegex(DataSourceError,'identity mismatch'):self.fetch()
        self.pages[0]='公司代码600519 FixtureCompany 2025年半年度报告 2025年1月1日至2025年6月30日'
        with self.assertRaisesRegex(DataSourceError,'period does not match'):self.fetch()

    def test_wrong_value_or_unit_is_rejected_before_financial_storage(self):
        self.entry['reviewed_fields'][0]['reported_decimal']='101'
        with self.assertRaisesRegex(DataSourceError,'value missing'):self.fetch()
        self.entry['reviewed_fields'][0].update(reported_decimal='100',unit='percent')
        with self.assertRaisesRegex(DataSourceError,'metric/unit'):self.fetch()

    def test_date_only_report_does_not_establish_historical_publication_time(self):
        rows=self.fetch();s=MarketStore(self.root/'data.sqlite3');s.upsert_observations(rows)
        pack=evidence_pack(s,'sh600519',question='valuation',point_in_time=True)
        self.assertFalse(pack['point_in_time_verified'])
        self.assertFalse(any(r['dataset']=='financials_primary' for r in pack['observations']))
        self.assertTrue(any('publication_not_established:financials_primary' in m for m in pack['missing']))

    def test_same_page_other_row_and_reversed_columns_cannot_be_promoted(self):
        f=self.entry['reviewed_fields'][0]
        f.update(reported_decimal='10.00',prior_reported_decimal='5.00')
        with self.assertRaisesRegex(DataSourceError,'selected current column'):self.fetch()
        f.update(reported_decimal='80.00',prior_reported_decimal='100.00')
        with self.assertRaisesRegex(DataSourceError,'selected current column'):self.fetch()

    def test_wrong_accounting_scope_period_and_statement_headers_are_rejected(self):
        f=self.entry['reviewed_fields'][0]
        f['accounting_scope']='attributable_to_parent_shareholders'
        with self.assertRaisesRegex(DataSourceError,'accounting scope'):self.fetch()
        f['accounting_scope']='consolidated_including_noncontrolling_interests';f['period_kind']='flow_TTM'
        with self.assertRaisesRegex(DataSourceError,'period kind'):self.fetch()
        f['period_kind']='flow_YTD';f['prior_basis']='2025-12-31'
        with self.assertRaisesRegex(DataSourceError,'comparison period'):self.fetch()
        f['prior_basis']='2025-01-01_to_2025-06-30';self.pages[1]=self.pages[1].replace('合并利润表','母公司利润表')
        with self.assertRaisesRegex(DataSourceError,'statement column headers'):self.fetch()

    def test_evidence_reports_verified_fields_without_promoting_raw_or_H1_to_TTM(self):
        s=MarketStore(self.root/'data.sqlite3');s.upsert_observations(self.fetch())
        s.upsert_observations([Observation('vendor','financials','sh600519','2026-06-30',
            {'unit_state':'requires_primary_field_unit_verification'},quality='provider_financials_units_unverified'),
            Observation('vendor','cn_daily_valuation_liquidity','sh600519','2026-09-30',{'pe_ttm':20})])
        pack=evidence_pack(s,'sh600519',question='valuation')
        self.assertEqual(pack['financial_coverage']['primary_fields_usable'],1)
        self.assertEqual(pack['financial_coverage']['primary_fields'][0]['period_months'],6)
        self.assertNotIn('financial_field_units_verification',pack['missing'])
        self.assertIn('valuation_TTM_denominator_reconciliation',pack['missing'])
        self.assertEqual(pack['status'],'incomplete')
        self.assertIs(pack['financial_coverage']['raw_vendor_records'][0]['whole_record_verified'],False)

    def test_primary_record_without_semantic_row_proof_does_not_clear_field_gap(self):
        rows=self.fetch()
        for f in rows[-1].value['fields']:f.pop('semantic_verification')
        s=MarketStore(self.root/'data.sqlite3');s.upsert_observations(rows)
        pack=evidence_pack(s,'sh600519',question='valuation')
        self.assertEqual(pack['financial_coverage']['primary_fields_usable'],0)
        self.assertIn('primary_financial_semantic_row_review',pack['missing'])
        run=self.root/'no-semantic-proof';prepare_research(s,run,profile='allocation')
        _,inputs,_=read_prepared(run)
        fact=next(f for f in inputs['evidence_register'].values() if f['record'].get('dataset')=='financials_primary')
        self.assertIs(fact['eligible'],False)


if __name__=='__main__':unittest.main()
