import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date,timedelta
from pathlib import Path
from unittest.mock import patch

from market_core.candidate_research import normalize_candidates,research_candidates
from market_core.models import Bar
from market_core.store import MarketStore


class CandidateResearchTests(unittest.TestCase):
    def rows(self,symbol,market='US',n=130):
        start=date(2026,1,1)
        return [Bar('fixture',symbol,'1d',(start+timedelta(days=i)).isoformat(),100,102,99,100+i/100,
                    volume=10000,currency={'CN':'CNY','US':'USD','HK':'HKD'}[market],volume_unit='share',
                    price_basis='provider_split_adjusted_close' if market!='CN' else 'unadjusted',
                    session='completed_regular_session') for i in range(n)]

    def test_exact_identity_kind_and_selection_reason_required(self):
        basic={'market':'CN','kind':'stock','identity':'600276','selection_reason':'independent mechanism'}
        self.assertEqual(normalize_candidates([basic])[0]['identity'],'sh600276')
        for changed in ({**basic,'kind':'ETF'},{**basic,'selection_reason':''},{**basic,'market':'XX'}):
            with self.assertRaises(ValueError):normalize_candidates([changed])
        with self.assertRaisesRegex(ValueError,'Duplicate'):normalize_candidates([basic,basic])
        hk={'market':'HK','kind':'stock','identity':'00700.HK','selection_reason':'independent mechanism'}
        self.assertEqual(normalize_candidates([hk])[0]['identity'],'0700.HK')

    def test_readonly_native_price_packets_keep_benchmark_currency_and_no_personal_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=MarketStore(root/'x.sqlite3')
            store.upsert_bars(self.rows('XLK')+self.rows('SPY')+self.rows('0700.HK','HK')+self.rows('^HSI','HK'))
            readonly=MarketStore(store.path,read_only=True)
            candidates=[{'market':'US','kind':'ETF','identity':'XLK','selection_reason':'tech mechanism'},
                        {'market':'HK','kind':'stock','identity':'0700.HK','selection_reason':'local mechanism'}]
            result=research_candidates(readonly,candidates,root/'out',collect=False)
            self.assertEqual([r['source']['currency'] for r in result['results']],['USD','HKD'])
            self.assertFalse(result['portfolio_used']);self.assertFalse(result['final_investment_decisions_complete'])
            packet=json.loads((root/'out/01-XLK/candidate-evidence.json').read_text(encoding='utf-8'))
            self.assertEqual(packet['regional_broad_benchmark_comparison']['benchmark_identity'],'SPY')
            self.assertEqual(packet['technical_context']['state'],'measured')
            self.assertTrue((root/'out/01-XLK/chart.html').exists())
            with self.assertRaisesRegex(ValueError,'new candidate'):research_candidates(readonly,candidates,root/'out',collect=False)

    def test_one_failure_does_not_drop_other_candidates_or_claim_fundamental_research(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=MarketStore(root/'x.sqlite3');store.upsert_bars(self.rows('XLK')+self.rows('SPY'))
            rows=[{'market':'US','kind':'stock','identity':'MISSING','selection_reason':'one mechanism'},
                  {'market':'US','kind':'ETF','identity':'XLK','selection_reason':'another mechanism'}]
            result=research_candidates(MarketStore(store.path,read_only=True),rows,root/'out',collect=False)
            self.assertEqual(result['results'][0]['status'],'candidate_evidence_incomplete')
            self.assertEqual(result['results'][1]['status'],'candidate_price_evidence_ready')
            packet=json.loads((root/'out/02-XLK/candidate-evidence.json').read_text(encoding='utf-8'))
            self.assertFalse(packet['fundamental_due_diligence_complete'])

    def test_unfinished_future_and_unverified_foreign_bars_do_not_enter_chart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=MarketStore(root/'x.sqlite3');rows=self.rows('XLK')
            rows+=[replace(rows[-1],timestamp='2026-10-06'),replace(rows[-1],timestamp='2026-10-05',session='completion_unverified')]
            store.upsert_bars(rows+self.rows('SPY'))
            request=[{'market':'US','kind':'ETF','identity':'XLK','selection_reason':'mechanism'}]
            with patch('market_core.candidate_research.completed_cash_session',return_value='2026-10-05'):
                result=research_candidates(MarketStore(store.path,read_only=True),request,root/'out',collect=False)
            self.assertEqual(result['results'][0]['daily_bars'],130)

    def test_off_exchange_exact_share_routes_to_fund_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            request=[{'market':'CN','kind':'off_exchange_fund','identity':'005658','selection_reason':'wrapper mechanism'}]
            with patch('market_core.candidate_research.resolve_fund_identifier',return_value='005658'), \
                 patch('market_core.candidate_research.create_fund_research',return_value={'status':'fund_research_evidence_stage'}) as fund:
                result=research_candidates(object(),request,Path(tmp)/'out',collect=False)
            self.assertFalse(fund.call_args.kwargs['collect'])
            self.assertEqual(result['results'][0]['status'],'fund_research_evidence_stage')

    def test_readonly_stock_metadata_cannot_be_relabelled_as_ETF(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=MarketStore(root/'x.sqlite3')
            store.upsert_bars([replace(b,raw={'instrument_type':'EQUITY'}) for b in self.rows('MU')]+self.rows('SPY'))
            request=[{'market':'US','kind':'ETF','identity':'MU','selection_reason':'one hypothesis'}]
            result=research_candidates(MarketStore(store.path,read_only=True),request,root/'out',collect=False)
            self.assertEqual(result['results'][0]['status'],'candidate_evidence_incomplete')
