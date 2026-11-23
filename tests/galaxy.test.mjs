// The Knowledge Galaxy's search: typing a query hides the stars that don't match
// (they stop being drawn and stop being hoverable/clickable), and clearing the
// search brings them all back. The galaxy draws on a canvas, so this test stubs
// the DOM and a 2D context and reads back what drawFrame() actually drew.
import { test } from "node:test";
import assert from "node:assert/strict";

let nowMs = 0;
globalThis.performance = { now: () => nowMs };
globalThis.devicePixelRatio = 1;
globalThis.matchMedia = () => ({ matches: false });
let rafCb = null;
globalThis.requestAnimationFrame = (cb) => { rafCb = cb; return 1; };
globalThis.cancelAnimationFrame = () => {};
globalThis.addEventListener = () => {};
globalThis.removeEventListener = () => {};
globalThis.window = globalThis;

function makeEl(tag) {
  const el = {
    tag, children: [], style: {}, className: "", textContent: "", value: "",
    listeners: {}, _q: {},
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    addEventListener(type, fn) { (el.listeners[type] ??= []).push(fn); },
    append(...c) { el.children.push(...c); },
    setAttribute() {},
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 800, height: 600 }),
    closest: () => null,
    focus() {},
    querySelector(sel) {
      if (el._q[sel]) return el._q[sel];
      if (sel.startsWith(".")) {
        const cls = sel.slice(1);
        return el.children.find((c) => (c.className || "").split(" ").includes(cls)) ?? null;
      }
      return el.children.find((c) => c.tag === sel) ?? null;
    },
  };
  return el;
}
globalThis.document = {
  createElement: (tag) => makeEl(tag),
  createTextNode: (t) => ({ textContent: t }),
  querySelector: () => null,
};

const labelsDrawn = [];
const ctx = {
  fillText(text) { labelsDrawn.push(text); },
  clearRect() {}, beginPath() {}, arc() {}, fill() {}, stroke() {},
  moveTo() {}, lineTo() {}, closePath() {}, setTransform() {},
  createRadialGradient: () => ({ addColorStop() {} }),
};
const canvas = makeEl("canvas");
canvas.getContext = () => ctx;
const info = makeEl("div");
info._q = { h3: makeEl("h3"), ".kind": makeEl("div"), p: makeEl("p") };
const searchEl = makeEl("input");
const labelsBtn = makeEl("button");
const root = makeEl("section");
root._q = {
  canvas,
  ".galaxy-info": info,
  ".galaxy-search input": searchEl,
  ".galaxy-labels": labelsBtn,
  ".galaxy-hud": makeEl("div"),
  ".galaxy-title small": makeEl("small"),
  ".galaxy-close": makeEl("button"),
};

const { createGalaxy, relaxGalaxyNodes } = await import("../ui/galaxy.js");
const galaxy = createGalaxy(root, { act: () => {}, onOpenChange: () => {} });
galaxy.loadData({ nodes: [
  { id: "rust", label: "Rust", kind: "wiki", excerpt: "systems language", x: -20, y: 0, z: 20, size: 1 },
  { id: "python", label: "Python", kind: "wiki", excerpt: "scripting language", x: 20, y: 0, z: 20, size: 1 },
  { id: "go", label: "Go", kind: "wiki", excerpt: "compiled language", x: 0, y: 10, z: 20, size: 1 },
], edges: [{ source: "rust", target: "python" }] });
galaxy.open();
const frame = () => { const cb = rafCb; rafCb = null; cb(0); };

test("labels stay hidden until a star is hovered or selected", () => {
  frame();
  assert.deepEqual(labelsDrawn, []);
  labelsDrawn.length = 0;

  // Rust projects to sx≈253, sy≈343 at the default camera; hovering it shows only its label.
  for (const fn of canvas.listeners.pointermove) fn({ clientX: 253, clientY: 343 });
  assert.equal(canvas.style.cursor, "pointer");
  frame();
  assert.deepEqual(labelsDrawn, ["Rust"]);
  labelsDrawn.length = 0;

  // Moving away hides it again.
  for (const fn of canvas.listeners.pointermove) fn({ clientX: 0, clientY: 0 });
  frame();
  assert.deepEqual(labelsDrawn, []);
});

test("the Labels toggle shows every visible star's label", () => {
  for (const fn of labelsBtn.listeners.click) fn();
  frame();
  assert.deepEqual([...labelsDrawn].sort(), ["Go", "Python", "Rust"]);
  labelsDrawn.length = 0;
  for (const fn of labelsBtn.listeners.click) fn();
  frame();
  assert.deepEqual(labelsDrawn, []);
});

test("search hides non-matching stars and they stop being hoverable", () => {
  labelsDrawn.length = 0;

  searchEl.value = "rust"; // Rust matches; Python + Go become hidden
  for (const fn of searchEl.listeners.input) fn();
  nowMs += 2000; // let the fly-to animation finish so projection is deterministic
  frame();
  assert.deepEqual(labelsDrawn, ["Rust"]);

  // Python projects to sx≈852, sy=300 once the fly-to settles; hovering there
  // must not find it any more (cursor stays "grab", not "pointer").
  for (const fn of canvas.listeners.pointermove) fn({ clientX: 852, clientY: 300 });
  assert.notEqual(canvas.style.cursor, "pointer");
});

test("clearing the search brings every star back", () => {
  labelsDrawn.length = 0;
  searchEl.value = "";
  for (const fn of searchEl.listeners.input) fn();
  frame();
  // Hovering Python's spot finds it again (cursor turns to "pointer").
  for (const fn of canvas.listeners.pointermove) fn({ clientX: 852, clientY: 300 });
  assert.equal(canvas.style.cursor, "pointer");
});

test("relaxGalaxyNodes spreads a clump and keeps every star on its sphere", () => {
  const nodes = Array.from({ length: 30 }, (_, i) => ({
    x: 40 + (i % 5) * 0.5, y: (i % 3) * 0.5, z: 0.5,
  }));
  const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);
  const minBefore = Math.min(...nodes.flatMap((a, i) => nodes.slice(i + 1).map((b) => dist(a, b))));
  relaxGalaxyNodes(nodes, 40);
  const minAfter = Math.min(...nodes.flatMap((a, i) => nodes.slice(i + 1).map((b) => dist(a, b))));
  assert.ok(minAfter > minBefore * 3, `min distance ${minBefore} -> ${minAfter}`);
  for (const node of nodes) {
    assert.ok(Math.abs(Math.hypot(node.x, node.y, node.z) - 40) < 0.01);
  }
});
