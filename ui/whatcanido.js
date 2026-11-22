// "What I can do": one small collapsible panel per lab tab, listing only the phrases for that tab. The phrases
// come from skills_board.py (the Skills board): each tab's entry there, copied word for word, so the panel never
// promises something Nova can't do. The Skills tab itself draws from the Talk entries; Trading draws from the
// Trading entry the integration adds to the board; Shannon has no example phrases on the board, so its panel
// shows what it does and what it needs instead.
import { h } from "./lab.js";

// The shared "try this phrase" action: put the phrase in the ask box and focus it. Most labs use
// exactly this; skills/build/trading pass their own onPhrase instead.
export function askPhrase(phrase) {
  const box = document.querySelector("#text");
  box.value = phrase;
  box.focus();
}

export const WHAT_CAN_I_DO = {
  galaxy: {
    name: "Knowledge Galaxy",
    what: "A 3D star map of everything Nova knows: wiki topics, memory facts, skills and sources orbiting as stars you can search and explore.",
    say: ["show me the galaxy", "open the star map", "what does Nova know"],
  },
  library: {
    name: "Library",
    what: "Your projects, repos and ideas by topic on the gold shelf.",
    say: ["open my library", "add an idea: a habit tracker for my bike rides"],
  },
  world: {
    name: "World",
    what: "A live globe: earthquakes, storms, fires and news by country.",
    say: ["what's happening in Japan this week"],
  },
  route: {
    name: "Fastest route",
    what: "The globe flies to the city, then the search spreads through the streets and the fastest way lights up; stops in the best order.",
    say: ["fastest way from District 12 to District 7 via Ben Thanh"],
  },
  rea: {
    name: "Rea: reverse engineering",
    what: "How an app or site is built, as a blueprint of its parts (REA through Claude Code).",
    say: ["reverse engineer notion.so and tell me how its sync works"],
  },
  shannon: {
    name: "Shannon: break into your own app",
    what: "An AI pentester that proves real holes in your app, with the fix.",
    say: [],
    note: "SHANNON screen; needs WSL2, Docker Desktop and an API key",
  },
  skills: {
    name: "Skills",
    what: "Everything Nova can do, grouped, with what to say and whether it's ready here.",
    say: ["Hey Nova, what's on today?", "timer for 10 minutes", "remember that my sister's birthday is May 3"],
  },
  build: {
    name: "Building mode",
    what: "A 3D electronics bench on a screen of its own: place a board (Arduino, ESP32, Pico, Blue Pill, Raspberry Pi 4) and parts, wire them pin to pin and press Run. Describe what you want and Nova builds it: she picks the board and parts, wires them, the bench checks the wiring (short circuits, 5 V into a 3.3 V pin), and the parts list and build steps appear beside it. Projects are saved by name.",
    say: ["building mode", "build me a blinking LED on an Uno", "a servo that follows a knob on an ESP32",
          "is my circuit wired right?", "explain this circuit with Anatomy"],
  },
  workplace: {
    name: "Workplace",
    what: "A board for notes, sketch notes you draw on, pictures and files (text, code, PDF, Word). Select something and Nova explains it: she highlights the key words, adds her note beside it, points at things and looks at pictures. Closing asks whether to save.",
    say: ["workplace mode", "explain this", "highlight what matters in these notes", "what's in this picture?"],
  },
  trading: {
    name: "Trading",
    what: "Paper trading only: scan the market for day-trade setups, check the news, time an entry, plan the exit, replay the odds, and size the trade to your budget. No order is ever placed without your say-so.",
    say: ["scan the market for day trades", "what's the news on AAPL?", "is TSLA a good entry today?",
          "plan my exit from TSLA", "how big should this trade be?",
          "how much can I risk on one trade?", "what are the odds this setup worked before?"],
  },
  network: {
    name: "Network",
    what: "Your home network in one place, measured on this PC: a real speed test, Wi-Fi and router status, who's on the network, a history of your speeds, and alerts when speed drops or a device goes quiet. No account, no key, nothing leaves the PC.",
    say: ["how fast is my internet?", "who's on my Wi-Fi?", "is anything wrong with my network?",
          "what's my usual internet speed?"],
  },
};

// Mount the panel for one tab into a container inside that tab's lab. Clicking a phrase calls onPhrase with it;
// without one, the phrase goes into the first text box in the same section, so it works in every lab as-is.
export function mountWhatCanIDo(container, tab, { onPhrase } = {}) {
  const entry = WHAT_CAN_I_DO[tab];
  if (!container || !entry) return null;
  const fill = (phrase) => {
    if (onPhrase) { onPhrase(phrase); return; }
    const box = container.closest("section")?.querySelector("input[type=text], input[type=search], input:not([type]), textarea");
    if (box) { box.value = phrase; box.focus(); }
  };
  const panel = h("details", { class: "what-can-i-do" },
    h("summary", {}, `What I can do — ${entry.name}`),
    h("p", { class: "muted small" }, entry.what),
    entry.note ? h("p", { class: "muted small" }, entry.note) : null,
    entry.say.length
      ? h("div", { class: "skill-says" }, entry.say.map((phrase) => h("button", {
        type: "button", class: "skill-say", title: "Try this phrase",
        onclick: () => fill(phrase),
      }, `“${phrase}”`)))
      : h("p", { class: "muted small" }, "No example phrases on the Skills board for this one yet — say what you want in your own words."));
  panel.style.cssText = "margin-top: 14px; padding: 10px 12px; border: 1px solid var(--line-strong); border-radius: 6px; background: rgba(10, 9, 6, 0.5);";
  const summary = panel.querySelector("summary");
  summary.style.cssText = "cursor: pointer; font: 600 11px var(--mono); letter-spacing: 0.14em; text-transform: uppercase; color: var(--accent);";
  container.append(panel);
  return panel;
}
