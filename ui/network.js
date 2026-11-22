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

export function createNetwork(root, { act, onOpenChange }) {
  const view = screen(root, { onOpenChange });
  let built = false;
  let cardsBox, setupBox, resultBoxes = [];

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
    root.append(head, banner, cardsBox, setupBox, helpWrap, hint);
  }

  function showSetup(message) {
    if (!message) { setupBox.hidden = true; setupBox.textContent = ""; return; }
    setupBox.hidden = false;
    setupBox.textContent = message;
  }

  function historyBars(history) {
    // A small bar chart of saved downloads: one bar per test, the tallest bar is the fastest run.
    if (!history || !history.length) return null;
    const downs = history.map((row) => Number(row.down_mbps) || 0);
    const best = Math.max(...downs, 1);
    const bars = h("div", { style: "display: flex; align-items: flex-end; gap: 3px; height: 56px; margin: 6px 0 2px;" },
      downs.slice(-20).map((value) => h("div", {
        title: `${value} Mbps down`,
        style: `flex: 1; min-width: 4px; height: ${Math.max(2, Math.round((value / best) * 52))}px; `
          + "background: var(--accent); border-radius: 2px 2px 0 0; opacity: 0.85;",
      })));
    const caption = h("p", { class: "skill-note" },
      `Last ${Math.min(downs.length, 20)} tests, oldest left, newest right — tallest bar is your fastest (${best} Mbps down).`);
    return h("div", {}, bars, caption);
  }

  function renderResult(box, answer, action) {
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
    const extra = [];
    if ((action === "speed" || action === "history") && answer.history?.length) {
      const bars = historyBars(answer.history);
      if (bars) extra.push(bars);
    }
    box.replaceChildren(...lines, ...extra);
  }

  async function run(action, resultBox, button) {
    build();
    const card = CARDS.find((entry) => entry.id === action) || CARDS[0];
    const box = resultBox || resultBoxes[CARDS.indexOf(card)];
    if (button) button.disabled = true;
    box.replaceChildren(h("p", { class: "skill-note" }, action === "devices" ? "Scanning your network…" : action === "speed" ? "Measuring — downloading, then uploading…" : "…"));
    const answer = await act("network", { action });
    renderResult(box, answer || { ok: false }, action);
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
