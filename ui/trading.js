// Trading lab: paper trading only, from the day-trader skill's method (Jakeschincariol/day-trader-skill, MIT).
// Seven cards — Scan, News, Entry, Exit, Time Machine odds, Risk, Budget — each one a question to the backend
// (trading.py), which reads free public data and does arithmetic. Nothing here places an order: there is no
// order button, no broker, no key. The banner says so on the screen, and every card's answer is a plan to read.
// The lab builds its own DOM (the top bar and section shell come from the integration), so it works from the
// one-line section the integration adds.
import { h, screen } from "./lab.js";
import { mountWhatCanIDo } from "./whatcanido.js";

const CARDS = [
  { id: "scan", title: "Scan", what: "Scans the watchlist for setups: opening-range breakouts, flags, oversold bounces." },
  { id: "news", title: "News", what: "Breaking headlines and filings for one symbol — and Congress trades from the House Clerk." },
  { id: "entry", title: "Entry", what: "Watches the setup and says the moment to get in: the first close above the range." },
  { id: "exit", title: "Exit", what: "Sets the stop and the target before you enter, so you know when to get out." },
  { id: "odds", title: "Time Machine odds", what: "Replays the trade 10,000 times from the stock's own history and tells you the honest odds." },
  { id: "risk", title: "Risk", what: "Checks the trade against your limits and says PASS or BLOCK, with the reasons." },
  { id: "budget", title: "Budget", what: "Sizes the position to your account and your max loss per trade." },
];
const SYMBOL = /^[A-Za-z][A-Za-z0-9.\-^]{0,11}$/;

// Well-known company names -> tickers, mirroring trading.py's COMPANY_NAMES so typing
// "coca-cola" works in the box instead of needing KO. Keys are the name lower-cased with
// every non-alphanumeric stripped.
export const COMPANY_NAMES = {
  apple: "AAPL", microsoft: "MSFT", nvidia: "NVDA", tesla: "TSLA",
  amazon: "AMZN", alphabet: "GOOGL", google: "GOOGL", meta: "META", facebook: "META",
  amd: "AMD", netflix: "NFLX", cocacola: "KO", cocacolacompany: "KO",
  pepsi: "PEP", pepsico: "PEP", walmart: "WMT", disney: "DIS", nike: "NKE",
  mcdonalds: "MCD", starbucks: "SBUX", intel: "INTC", costco: "COST",
  berkshire: "BRK-B", berkshirehathaway: "BRK-B",
  jpmorgan: "JPM", jpmorganchase: "JPM", chase: "JPM", bankofamerica: "BAC",
  visa: "V", mastercard: "MA", paypal: "PYPL", uber: "UBER", airbnb: "ABNB",
  spotify: "SPOT", cisco: "CSCO", oracle: "ORCL", adobe: "ADBE", salesforce: "CRM",
  ford: "F", generalmotors: "GM", exxon: "XOM", exxonmobil: "XOM", chevron: "CVX",
  pfizer: "PFE", johnsonjohnson: "JNJ", jj: "JNJ", proctergamble: "PG",
  palantir: "PLTR", coinbase: "COIN", gamestop: "GME",
};

export function resolveTradingSymbol(text) {
  const raw = String(text || "").trim();
  if (!raw) return null;
  const key = raw.toLowerCase().replace(/[^a-z0-9]/g, "");
  if (COMPANY_NAMES[key]) return COMPANY_NAMES[key];
  return SYMBOL.test(raw) ? raw.toUpperCase() : null;
}

// One-tap picks under the search box: the names Keith reaches for most.
export const QUICK_PICKS = [
  ["AAPL", "Apple"], ["MSFT", "Microsoft"], ["NVDA", "Nvidia"], ["TSLA", "Tesla"],
  ["AMZN", "Amazon"], ["GOOGL", "Alphabet"], ["META", "Meta"], ["KO", "Coca-Cola"],
];

// --- the hero price chart: pure shaping, no DOM, so it is testable in node ---

// Stats for a list of {date, close} points, or null when there is nothing to draw.
export function chartStats(points) {
  if (!Array.isArray(points) || points.length < 2) return null;
  const closes = points.map((point) => point.close);
  const first = closes[0], last = closes[closes.length - 1];
  return {
    min: Math.min(...closes), max: Math.max(...closes), first, last,
    changePct: first ? +(((last / first) - 1) * 100).toFixed(1) : 0,
  };
}

// An SVG line chart for the points, as a string (innerHTML parses SVG properly; createElement
// does not). "" when there is nothing to draw — the caller shows a plain message instead.
export function chartSvg(points, width = 600, height = 180) {
  const stats = chartStats(points);
  if (!stats) return "";
  const padL = 8, padR = 8, padT = 16, padB = 22;
  const range = stats.max - stats.min || 1;
  const x = (i) => padL + (i * (width - padL - padR)) / (points.length - 1);
  const y = (value) => padT + (1 - (value - stats.min) / range) * (height - padT - padB);
  const line = points.map((point, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(point.close).toFixed(1)}`).join(" ");
  const area = `${line} L${x(points.length - 1).toFixed(1)},${height - padB} L${padL},${height - padB} Z`;
  const last = points[points.length - 1];
  const up = last.close >= points[0].close;
  const color = up ? "#5be0a0" : "#ff6e82";
  const esc = (text) => String(text).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  return `<svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}" role="img" aria-label="Price chart">`
    + `<path d="${area}" fill="${color}" opacity="0.10"/>`
    + `<path d="${line}" fill="none" stroke="${color}" stroke-width="2"/>`
    + `<circle cx="${x(points.length - 1).toFixed(1)}" cy="${y(last.close).toFixed(1)}" r="3.5" fill="${color}"/>`
    + `<text x="${padL}" y="11" fill="#8a94a6" font-size="10" font-family="monospace">$${stats.max.toFixed(2)}</text>`
    + `<text x="${padL}" y="${height - 8}" fill="#8a94a6" font-size="10" font-family="monospace">${esc(points[0].date)} → ${esc(last.date)}</text>`
    + `</svg>`;
}

export function createTrading(root, { act, onOpenChange }) {
  const view = screen(root, { onOpenChange });
  let built = false;
  let symbolBox, accountBox, cardsBox, setupBox, heroBox, resultBoxes = [];
  let chartSymbol = "";

  function build() {
    if (built) return;
    built = true;
    root.classList.add("world", "lab", "lab-trading");
    const head = h("header", { class: "lib-head" },
      h("div", { class: "lib-title" }, h("span", { class: "lib-mark", "aria-hidden": "true" }),
        h("b", {}, "TRADING"), h("span", { class: "lib-crumb" }, "paper trading only")),
      h("form", { class: "route-form", autocomplete: "off" },
        symbolBox = h("input", { class: "field", name: "symbol", placeholder: "Symbol or company, e.g. AAPL or Coca-Cola", maxlength: "24", "aria-label": "Symbol or company name" }),
        accountBox = h("input", { class: "field", name: "account", placeholder: "Account $ (e.g. 5000)", maxlength: "12", inputmode: "decimal", "aria-label": "Account size in dollars" }),
        h("button", { class: "box small on", type: "submit" }, "Scan")),
      h("button", { class: "box small", type: "button", title: "Esc" }, "Close"));
    head.querySelector("form").addEventListener("submit", (event) => { event.preventDefault(); run("scan"); });
    head.querySelector("button[type=button]").onclick = () => view.close();
    const banner = h("p", { class: "trading-paper" },
      "Paper trading only — no real money. Nova never places an order: every card below is a plan to read, "
      + "and any order needs your explicit say-so first.");
    banner.style.cssText = "margin: 0 22px; padding: 10px 14px; border: 1px solid var(--warn); border-left: 3px solid var(--warn); "
      + "background: rgba(255, 181, 71, 0.07); color: var(--text); font: 500 13px/1.5 var(--sans);";
    // Quick picks: tap a name instead of typing a ticker.
    const chips = h("div", { class: "trading-chips" },
      h("span", { class: "trading-chips-label" }, "Quick picks:"),
      ...QUICK_PICKS.map(([ticker, name]) => h("button", {
        type: "button", class: "trading-chip", title: `${name} (${ticker})`,
        onclick: () => { symbolBox.value = ticker; loadChart(ticker); run("scan"); },
      }, ticker)));
    // The hero chart: the current symbol's recent closes, or a plain message when the
    // data can't be fetched — never invented numbers.
    heroBox = h("section", { class: "trading-hero", "aria-live": "polite" });
    cardsBox = h("div", { class: "skills-grid" },
      h("div", { class: "skill-cards" }, CARDS.map((card) => {
        const result = h("div", { class: "trading-result" });
        const button = h("button", { type: "button", class: "box small on",
          onclick: () => run(card.id, result, button) }, "Run");
        return h("article", { class: "skill-card ready" },
          h("header", {}, h("b", {}, card.title)),
          h("p", {}, card.what),
          button, result);
      })));
    resultBoxes = [...cardsBox.querySelectorAll(".trading-result")];
    setupBox = h("p", { class: "lab-problem", hidden: true, role: "status" });
    const hint = h("p", { class: "lib-hint" },
      "Free public data only (Yahoo Finance, SEC EDGAR, House Clerk) · Not financial advice — most people who day trade lose money · Esc");
    const helpWrap = h("div", { style: "padding: 0 22px;" });
    mountWhatCanIDo(helpWrap, "trading", { onPhrase: runPhrase });
    root.append(head, banner, chips, heroBox, cardsBox, setupBox, helpWrap, hint);
    loadChart(symbol() || "AAPL");
  }

  function symbol() {
    return resolveTradingSymbol(symbolBox?.value || "") || "";
  }

  async function loadChart(ticker) {
    // One chart at a time: a slower earlier reply must not overwrite a newer one.
    chartSymbol = ticker;
    heroBox.replaceChildren(h("p", { class: "trading-hero-note" }, `Loading ${ticker} chart…`));
    const answer = await act("trading", { action: "chart", symbol: ticker });
    if (chartSymbol !== ticker) return;
    if (!answer?.ok) {
      heroBox.replaceChildren(h("p", { class: "trading-hero-note" },
        answer?.error || `Couldn't load the ${ticker} chart — the data didn't come back.`));
      return;
    }
    const svg = chartSvg(answer.points || []);
    if (!svg) {
      heroBox.replaceChildren(h("p", { class: "trading-hero-note" },
        `No price history for ${ticker} yet — try again in a bit.`));
      return;
    }
    const change = answer.change_pct ?? 0;
    const head = h("div", { class: "trading-hero-head" },
      h("b", {}, answer.symbol || ticker),
      h("span", { class: "trading-hero-price" }, `$${Number(answer.last || 0).toFixed(2)}`),
      h("span", { class: change >= 0 ? "trading-hero-up" : "trading-hero-down" },
        `${change >= 0 ? "+" : ""}${change.toFixed(1)}% today`),
      h("span", { class: "trading-hero-range" }, `${(answer.points || []).length} closes`));
    const chart = h("div", { class: "trading-hero-chart" });
    chart.innerHTML = svg;
    heroBox.replaceChildren(head, chart);
  }

  function account() {
    const value = parseFloat((accountBox?.value || "").replace(/[$,\s]/g, ""));
    return Number.isFinite(value) && value > 0 ? value : undefined;
  }

  function showSetup(message) {
    if (!message) { setupBox.hidden = true; setupBox.textContent = ""; return; }
    setupBox.hidden = false;
    setupBox.textContent = message;
  }

  function renderResult(box, answer) {
    if (!answer.ok) {
      const unknown = String(answer.error || "").includes("Unknown action");
      box.replaceChildren(h("p", { class: "skill-note" },
        unknown
          ? "Trading isn't wired up in this Nova yet — it needs its one-line backend wiring before the cards can run."
          : (answer.error || "Nova didn't answer.")));
      if (!unknown) showSetup("Trading data needs the internet for live prices. If this keeps failing, check Nova is online and try again.");
      return;
    }
    showSetup("");
    const lines = (answer.lines || []).map((line) => h("p", { class: "skill-note" }, line));
    const items = (answer.items || []).map((item) => h("p", { class: "skill-note" },
      item.link
        ? h("a", { href: item.link, target: "_blank", rel: "noreferrer" }, item.title)
        : item.title,
      item.source ? ` — ${item.source}` : "", item.when ? ` · ${item.when}` : ""));
    box.replaceChildren(...lines, ...items);
  }

  async function run(action, resultBox, button) {
    build();
    const card = CARDS.find((entry) => entry.id === action) || CARDS[0];
    const box = resultBox || resultBoxes[CARDS.indexOf(card)];
    const raw = (symbolBox?.value || "").trim();
    const resolved = symbol();
    if (raw && !resolved) {
      box.replaceChildren(h("p", { class: "skill-note" },
        `Couldn't find "${raw}" as a symbol — try a ticker like KO for Coca-Cola, or tap one of the quick picks above.`));
      symbolBox.focus();
      return;
    }
    if (resolved && resolved !== chartSymbol) loadChart(resolved);
    if (action !== "scan" && !resolved) {
      box.replaceChildren(h("p", { class: "skill-note" }, "Type a symbol first, e.g. AAPL."));
      symbolBox.focus();
      return;
    }
    if (button) button.disabled = true;
    box.replaceChildren(h("p", { class: "skill-note" }, "…"));
    const args = { action, symbol: resolved || undefined, account: account() };
    const answer = await act("trading", args);
    renderResult(box, answer || { ok: false });
    if (button) button.disabled = false;
  }

  function runPhrase(phrase) {
    // A "What I can do" phrase runs the card it names, with the symbol box as it stands.
    build();
    const lower = phrase.toLowerCase();
    if (lower.includes("chart")) {
      const tokens = phrase.replace(/[?.!]/g, "").split(/\s+/).filter(Boolean);
      const pick = resolveTradingSymbol(tokens[tokens.length - 1] || "");
      if (pick) { symbolBox.value = pick; loadChart(pick); }
      else if (symbol()) loadChart(symbol());
      return;
    }
    const action = lower.includes("news") ? "news"
      : lower.includes("entry") ? "entry"
      : lower.includes("exit") ? "exit"
      : lower.includes("budget") || lower.includes("how big") || lower.includes("size the") ? "budget"
      : lower.includes("risk") ? "risk"
      : lower.includes("odds") || lower.includes("worked before") ? "odds"
      : "scan";
    if (action !== "scan") {
      const found = phrase.match(/[A-Z]{1,5}/);
      if (found && symbolBox && !symbolBox.value) symbolBox.value = found[0];
    }
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
