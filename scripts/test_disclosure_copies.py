import hashlib,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from market_core.http import HttpClient,DataSourceError
from market_core.providers.fund_documents import FundDocumentProvider
from market_core.store import MarketStore
from market_core.fund_products import assemble_product,verified_nav_currency


class DisclosureCopyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.summary=b'%PDF-copy';self.family=b'%PDF-issuer-family'
        self.summary_sha=hashlib.sha256(self.summary).hexdigest();self.family_sha=hashlib.sha256(self.family).hexdigest()
        self.registry={'funds':{'012552':{'name':'Fixture A','manager':'fixture','registry_verified_at':'2026-10-06',
            'issuer_document_hosts':['issuer.example.test'],'disclosure_copy_hosts':['distributor.example.test'],
            'documents':[
                {'kind':'summary','publication_date':'2026-06-26','url':'https://distributor.example.test/summary',
                 'source_origin':'distributor_disclosure_copy','reviewed_facts':{'sha256':self.summary_sha,
                     'facts':{'share_class':'A','currency':'CNY','fund_type':'etf_link'}}},
                {'kind':'prospectus','publication_date':'2026-03-07','url':'https://issuer.example.test/family',
                 'reviewed_facts':{'sha256':self.family_sha,'facts':{'management_charge_base':'previous_net_assets_excluding_ETF'}},
                 'identity_bridge':{'sha256':self.summary_sha,'share_code':'012552','fund_family_name':'Fixture family'}}]}}}
        self.path=self.root/'registry.json';self.client=HttpClient()

    def tearDown(self):self.temp.cleanup()

    def fetch(self,title='Fixture family (A 类份额) 基金代码A 012552'):
        self.path.write_text(json.dumps(self.registry),encoding='utf-8')
        def reader(handle):
            text=title if handle.getvalue()==self.summary else 'Fixture family prospectus'
            return SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda:text)])
        with (patch.object(self.client,'get_bytes',side_effect=[
             (self.summary,'https://distributor.example.test/summary'),(self.family,'https://issuer.example.test/family')]),
             patch('pypdf.PdfReader',side_effect=reader)):
            return FundDocumentProvider(self.path,self.root/'docs',self.client).fetch_evidence('012552')

    def test_copy_and_issuer_bridge_keep_distinct_document_and_identity_origins(self):
        rows=self.fetch()
        self.assertFalse(rows[0].value['issuer_origin_verified'])
        self.assertEqual(rows[0].quality,'disclosure_copy_reviewed_bytes')
        self.assertTrue(rows[1].value['issuer_origin_verified'])
        self.assertFalse(rows[1].value['identity_basis_issuer_origin_verified'])
        self.assertEqual(rows[1].value['identity_dependencies'][0]['source_origin'],'distributor_disclosure_copy')
        store=MarketStore(self.root/'store.sqlite3');store.upsert_observations(rows)
        product=assemble_product(store,'012552');store.upsert_observations([product])
        contract=verified_nav_currency(store,'012552')
        self.assertTrue(contract['verified'])
        self.assertFalse(contract['source']['issuer_origin_verified'])
        self.assertEqual(contract['source']['source_origin'],'distributor_disclosure_copy')
        self.assertFalse(product.value['selection_ready'])

    def test_copy_host_cannot_be_claimed_as_issuer_host(self):
        del self.registry['funds']['012552']['documents'][0]['source_origin']
        with self.assertRaisesRegex(DataSourceError,'reviewed source registry'):self.fetch()

    def test_C_summary_containing_family_A_code_cannot_establish_A_share(self):
        with self.assertRaisesRegex(DataSourceError,'different share class'):
            self.fetch('Fixture family (C类份额) 基金代码012552 基金代码C012553')

    def test_copy_needs_class_specific_code_not_only_family_code(self):
        with self.assertRaisesRegex(DataSourceError,'class-specific code'):
            self.fetch('Fixture family (A类份额) 基金代码012552 基金代码A012553')

    def test_missing_review_class_cannot_bypass_copy_identity_check(self):
        del self.registry['funds']['012552']['documents'][0]['reviewed_facts']['facts']['share_class']
        with self.assertRaisesRegex(DataSourceError,'class-specific code'):
            self.fetch('Fixture family (C类份额) 基金代码012552 基金代码C012553')

    def test_unreviewed_copy_does_not_verify_NAV_currency(self):
        self.registry['funds']['012552']['documents'][0]['reviewed_facts']['sha256']='old-content-hash'
        self.registry['funds']['012552']['documents']=self.registry['funds']['012552']['documents'][:1]
        rows=self.fetch();store=MarketStore(self.root/'store.sqlite3');store.upsert_observations(rows)
        store.upsert_observations([assemble_product(store,'012552')])
        self.assertFalse(verified_nav_currency(store,'012552')['verified'])

    def test_fee_coverage_does_not_call_missing_transaction_bases_complete(self):
        facts=self.registry['funds']['012552']['documents'][0]['reviewed_facts']['facts']
        facts.update(management_fee_annual_fraction=0.005,custody_fee_annual_fraction=0.001,
                     management_charge_base='prior_net_assets_excluding_ETF',custody_charge_base='prior_net_assets_excluding_ETF',
                     sales_service_fee_annual_fraction=0)
        rows=self.fetch();store=MarketStore(self.root/'store.sqlite3');store.upsert_observations(rows)
        product=assemble_product(store,'012552')
        self.assertEqual(product.value['fee_coverage']['ongoing_contract_missing'],[])
        self.assertIn('redemption_charge_base',product.value['fee_contract_missing'])
        self.assertIn('subscription_fee_calculation',product.value['fee_contract_missing'])
        self.assertFalse(product.value['fee_coverage']['platform_discount_verified'])

    def test_empty_transaction_tier_arrays_remain_missing(self):
        facts=self.registry['funds']['012552']['documents'][0]['reviewed_facts']['facts']
        facts.update(subscription_fee_tiers=[],redemption_fee_tiers=[])
        rows=self.fetch();store=MarketStore(self.root/'store.sqlite3');store.upsert_observations(rows)
        missing=assemble_product(store,'012552').value['fee_contract_missing']
        self.assertIn('subscription_fee_tiers',missing)
        self.assertIn('redemption_fee_tiers',missing)

    def test_parent_fund_code_cannot_identify_another_subordinate_share(self):
        self.registry['funds']['012552']['documents'][0]['source_origin']='issuer_host'
        self.registry['funds']['012552']['issuer_document_hosts'].append('distributor.example.test')
        with self.assertRaisesRegex(DataSourceError,'subordinate share code'):
            self.fetch(title='Fixture family 人民币C) 基金代码 012552 下属基金代码 654321')

    def test_currency_title_share_does_not_inherit_A_from_a_family_code(self):
        self.registry['funds']['012552']['documents'][0]['source_origin']='issuer_host'
        self.registry['funds']['012552']['issuer_document_hosts'].append('distributor.example.test')
        with self.assertRaisesRegex(DataSourceError,'different share class'):
            self.fetch(title='Fixture family 人民币C) 基金代码 012552')


if __name__=='__main__':unittest.main()
