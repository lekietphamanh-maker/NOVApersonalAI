"""Trading lab: paper trading only. The arithmetic is tested exactly (the day-trader skill's worked example:
a $5,000 account with a $50 max loss takes 8 shares at $364.18, costing $2,913.44 and losing $46.88 at the
stop), the network is faked, and there is no live-order code path anywhere to test for."""
from __future__ import annotations

import unittest
import urllib.error
from typing import Any

import trading


def bars(closes: list[float]) -> list[dict[str, Any]]:
    """Daily bars from closes: highs a touch above, lows a touch below, opens a touch under the close."""
    return [{"date": f"2026-01-{day + 1:02d}", "open": close - 0.2, "high": close + 0.5,
             "low": close - 0.5, "close": close, "volume": 1000} for day, close in enumerate(closes)]


def chart_json(closes: list[float]) -> dict[str, Any]:
    series = bars(closes)
    return {"chart": {"result": [{"timestamp": [1_700_000_000 + day * 86400 for day in range(len(series))],
                                  "indicators": {"quote": [{"open": [bar["open"] for bar in series],
                                                           "high": [bar["high"] for bar in series],
                                                           "low": [bar["low"] for bar in series],
                                                           "close": [bar["close"] for bar in series],
                                                           "volume": [bar["volume"] for bar in series]}]}}]}}


BREAKOUT = [100 + i * 0.5 for i in range(20)] + [110.0] * 9 + [112.0]  # a close above the 20-day high
NEWS_JSON = {"news": [{"title": "Apple unveils a new chip", "publisher": "Reuters",
                       "providerTime": 1_763_000_000, "link": "https://example.com/apple-chip"}]}
TICKERS_JSON = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
FACTS_JSON = {"facts": {"us-gaap": {
    "Revenues": {"unit": {"USD": [{"val": 391_000_000_000, "end": "2024-09-28", "form": "10-K"}]}},
    "NetIncomeLoss": {"unit": {"USD": [{"val": 93_740_000_000, "end": "2024-09-28", "form": "10-K"}]}}}}}


def fake_fetch(url: str) -> Any:
    if "v8/finance/chart" in url and "AAPL" in url:
        return chart_json(BREAKOUT)
    if "v1/finance/search" in url:
        return NEWS_JSON
    if "company_tickers.json" in url:
        return TICKERS_JSON
    if "companyfacts" in url:
        return FACTS_JSON
    raise urllib.error.URLError("no network in tests")


def offline_fetch(url: str) -> Any:
    raise urllib.error.URLError("no network in tests")


class SymbolTests(unittest.TestCase):
    def test_clean_symbol(self) -> None:
        self.assertEqual(trading.clean_symbol("aapl"), "AAPL")
        self.assertEqual(trading.clean_symbol(" BRK-B "), "BRK-B")
        self.assertEqual(trading.clean_symbol("^GSPC"), "^GSPC")
        self.assertIsNone(trading.clean_symbol(""))
        self.assertIsNone(trading.clean_symbol("AAPL; DROP TABLE"))
        self.assertIsNone(trading.clean_symbol("waytoolongticker"))


class MathTests(unittest.TestCase):
    def test_position_size_matches_the_originals_worked_example(self) -> None:
        sizing, problem = trading.position_size(5000, 50, 364.18, 358.32)
        self.assertEqual(problem, "")
        self.assertEqual(sizing["shares"], 8)
        self.assertAlmostEqual(sizing["cost"], 2913.44, places=2)
        self.assertAlmostEqual(sizing["loss_at_stop"], 46.88, places=2)

    def test_position_size_needs_a_stop_below_the_entry(self) -> None:
        sizing, problem = trading.position_size(5000, 50, 100, 100)
        self.assertIsNone(sizing)
        self.assertIn("stop has to sit below the entry", problem)
        sizing, problem = trading.position_size(0, 50, 100, 90)
        self.assertIsNone(sizing)

    def test_entry_exit_on_a_breakout(self) -> None:
        plan, problem = trading.entry_exit(bars(BREAKOUT))
        self.assertEqual(problem, "")
        self.assertTrue(plan["triggered"])
        self.assertAlmostEqual(plan["entry"], 112.0)
        self.assertAlmostEqual(plan["stop"], 107.25)   # midpoint of the 110.50 high and the 104.00 low
        self.assertAlmostEqual(plan["target"], 116.75)  # 1R above the entry

    def test_entry_exit_waits_when_nothing_triggered(self) -> None:
        plan, _ = trading.entry_exit(bars([100 + i * 0.5 for i in range(20)] + [110.0] * 9 + [109.0]))
        self.assertFalse(plan["triggered"])
        self.assertAlmostEqual(plan["entry"], 110.5)   # the trigger price: a close above the range
        self.assertAlmostEqual(plan["target"], 113.75)

    def test_rsi(self) -> None:
        self.assertEqual(trading.rsi(bars([100.0] * 20)), 50.0)          # flat: no gains, no losses
        self.assertEqual(trading.rsi(bars([100.0 + i for i in range(20)])), 100.0)  # only up
        self.assertIsNone(trading.rsi(bars([100.0] * 5)))                # too few bars

    def test_time_machine_flat_stock_never_hits_either_side(self) -> None:
        odds, problem = trading.time_machine_odds(bars([100.0] * 40), 100, 95, 105)
        self.assertEqual(problem, "")
        self.assertEqual(odds["fired"], 0)
        self.assertEqual((odds["target_pct"], odds["stop_pct"], odds["open_pct"]), (0.0, 0.0, 100.0))

    def test_time_machine_is_deterministic_and_sums_to_100(self) -> None:
        series = bars([100 * 1.01 ** i for i in range(40)])  # up 1% a day
        first, _ = trading.time_machine_odds(series, 100, 98, 102)
        second, _ = trading.time_machine_odds(series, 100, 98, 102)
        self.assertEqual(first, second)  # same seed, same numbers
        self.assertAlmostEqual(first["target_pct"] + first["stop_pct"] + first["open_pct"], 100.0)
        self.assertEqual(first["target_pct"], 100.0)  # a steady climb hits the target first
        self.assertEqual(first["fired"], 15)
        self.assertEqual(first["past_target"] + first["past_stop"] + first["past_open"], first["fired"])


class DeskTests(unittest.TestCase):
    def test_unknown_action_says_what_exists(self) -> None:
        desk = trading.TradingDesk(fake_fetch)
        answer = desk.act("buy", {})
        self.assertFalse(answer["ok"])
        self.assertIn("scan", answer["error"])

    def test_scan_finds_the_breakout(self) -> None:
        desk = trading.TradingDesk(fake_fetch)
        answer = desk.act("scan", {"symbol": "AAPL"})
        self.assertTrue(answer["ok"])
        self.assertIn("AAPL $112.00", answer["lines"][0])
        self.assertIn("Breakout", answer["lines"][0])

    def test_scan_with_no_network_says_so_per_symbol(self) -> None:
        desk = trading.TradingDesk(offline_fetch)
        answer = desk.act("scan", {"symbol": "AAPL"})
        self.assertTrue(answer["ok"])  # a scan reports each symbol's failure rather than dying
        self.assertIn("Couldn't reach Yahoo Finance", answer["lines"][0])

    def test_entry_news_and_odds_from_fake_data(self) -> None:
        desk = trading.TradingDesk(fake_fetch)
        entry = desk.act("entry", {"symbol": "AAPL"})
        self.assertTrue(entry["ok"])
        self.assertIn("Triggered", entry["lines"][1])
        news = desk.act("news", {"symbol": "AAPL"})
        self.assertTrue(news["ok"])
        self.assertIn("Apple unveils a new chip", [item["title"] for item in news["items"]])
        self.assertIn("House Clerk", [item["source"] for item in news["items"]])
        self.assertIn("revenue $391.0B (2024)", " ".join(news["lines"]))
        odds = desk.act("odds", {"symbol": "AAPL"})
        self.assertTrue(odds["ok"])
        self.assertIn("10,000 replays", odds["lines"][1])
        self.assertIn("not a prediction", " ".join(odds["lines"]))

    def test_entry_with_no_network_is_a_clear_error(self) -> None:
        desk = trading.TradingDesk(offline_fetch)
        answer = desk.act("entry", {"symbol": "AAPL"})
        self.assertFalse(answer["ok"])
        self.assertIn("Couldn't reach Yahoo Finance", answer["error"])

    def test_budget_sizes_the_breakout_plan(self) -> None:
        desk = trading.TradingDesk(fake_fetch)
        answer = desk.act("budget", {"symbol": "AAPL", "account": 5000})
        self.assertTrue(answer["ok"])
        self.assertIn("10 shares at $112.00 = $1,120.00.", answer["lines"])
        self.assertIn("A fill at the stop loses $47.50.", answer["lines"])
        self.assertIn("places nothing", " ".join(answer["lines"]))

    def test_risk_pass_and_block(self) -> None:
        desk = trading.TradingDesk(fake_fetch)
        passing = desk.act("risk", {"entry": 364.18, "stop": 358.32, "account": 5000, "shares": 8})
        self.assertIn("PASS", " ".join(passing["lines"]))
        blocked = desk.act("risk", {"entry": 364.18, "stop": 358.32, "account": 5000, "shares": 9})
        self.assertIn("BLOCK", " ".join(blocked["lines"]))
        self.assertIn("over the $50.00 limit", " ".join(blocked["lines"]))

    def test_exit_from_numbers_needs_no_network(self) -> None:
        desk = trading.TradingDesk(offline_fetch)
        answer = desk.act("exit", {"entry": 100, "stop": 95, "target": 105})
        self.assertTrue(answer["ok"])
        self.assertIn("Entry $100.00 · stop $95.00 · target $105.00.", answer["lines"][0])

    def test_answer_is_plain_text_for_nova(self) -> None:
        desk = trading.TradingDesk(fake_fetch)
        text = desk.answer("scan", {"symbol": "AAPL"})
        self.assertIn("Scan", text)
        self.assertIn("AAPL $112.00", text)
        offline = trading.TradingDesk(offline_fetch).answer("entry", {"symbol": "AAPL"})
        self.assertIn("Couldn't reach Yahoo Finance", offline)

    def test_there_is_no_live_order_code_path(self) -> None:
        desk = trading.TradingDesk(fake_fetch)
        for name in ("place_order", "buy", "sell", "broker", "place", "execute_order"):
            self.assertFalse(hasattr(desk, name), name)


if __name__ == "__main__":
    unittest.main()
