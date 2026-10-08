import tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from market_core.issuer_document_followup import fetch_catalogued_documents


class IssuerDocumentFollowupTests(unittest.TestCase):
    def test_exact_issuer_filter_and_received_document_remains_unreviewed(self):
        with tempfile.TemporaryDirectory() as tmp:
            saved=[];runs=[];calls=[]
            store=SimpleNamespace(path=Path(tmp)/'data.sqlite3',response_vault=None,
                get_observations=lambda kind,key,**kwargs:[{'value':{'symbol':'sh600276','announcement_id':'123'}}],
                upsert_observations=lambda rows:saved.extend(rows) or len(rows),
                record_run=lambda *args,**kwargs:runs.append((args,kwargs)))
            document=SimpleNamespace(to_dict=lambda:{'value':{'content_reviewed':False}})
            provider=SimpleNamespace(name='fixture',client=SimpleNamespace(archive=None,retries=1),
                fetch_document=lambda row:calls.append(row) or document)
            with patch('market_core.issuer_document_followup.CninfoAnnouncementsProvider',return_value=provider):
                result=fetch_catalogued_documents(store,'600276',['123'])
                self.assertEqual(result['documents'][0]['status'],'original_document_received')
                self.assertFalse(result['documents'][0]['economic_content_reviewed'])
                self.assertFalse(result['all_material_content_reviewed'])
                self.assertEqual(len(saved),1)
                result=fetch_catalogued_documents(store,'600519',['123'])
                self.assertEqual(result['documents'][0]['status'],'missing_exact_issuer_catalogue_entry')
                self.assertEqual(len(calls),1)

    def test_invalid_ids_fail_before_provider_or_network(self):
        with patch('market_core.issuer_document_followup.CninfoAnnouncementsProvider') as provider:
            for ids in [[],['1','1'],['bad'],[1],[{}],['1']*21]:
                with self.assertRaises(ValueError):fetch_catalogued_documents(None,'600276',ids)
            provider.assert_not_called()

    def test_failed_fetch_has_no_document_and_does_not_claim_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs=[];store=SimpleNamespace(path=Path(tmp)/'data.sqlite3',response_vault=None,
                get_observations=lambda *args,**kwargs:[{'value':{'symbol':'sh600276','announcement_id':'123'}}],
                upsert_observations=lambda rows:self.fail('Failed retrieval must not create a document'),
                record_run=lambda *args,**kwargs:runs.append((args,kwargs)))
            def failed(row):raise RuntimeError('public source unavailable')
            provider=SimpleNamespace(name='fixture',client=SimpleNamespace(),fetch_document=failed)
            with patch('market_core.issuer_document_followup.CninfoAnnouncementsProvider',return_value=provider):
                result=fetch_catalogued_documents(store,'600276',['123'])
            self.assertEqual(result['documents'][0]['status'],'failed')
            self.assertFalse(result['all_material_content_reviewed'])
            self.assertEqual(runs[0][0][-2],'failed')
