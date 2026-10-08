import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from market_core.models import Observation
from market_core.store import MarketStore
from market_core.fund_products import assemble_product,verified_nav_currency
from market_core.providers.fund_eastmoney import EastmoneyFundProvider
from market_core.http import HttpClient,DataSourceError
from market_core.fund_clocks import nav_currentness
from market_core.providers.fund_documents import FundDocumentProvider
import hashlib,json
from types import SimpleNamespace
from market_core.workflow import prepare_research,lock_market_view
from market_core.product_dossier import freeze_product_dossier
from market_core.workflow import load_portfolio_after_view
from market_core.portfolio_overlay import map_portfolio


class FundProductTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=MarketStore(Path(self.temp.name)/'fixture.sqlite3')

    def tearDown(self):self.temp.cleanup()

    def doc(self,kind,facts,*,date='2026-06-01',sha='fixture-sha',verified=True):
        return Observation('fixture','fund_document','000051#'+kind,'2026-10-01T00:00:00+00:00',
            {'code':'000051','kind':kind,'name':'fixture A','publication_date':date,'sha256':sha,
             'source_url':'https://example.test/issuer.pdf','facts_verified_against_current_bytes':verified,
             'reviewed_facts':facts},source_url='https://example.test/issuer.pdf')

    def test_identity_currency_can_bind_without_complete_product_approval(self):
        self.store.upsert_observations([self.doc('summary',{'currency':'CNY','share_class':'A','fund_type':'etf_link'})])
        product=assemble_product(self.store,'000051');self.store.upsert_observations([product])
        self.assertTrue(verified_nav_currency(self.store,'000051')['verified'])
        self.assertIs(product.value['selection_ready'],False)
        self.assertEqual(product.value['subscription_status'],'unknown')

    def test_document_revision_invalidates_old_currency_binding(self):
        self.store.upsert_observations([self.doc('summary',{'currency':'CNY'})])
        self.store.upsert_observations([assemble_product(self.store,'000051')])
        self.store.upsert_observations([self.doc('summary',{},sha='changed-sha',verified=False)])
        self.assertEqual(verified_nav_currency(self.store,'000051')['currency'],'unknown')

    def test_same_date_currency_conflict_is_not_silently_resolved(self):
        self.store.upsert_observations([self.doc('summary',{'currency':'CNY'}),self.doc('prospectus',{'currency':'USD'})])
        product=assemble_product(self.store,'000051')
        self.assertEqual(product.value['currency'],'unknown')
        self.assertIn('currency',product.value['field_conflicts'])

    def test_newer_reviewed_charge_base_supersedes_old_unknown(self):
        self.store.upsert_observations([self.doc('summary',{'sales_service_charge_base':'unknown','share_class':'C'},date='2026-03-01'),
             self.doc('prospectus',{'sales_service_charge_base':'previous_C_class_assets','sales_service_fee_annual_fraction':0.0035},date='2026-04-01')])
        product=assemble_product(self.store,'000051')
        self.assertEqual(product.value['fee_terms']['sales_service_charge_base'],'previous_C_class_assets')

    def test_wrong_fund_code_reply_is_rejected_before_nav_storage(self):
        client=HttpClient()
        payload='var fS_code="000217"; var Data_netWorthTrend=[{"x":1790697600000,"y":1.2}];'
        with patch.object(client,'get_text',return_value=(payload,'https://example.test/nav')):
            with self.assertRaisesRegex(DataSourceError,'exact share code'):
                EastmoneyFundProvider(client).fetch_nav_history('000051')

    def test_nonpositive_nav_is_rejected(self):
        client=HttpClient()
        payload='var fS_code="000051"; var Data_netWorthTrend=[{"x":1790697600000,"y":0}];'
        with patch.object(client,'get_text',return_value=(payload,'https://example.test/nav')):
            with self.assertRaises(DataSourceError):EastmoneyFundProvider(client).fetch_nav_history('000051')

    def test_nav_calendar_waits_for_publication_deadline(self):
        product={'nav_calendar_contract':{'verified':True,'valuation_market':'CN_CASH','publication_rule':'next_calendar_day_end'}}
        self.assertEqual(nav_currentness(product,'2026-09-30','2026-10-08T18:00:00+08:00')['status'],'current_publication_window')
        self.assertEqual(nav_currentness(product,'2026-09-30','2026-10-10T10:00:00+08:00')['status'],'stale')

    def test_fund_calendar_does_not_accept_future_valuation(self):
        product={'nav_calendar_contract':{'verified':True,'valuation_market':'CN_CASH','publication_rule':'next_calendar_day_end'}}
        self.assertEqual(nav_currentness(product,'2026-10-08','2026-10-05T18:00:00+08:00')['status'],'unavailable')

    def test_family_bridge_requires_same_call_matching_summary_hash(self):
        root=Path(self.temp.name);summary=b'%PDF-summary';family=b'%PDF-family'
        summary_sha=hashlib.sha256(summary).hexdigest();family_sha=hashlib.sha256(family).hexdigest()
        registry={'funds':{'017641':{'name':'fixture A','manager':'fixture','registry_verified_at':'2026-10-05',
                  'issuer_document_hosts':['example.test'],'documents':[
                    {'kind':'summary','publication_date':'2026-06-01','url':'https://example.test/summary',
                     'reviewed_facts':{'sha256':summary_sha,'facts':{'currency':'CNY'}}},
                    {'kind':'prospectus','publication_date':'2026-06-01','url':'https://example.test/family',
                     'reviewed_facts':{'sha256':family_sha,'facts':{}},
                     'identity_bridge':{'sha256':summary_sha,'share_code':'017641','fund_family_name':'Fixture family'}}]}}}
        path=root/'registry.json';path.write_text(json.dumps(registry),encoding='utf-8');client=HttpClient()
        def reader(handle):
            body=handle.getvalue();text='017641 Fixture family' if body==summary else 'Fixture family'
            return SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda:text)])
        with patch.object(client,'get_bytes',side_effect=[(summary,'https://example.test/summary'),(family,'https://example.test/family')]),patch('pypdf.PdfReader',side_effect=reader):
            rows=FundDocumentProvider(path,root/'docs',client).fetch_evidence('017641')
        self.assertTrue(rows[1].value['identity_bridge_verified'])
        registry['funds']['017641']['documents'][1]['identity_bridge']['sha256']='wrong-hash'
        path.write_text(json.dumps(registry),encoding='utf-8')
        with patch.object(client,'get_bytes',side_effect=[(summary,'https://example.test/summary'),(family,'https://example.test/family')]),patch('pypdf.PdfReader',side_effect=reader):
            with self.assertRaises(DataSourceError):FundDocumentProvider(path,root/'docs',client).fetch_evidence('017641')

    def test_product_dossier_requires_view_seal_and_preserves_it(self):
        root=Path(self.temp.name);run=root/'run';prepare_research(self.store,run,profile='allocation')
        with self.assertRaisesRegex(ValueError,'Lock the independent'):
            freeze_product_dossier(self.store,run,['000051'])
        view=root/'view.json';view.write_text(json.dumps({'market_summary':'No qualified evidence','theses':[],
                          'opportunities':[],'alternatives':['wait'],'waiting_case':'Missing evidence'}),encoding='utf-8')
        lock_market_view(run,view);before=(run/'market-view.json').read_bytes()
        result=freeze_product_dossier(self.store,run,['000051'])
        self.assertIs(result['market_view_unchanged'],True)
        self.assertEqual(before,(run/'market-view.json').read_bytes())
        self.assertEqual(result['readiness'][0]['status'],'incomplete')
        portfolio=root/'positions.json';portfolio.write_text(json.dumps({'authoritative_source':'fixture_user_record',
                      'positions':[{'code':'000051','amount':12345,'amount_basis':'invested_cost'}]}),encoding='utf-8')
        load_portfolio_after_view(run,portfolio);mapping=map_portfolio(run)
        self.assertNotIn('12345',json.dumps(mapping))
        self.assertFalse(mapping['quantitative_weights_verified'])
        self.assertEqual(before,(run/'market-view.json').read_bytes())


if __name__=='__main__':unittest.main(verbosity=2)
