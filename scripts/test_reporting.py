import json
import tempfile
import unittest
from pathlib import Path

from market_core.store import MarketStore
from market_core.workflow import prepare_research, lock_market_view, load_portfolio_after_view
from market_core.product_dossier import freeze_product_dossier
from market_core.portfolio_overlay import map_portfolio
from market_core.reporting import export_report


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = MarketStore(self.root / 'fixture.sqlite3')
        self.run = self.root / 'run'
        prepare_research(self.store, self.run, profile='allocation')
        path = self.root / 'view.json'
        path.write_text(json.dumps({'market_summary': 'No qualified evidence', 'theses': [],
                        'opportunities': [], 'alternatives': [], 'waiting_case': 'Wait for evidence'}), encoding='utf-8')
        lock_market_view(self.run, path)

    def tearDown(self):
        self.temp.cleanup()

    def private_layer(self):
        freeze_product_dossier(self.store, self.run, ['000051'])
        path = self.root / 'positions.json'
        path.write_text(json.dumps({'authoritative_source': 'fixture_user_record',
             'positions': [{'code': '000051', 'amount': 876543.21, 'amount_basis': 'invested_cost'}]}), encoding='utf-8')
        load_portfolio_after_view(self.run, path)
        map_portfolio(self.run)

    def test_market_only_export_never_reads_private_inputs(self):
        (self.run / 'portfolio-inputs.private.json').write_text('deliberately unreadable private input', encoding='utf-8')
        result = export_report(self.run, self.root / 'public')
        self.assertNotIn('portfolio-appendix.private.md', result['artifacts'])
        self.assertFalse(json.loads((self.root / 'public/report-provenance.json').read_text(encoding='utf-8'))['portfolio_in_market_report'])

    def test_separate_appendix_preserves_view_and_excludes_cost_amount(self):
        self.private_layer()
        before = (self.run / 'market-view.json').read_bytes()
        output = self.root / 'export'
        result = export_report(self.run, output, include_portfolio=True)
        self.assertIn('portfolio-appendix.private.md', result['artifacts'])
        for path in output.iterdir():
            self.assertNotIn('876543', path.read_text(encoding='utf-8'))
        self.assertEqual(before, (self.run / 'market-view.json').read_bytes())

    def test_modified_view_refuses_export_without_partial_output(self):
        path = self.run / 'market-view.json'
        value = json.loads(path.read_text(encoding='utf-8'))
        value['view']['market_summary'] = 'Changed conclusion'
        path.write_text(json.dumps(value), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Changed sealed'):
            export_report(self.run, self.root / 'failed')
        self.assertFalse((self.root / 'failed').exists())

    def test_changed_product_mapping_refuses_export(self):
        self.private_layer()
        path = self.run / 'portfolio-mapping.private.json'
        value = json.loads(path.read_text(encoding='utf-8'))
        value['positions'][0]['underlying_identity'] = 'fabricated target'
        path.write_text(json.dumps(value), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'authoritative projection'):
            export_report(self.run, self.root / 'failed', include_portfolio=True)
        self.assertFalse((self.root / 'failed').exists())

    def test_export_cannot_overwrite_an_existing_artifact_directory(self):
        output = self.root / 'existing'
        output.mkdir()
        (output / 'keep.txt').write_text('existing user artifact', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            export_report(self.run, output)
        self.assertEqual((output / 'keep.txt').read_text(encoding='utf-8'), 'existing user artifact')


if __name__ == '__main__':
    unittest.main()
