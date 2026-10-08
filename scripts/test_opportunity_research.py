import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from market_core.models import Bar
from market_core.opportunity_research import prepare_opportunity_research


class ReadOnlyInputs:
    def __init__(self):
        self.reads = []

    def get_bars(self, identity, interval, **kwargs):
        self.reads.append((identity, kwargs))
        hk = identity.endswith('.HK') or identity == '^HSI'
        return [Bar('yahoo_public_chart', identity, interval, '2026-10-0'+str(day),
                    100, 102, 99, 100+day, currency='HKD' if hk else 'USD',
                    price_basis='provider_split_adjusted_close') for day in (5, 6)]

    def get_observations(self, dataset, **kwargs):
        if dataset != 'macro_series':
            raise AssertionError('Unexpected dataset or personal inputs')
        return []


class OpportunityResearchTests(unittest.TestCase):
    def prepare(self, store, root, **kwargs):
        with patch('market_core.opportunity_research.scan_market', return_value={'status':'research_scan'}), \
             patch('market_core.opportunity_research.sector_price_scan', return_value={'rows':[]}):
            return prepare_opportunity_research(store, {}, root, **kwargs)

    def test_exchange_clocks_keep_HK_close_and_exclude_US_intraday(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ReadOnlyInputs()
            self.prepare(store, Path(tmp)/'report', as_of='2026-10-06T15:00:00Z')
            packet = json.loads((Path(tmp)/'report/opportunity-inputs.json').read_text(encoding='utf-8'))
            inputs = json.loads((Path(tmp)/'report/global-price-inputs.json').read_text(encoding='utf-8'))
            self.assertEqual(inputs['SPY'][-1]['timestamp'], '2026-10-05')
            self.assertEqual(inputs['^HSI'][-1]['timestamp'], '2026-10-06')
            self.assertEqual(packet['global_session_audit']['SPY']['excluded_uncompleted_bars'], ['2026-10-06'])
            self.assertTrue(packet['global_session_audit']['^HSI']['completed_session_aligned'])
            self.assertEqual(inputs['SPY'][-1]['currency'], 'USD')
            self.assertEqual(inputs['2800.HK'][-1]['currency'], 'HKD')
            self.assertEqual(len(store.reads), 15)

    def test_evidence_packet_is_read_only_sealed_and_not_a_recommendation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'report'
            result = self.prepare(ReadOnlyInputs(), root, as_of='2026-10-06T15:00:00Z')
            self.assertFalse(result['personal_portfolio_used'])
            self.assertFalse(result['complete_autonomous_recommendation_verified'])
            seals = json.loads((root/'artifact-seal.json').read_text(encoding='utf-8'))
            self.assertEqual(len(seals), 3)
            for name, digest in seals.items():
                self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(), digest)
            before = (root/'opportunity-inputs.json').read_bytes()
            with self.assertRaisesRegex(ValueError, 'new opportunity'):
                self.prepare(ReadOnlyInputs(), root, as_of='2026-10-06T15:00:00Z')
            self.assertEqual((root/'opportunity-inputs.json').read_bytes(), before)

    def test_unknown_calendar_cannot_claim_current_completed_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'report'
            self.prepare(ReadOnlyInputs(), root, as_of='2027-01-04T15:00:00Z')
            packet = json.loads((root/'opportunity-inputs.json').read_text(encoding='utf-8'))
            audit = packet['global_session_audit']['SPY']
            self.assertFalse(audit['calendar_coverage_verified'])
            self.assertFalse(audit['completed_session_aligned'])

    def test_historical_evaluation_refuses_live_refresh_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'report'
            with self.assertRaisesRegex(ValueError, 'Historical cutoff'):
                self.prepare(ReadOnlyInputs(), root, as_of='2026-10-06T15:00:00Z', refresh_global=True)
            self.assertFalse(root.exists())

    def test_ambiguous_cutoff_timezone_refuses_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'report'
            with self.assertRaisesRegex(ValueError,'timezone'):
                self.prepare(ReadOnlyInputs(),root,as_of='2026-10-06T15:00:00')
            self.assertFalse(root.exists())
