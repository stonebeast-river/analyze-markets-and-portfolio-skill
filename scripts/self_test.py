#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from market_core.indicators import (
    breadth,
    indicator_rows_grouped,
    intraday_volume_ratio,
    macd,
    order_book_imbalance,
    series_indicator_rows,
    trailing_return,
)
from market_core.models import Bar, Quote
from market_core.microstructure import summarize_transactions
from market_core.models import Observation
from market_core.providers.tencent import parse_tencent_payload
from market_core.store import MarketStore
from market_core.symbols import eastmoney_secid, normalize_cn_symbol


class SymbolTests(unittest.TestCase):
    def test_ambiguous_and_explicit_symbols(self):
        self.assertEqual(normalize_cn_symbol("000300"), "sh000300")
        self.assertEqual(normalize_cn_symbol("sz000001"), "sz000001")
        self.assertEqual(eastmoney_secid("510300"), "1.510300")
        with self.assertRaises(ValueError):
            normalize_cn_symbol("sz600519")


class IndicatorTests(unittest.TestCase):
    def test_macd_lengths_and_flat_series(self):
        dif, dea, hist = macd([10.0] * 40)
        self.assertEqual(len(dif), 40)
        self.assertTrue(all(abs(value) < 1e-12 for value in dif + dea + hist))

    def test_intraday_volume_ratio(self):
        ratio = intraday_volume_ratio(600.0, 120, [1000.0] * 5)
        self.assertAlmostEqual(ratio or 0.0, 1.2)

    def test_breadth(self):
        result = breadth([1, -1, 0, 2, None])
        self.assertEqual(result["advancers"], 2)
        self.assertEqual(result["decliners"], 1)

    def test_trailing_returns(self):
        result = trailing_return([10.0, 11.0, 12.0], 2)
        self.assertIsNone(result[1])
        self.assertAlmostEqual(result[2] or 0.0, 0.2)

    def test_price_only_series_indicators(self):
        rows = [
            Observation(
                provider="fixture", dataset="fund_unit_nav", identity="000051",
                as_of=f"2026-08-{day:02d}", value=1.0 + day / 100,
            )
            for day in range(1, 29)
        ]
        result = series_indicator_rows(rows)
        self.assertEqual(len(result), 28 * 8)
        self.assertTrue(all(row.symbol == "000051" for row in result))


class TencentTests(unittest.TestCase):
    def test_quote_parser_marks_vendor_fields(self):
        values = [""] * 90
        values[1] = "测试股票"
        values[2] = "600519"
        values[3] = "100"
        values[4] = "99"
        values[5] = "98"
        values[6] = "1000"
        values[7] = "600"
        values[8] = "400"
        values[9], values[10] = "99.9", "12"
        values[19], values[20] = "100.1", "9"
        values[30] = "20260904150000"
        values[33], values[34] = "101", "97"
        values[37] = "1234"
        values[38] = "2.5"
        values[39] = "18"
        values[45] = "200"
        values[46] = "3"
        values[49] = "1.4"
        payload = 'v_sh600519="' + "~".join(values) + '";'
        quote = parse_tencent_payload(payload, ["sh600519"])[0]
        self.assertEqual(quote.amount, 12_340_000)
        self.assertEqual(quote.outer_volume, 600)
        self.assertAlmostEqual(order_book_imbalance(quote) or 0, 3 / 21)

    def test_csi_sector_symbol_is_classified_as_index(self):
        values = [""] * 90
        values[1], values[2], values[3], values[4], values[6] = "中证能源", "000928", "100", "99", "10"
        values[30] = "20260904150000"
        payload = 'v_sh000928="' + "~".join(values) + '";'
        quote = parse_tencent_payload(payload, ["sh000928"])[0]
        self.assertEqual(quote.asset_class, "index")


class MicrostructureTests(unittest.TestCase):
    def test_order_size_summary_is_explicitly_derived(self):
        rows = [
            Observation(
                provider="fixture", dataset="tick_transaction", identity="sh600519",
                as_of="2026-09-04T10:00:00+08:00",
                value={"price": 100, "volume": 30, "direction": "provider_buy"},
            ),
            Observation(
                provider="fixture", dataset="tick_transaction", identity="sh600519",
                as_of="2026-09-04T10:00:01+08:00",
                value={"price": 100, "volume": 10, "direction": "provider_sell"},
            ),
        ]
        result = summarize_transactions(
            rows, lot_size=100, large_notional=200_000, super_large_notional=1_000_000
        )
        self.assertEqual(result.value["large_buy_volume"], 30)
        self.assertEqual(result.value["large_net_notional"], 300_000)
        self.assertEqual(result.quality, "locally_derived_from_provider_trade_direction")


class StoreTests(unittest.TestCase):
    def test_quote_round_trip_uses_full_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            store = MarketStore(Path(directory) / "market.sqlite3")
            quote = Quote(
                provider="fixture", symbol="sh600519", as_of="2026-09-04T15:00:00+08:00",
                last=100.0, volume=1_000, amount=2_000_000, inner_volume=400,
                volume_unit="lot", amount_unit="CNY", book_volume_unit="lot",
                outer_volume=600, bid_book=[{"price": 99.9, "volume": 12}],
                ask_book=[{"price": 100.1, "volume": 9}],
                source_url="https://example.test/quote",
            )
            self.assertEqual(store.upsert_quotes([quote]), 1)
            snapshot = store.snapshot()
            self.assertEqual(snapshot["latest_quotes"][0]["symbol"], "sh600519")
            self.assertEqual(snapshot["latest_quotes"][0]["amount"], 2_000_000)
            self.assertEqual(snapshot["latest_quotes"][0]["amount_unit"], "CNY")
            self.assertEqual(snapshot["latest_quotes"][0]["source_url"], "https://example.test/quote")

    def test_round_trip_and_indicators(self):
        with tempfile.TemporaryDirectory() as directory:
            store = MarketStore(Path(directory) / "market.sqlite3")
            bars = [
                Bar(
                    provider="fixture", symbol="sh000300", interval="1d",
                    timestamp=f"2026-08-{day:02d}", open=float(day), high=float(day + 1),
                    low=float(day - 1), close=float(day) + 0.5, volume=1000 + day,
                    price_basis="qfq",
                )
                for day in range(1, 29)
            ]
            self.assertEqual(store.upsert_bars(bars), 28)
            computed = indicator_rows_grouped(bars)
            self.assertEqual(store.upsert_indicators(computed), 28 * 10)
            loaded = store.get_bars("sh000300", "1d")
            self.assertEqual(len(loaded), 28)
            health = store.health()
            self.assertEqual(health["row_counts"]["bars"], 28)


if __name__ == "__main__":
    unittest.main(verbosity=2)
