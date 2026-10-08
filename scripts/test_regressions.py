"""Regressions for data correctness; fixtures do not contact live providers."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from market_core.http import DataSourceError, HttpClient
from market_core.indicators import indicator_rows_grouped
from market_core.models import Bar, Observation, Quote
from market_core.providers.fund_eastmoney import EastmoneyFundProvider
from market_core.providers.mootdx_provider import MootdxProvider
from market_core.store import MarketStore


class Frame:
    empty = False

    def to_dict(self, orientation):
        return [{"time": "10:00:00", "price": 100, "vol": 10, "buyorsell": 0}]


class Client:
    def __init__(self):
        self.client = self

    def get_history_transaction_data(self, *args):
        return Frame().to_dict("records")

    def get_transaction_data(self, *args):
        return Frame().to_dict("records")
    def transaction(self, **kwargs):
        return Frame()

    def transactions(self, **kwargs):
        return Frame()


class CorrectnessTests(unittest.TestCase):
    def test_tick_branch_and_identity(self):
        with patch.object(MootdxProvider, "_client", return_value=Client()):
            rows = MootdxProvider().fetch_transactions("600519", date="2026-09-30")
        self.assertTrue(rows[0].identity.startswith("sh600519#"))

    def test_nav_uses_source_date(self):
        client = HttpClient()
        # Midnight 2026-09-30 Shanghai, not midnight UTC.
        payload = 'var fS_code="000051"; var Data_netWorthTrend = [{"x":1790697600000,"y":1.2}];'
        with patch.object(client, "get_text", return_value=(payload, "https://example.test/fund")):
            rows = EastmoneyFundProvider(client).fetch_nav_history("000051")
        self.assertEqual(rows[0].as_of, "2026-09-30")

    def test_json_error_redacts_query_secret(self):
        client = HttpClient()
        with patch.object(client, "get_text", return_value=("invalid", "https://example.test/?api_key=TEST_SECRET")):
            with self.assertRaises(DataSourceError) as captured:
                client.get_json("https://example.test/")
        self.assertNotIn("TEST_SECRET", str(captured.exception))

    def test_adjustment_variants_survive_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            store = MarketStore(Path(directory) / "test.sqlite3")
            rows = [Bar("fixture", "sh600519", "1d", "2026-09-30", price, price, price, price, price_basis=basis)
                    for basis, price in (("qfq", 10), ("hfq", 100))]
            store.upsert_bars(rows)
            self.assertEqual(len(store.get_bars("sh600519", "1d")), 2)

    def test_indicator_groups_preserve_basis(self):
        rows = [Bar("fixture", "sh600519", "1d", "2026-09-30", price, price, price, price, price_basis=basis)
                for basis, price in (("qfq", 10), ("hfq", 100))]
        values = indicator_rows_grouped(rows)
        self.assertEqual({getattr(row, "price_basis", None) for row in values}, {"qfq", "hfq"})

    def test_snapshot_keeps_slow_series_and_book(self):
        with tempfile.TemporaryDirectory() as directory:
            store = MarketStore(Path(directory) / "test.sqlite3")
            store.upsert_observations([Observation("fixture", "macro_series", "slow", "2026-01-01", 1)])
            store.upsert_observations([Observation("fixture", "fund_unit_nav", "fund", f"2026-09-{day:02d}", day)
                                       for day in range(1, 30)])
            store.upsert_quotes([Quote("fixture", "sh600519", "2026-09-30T15:00:00+08:00",
                                      bid_book=[{"price": 100, "volume": 10}])])
            snapshot = store.snapshot(observation_limit=3)
            self.assertIn("slow", {row["identity"] for row in snapshot["recent_observations"]})
            self.assertEqual(snapshot["latest_quotes"][0]["bid_book"][0]["price"], 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
