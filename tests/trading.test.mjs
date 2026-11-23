// Trading tab: company-name -> ticker, and the hero price chart's shaping. Pure logic, no DOM.
import { test } from "node:test";
import assert from "node:assert/strict";
import { resolveTradingSymbol, chartStats, chartSvg, QUICK_PICKS, COMPANY_NAMES } from "../ui/trading.js";

test("typing a company name resolves to its ticker", () => {
  assert.equal(resolveTradingSymbol("coca-cola"), "KO");
  assert.equal(resolveTradingSymbol("Coca-Cola"), "KO");
  assert.equal(resolveTradingSymbol("coca cola"), "KO");
  assert.equal(resolveTradingSymbol("apple"), "AAPL");
  assert.equal(resolveTradingSymbol("tesla"), "TSLA");
  assert.equal(resolveTradingSymbol("berkshire hathaway"), "BRK-B");
  assert.equal(resolveTradingSymbol("mcdonald's"), "MCD");
});

test("tickers still pass through, and junk resolves to nothing", () => {
  assert.equal(resolveTradingSymbol("aapl"), "AAPL");
  assert.equal(resolveTradingSymbol(" BRK-B "), "BRK-B");
  assert.equal(resolveTradingSymbol(""), null);
  assert.equal(resolveTradingSymbol("not a company xyz"), null);
});

test("quick picks cover the big names and match the name map", () => {
  assert.ok(QUICK_PICKS.length >= 8);
  for (const [ticker, name] of QUICK_PICKS) {
    assert.equal(resolveTradingSymbol(name), ticker, name);
    assert.equal(COMPANY_NAMES[name.toLowerCase().replace(/[^a-z0-9]/g, "")], ticker);
  }
});

const POINTS = [
  { date: "2026-11-02", close: 100 },
  { date: "2026-11-03", close: 102 },
  { date: "2026-11-04", close: 101 },
  { date: "2026-11-05", close: 105 },
];

test("chartStats reads min, max and the move across the points", () => {
  assert.deepEqual(chartStats(POINTS), { min: 100, max: 105, first: 100, last: 105, changePct: 5 });
  assert.equal(chartStats([]), null);
  assert.equal(chartStats([POINTS[0]]), null);
});

test("chartSvg draws a line through the closes, or nothing when there is nothing to draw", () => {
  const svg = chartSvg(POINTS);
  assert.match(svg, /<svg /);
  assert.match(svg, /<path d="M[^"]*L[^"]*"/); // the line
  assert.match(svg, /\$105\.00/); // the top label
  assert.match(svg, /2026-11-02 → 2026-11-05/); // the date range
  assert.equal(chartSvg([]), "");
  assert.equal(chartSvg([POINTS[0]]), "");
});

test("chartSvg colours a falling chart red and a rising one green", () => {
  assert.match(chartSvg(POINTS), /#5be0a0/);
  const falling = [...POINTS].reverse();
  assert.match(chartSvg(falling), /#ff6e82/);
});
