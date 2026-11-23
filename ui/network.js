// Network lab: the JARVIS-style network panel — speed, status, devices, history and alerts, in one place.
// Every number on this screen is measured on the PC by network.py (ping, ipconfig, arp, Cloudflare's speed
// test); nothing here is made up, and a failed measurement says so instead of showing a guessed value. The
// lab builds its own DOM (the top bar and section shell come from the integration), so it works from the
// one-line section the integration adds.
import { h, screen } from "./lab.js";
import { mountWhatCanIDo } from "./whatcanido.js";

const CARDS = [
  { id: "speed", title: "Speed test", what: "A real download and upload against Cloudflare's speed test — download, upload and ping, saved to your history." },
  { id: "status", title: "Network status", what: "Your Wi-Fi or Ethernet, this PC, the router, DNS, your public IP and the latency to the internet." },
  { id: "devices", title: "Devices", what: "Who's on your network right now — a sweep of your local network with IP and MAC, and who's gone quiet since last time." },
  { id: "history", title: "History", what: "Your saved speed tests on this PC, with your usual speed and the slowest and fastest runs." },
  { id: "alerts", title: "Alerts", what: "Speed well below your usual, or a device that was here last scan and isn't now." },
];

// --- the hero speed chart: pure shaping, no DOM, so it is testable in node ---

// The y-axis top for a list of {time, down, up} points, or null when there is nothing to draw.
export function historyChartStats(points) {
  if (!Array.isArray(points) || !points.length) return null;
  return { max: Math.max(1, ...points.flatMap((point) => [point.down, point.up])) };
}

// An SVG chart with two series — download (amber) and upload (green) — as a string (innerHTML
// parses SVG properly; createElement does not). "" when there is nothing to draw, so the caller
// shows "run a speed test first" instead of a fake chart. One test draws two dots, honestly.
export function historyChartSvg(points, width = 600, height = 180) {
  const stats = historyChartStats(points);
  if (!stats) return "";
  const padL = 8, padR = 8, padT = 16, padB = 22;
  const x = (i) => points.length === 1 ? width / 2
    : padL + (i * (width - padL - padR)) / (points.length - 1);
  const y = (value) => padT + (1 - value / stats.max) * (height - padT - padB);
  const series = (key, color) => {
    const line = points.map((point, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(point[key]).toFixed(1)}`).join(" ");
    const dots = points.map((point, i) =>
      `<circle cx="${x(i).toFixed(1)}" cy="${y(point[key]).toFixed(1)}" r="3.5" fill="${color}"/>`).join("");
    return points.length === 1 ? dots : `<path d="${line}" fill="none" stroke="${color}" stroke-width="2"/>${dots}`;
  };
  const esc = (text) => String(text).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const first = points[0], last = points[points.length - 1];
  return `<svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}" role="img" aria-label="Speed history chart">`
    + series("down", "#f5b942") + series("up", "#5be0a0")
    + `<text x="${padL}" y="11" fill="#f5b942" font-size="10" font-family="monospace">— Download (Mbps)</text>`
    + `<text x="150" y="11" fill="#5be0a0" font-size="10" font-family="monospace">— Upload (Mbps)</text>`
    + `<text x="${padL}" y="${height - 8}" fill="#8a94a6" font-size="10" font-family="monospace">${esc(first.time)} → ${esc(last.time)}</text>`
    + `</svg>`;
}

export function createNetwork(root, { act, onOpenChange }) {
  const view = screen(root, { onOpenChange });
  let built = false;
  let cardsBox, setupBox, heroBox, resultBoxes = [];

  function build() {
    if (built) return;
    built = true;
    root.classList.add("world", "lab", "lab-network");
    const head = h("header", { class: "lib-head" },
      h("div", { class: "lib-title" }, h("span", { class: "lib-mark", "aria-hidden": "true" }),
        h("b", {}, "NETWORK"), h("span", { class: "lib-crumb" }, "measured on this PC")),
      h("button", { class: "box small", type: "button", title: "Esc", onclick: () => view.close() }, "Close"));
    const banner = h("p", { class: "trading-paper" },
      "Every number here is measured live on this PC — a real speed test, real pings, a real scan of your network. "
      + "If something can't be measured, Nova says so instead of guessing. Nothing about your network ever leaves this PC.");
    banner.style.cssText = "margin: 0 22px; padding: 10px 14px; border: 1px solid var(--warn); border-left: 3px solid var(--warn); "
      + "background: rgba(255, 181, 71, 0.07); color: var(--text); font: 500 13px/1.5 var(--sans);";
    // The hero chart: your own measured speed history, download and upload. One test so far
    // shows that one honestly; none says "run a speed test first" instead of drawing anything fake.
    heroBox = h("section", { class: "network-hero", "aria-live": "polite" });
    cardsBox = h("div", { class: "skills-grid" },
      h("div", { class: "skill-cards" }, CARDS.map((card) => {
        const result = h("div", { class: "network-result" });
        const button = h("button", { type: "button", class: "box small on",
          onclick: () => run(card.id, result, button) }, card.id === "speed" ? "Run speed test" : "Run");
        return h("article", { class: "skill-card ready" },
          h("header", {}, h("b", {}, card.title)),
          h("p", {}, card.what),
          button, result);
      })));
    resultBoxes = [...cardsBox.querySelectorAll(".network-result")];
    setupBox = h("p", { class: "lab-problem", hidden: true, role: "status" });
    const hint = h("p", { class: "lib-hint" },
      "Free local tools only (ping, ipconfig, arp, Cloudflare speed test) · No account, no key, nothing sent to a cloud · Esc");
    const helpWrap = h("div", { style: "padding: 0 22px;" });
    mountWhatCanIDo(helpWrap, "network", { onPhrase: runPhrase });
    root.append(head, banner, heroBox, cardsBox, setupBox, helpWrap, hint);
    loadHistoryChart();
  }

  async function loadHistoryChart() {
    heroBox.replaceChildren(h("p", { class: "network-hero-note" }, "Loading your speed history…"));
    const answer = await act("network", { action: "chart" });
    if (!answer?.ok) {
      heroBox.replaceChildren(h("p", { class: "network-hero-note" },
        answer?.error || "Couldn't load your speed history — try again in a bit."));
      return;
    }
    const svg = historyChartSvg(answer.points || []);
    if (!svg) {
      heroBox.replaceChildren(h("p", { class: "network-hero-note" },
        "No speed tests saved yet — run a speed test first and the chart will fill in."));
      return;
    }
    const latest = answer.latest || {};
    const head = h("div", { class: "network-hero-head" },
      h("b", {}, "Speed history"),
      h("span", { class: "network-hero-latest" },
        `Latest: ${Number(latest.down || 0).toFixed(0)} down / ${Number(latest.up || 0).toFixed(0)} up Mbps`
        + (latest.ping != null ? ` · ${Number(latest.ping).toFixed(0)} ms ping` : "")),
      h("span", { class: "network-hero-range" }, `${(answer.points || []).length} test${(answer.points || []).length === 1 ? "" : "s"}`));
    const chart = h("div", { class: "network-hero-chart" });
    chart.innerHTML = svg;
    heroBox.replaceChildren(head, chart);
  }

  function showSetup(message) {
    if (!message) { setupBox.hidden = true; setupBox.textContent = ""; return; }
    setupBox.hidden = false;
    setupBox.textContent = message;
  }

  function renderResult(box, answer) {
    if (!answer.ok) {
      box.replaceChildren(h("p", { class: "skill-note" },
        String(answer.error || "").includes("Unknown action")
          ? "Network isn't wired up in this Nova yet — it needs its one-line backend wiring before the cards can run."
          : (answer.error || "Nova didn't answer.")));
      if (!String(answer.error || "").includes("Unknown action")) {
        showSetup("Network data needs the internet for the speed test and your public IP. If this keeps failing, check Nova is online and try again.");
      }
      return;
    }
    showSetup("");
    const lines = (answer.lines || []).map((line) => h("p", { class: "skill-note" }, line));
    box.replaceChildren(...lines);
  }

  async function run(action, resultBox, button) {
    build();
    const card = CARDS.find((entry) => entry.id === action) || CARDS[0];
    const box = resultBox || resultBoxes[CARDS.indexOf(card)];
    if (button) button.disabled = true;
    box.replaceChildren(h("p", { class: "skill-note" }, action === "devices" ? "Scanning your network…" : action === "speed" ? "Measuring — downloading, then uploading…" : "…"));
    const answer = await act("network", { action });
    renderResult(box, answer || { ok: false });
    if (action === "speed" && answer?.ok) loadHistoryChart(); // the new test belongs on the chart
    if (button) button.disabled = false;
  }

  function runPhrase(phrase) {
    // A "What I can do" phrase runs the card it names.
    const lower = phrase.toLowerCase();
    const action = lower.includes("who") || lower.includes("wi-fi") || lower.includes("wifi") || lower.includes("device") ? "devices"
      : lower.includes("history") || lower.includes("usual") ? "history"
      : lower.includes("alert") || lower.includes("wrong") || lower.includes("slow") ? "alerts"
      : lower.includes("status") || lower.includes("router") || lower.includes("connected") ? "status"
      : "speed";
    run(action);
  }

  return {
    open() { build(); view.open(); },
    close: () => view.close(),
    isOpen: view.isOpen,
    handleKey(event) {
      const editing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "");
      if (event.key === "Escape") {
        if (editing) { document.activeElement.blur(); return true; }
        view.close();
        return true;
      }
      return false;
    },
  };
}
