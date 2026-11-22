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

export function createTrading(root, { act, onOpenChange }) {
  const view = screen(root, { onOpenChange });
  let built = false;
  let symbolBox, accountBox, cardsBox, setupBox, resultBoxes = [];

  function build() {
    if (built) return;
    built = true;
    root.classList.add("world", "lab", "lab-trading");
    const head = h("header", { class: "lib-head" },
      h("div", { class: "lib-title" }, h("span", { class: "lib-mark", "aria-hidden": "true" }),
        h("b", {}, "TRADING"), h("span", { class: "lib-crumb" }, "paper trading only")),
      h("form", { class: "route-form", autocomplete: "off" },
        symbolBox = h("input", { class: "field", name: "symbol", placeholder: "Symbol, e.g. AAPL", maxlength: "12", "aria-label": "Symbol" }),
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
    root.append(head, banner, cardsBox, setupBox, helpWrap, hint);
  }

  function symbol() {
    const value = (symbolBox?.value || "").trim().toUpperCase();
    return SYMBOL.test(value) ? value : "";
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
    if (action !== "scan" && !symbol()) {
      box.replaceChildren(h("p", { class: "skill-note" }, "Type a symbol first, e.g. AAPL."));
      symbolBox.focus();
      return;
    }
    if (button) button.disabled = true;
    box.replaceChildren(h("p", { class: "skill-note" }, "…"));
    const args = { action, symbol: symbol() || undefined, account: account() };
    const answer = await act("trading", args);
    renderResult(box, answer || { ok: false });
    if (button) button.disabled = false;
  }

  function runPhrase(phrase) {
    // A "What I can do" phrase runs the card it names, with the symbol box as it stands.
    const lower = phrase.toLowerCase();
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
