// Network tab: the hero speed-history chart's shaping. Pure logic, no DOM.
import { test } from "node:test";
import assert from "node:assert/strict";
import { historyChartStats, historyChartSvg } from "../ui/network.js";

const POINTS = [
  { time: "2026-11-21 19:00", down: 100, up: 20, ping: 12 },
  { time: "2026-11-22 09:00", down: 120, up: 25, ping: 11 },
  { time: "2026-11-22 19:00", down: 90, up: 18, ping: 14 },
];

test("historyChartStats takes the top of both series", () => {
  assert.deepEqual(historyChartStats(POINTS), { max: 120 });
  assert.equal(historyChartStats([]), null);
});

test("historyChartSvg draws two series with a legend and a date range", () => {
  const svg = historyChartSvg(POINTS);
  assert.match(svg, /<svg /);
  assert.match(svg, /stroke="#f5b942"/); // download, amber
  assert.match(svg, /stroke="#5be0a0"/); // upload, green
  assert.match(svg, /Download \(Mbps\)/);
  assert.match(svg, /Upload \(Mbps\)/);
  assert.match(svg, /2026-11-21 19:00 → 2026-11-22 19:00/);
  assert.match(svg, /<circle /); // dots on the latest point
  assert.equal(historyChartSvg([]), "");
});

test("one test draws two honest dots, not a fake line", () => {
  const svg = historyChartSvg([POINTS[0]]);
  assert.match(svg, /<circle /);
  assert.doesNotMatch(svg, /<path /);
});
