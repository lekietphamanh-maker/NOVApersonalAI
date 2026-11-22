// The Skills board: every skill Nova has, grouped, with what to say and whether it's ready here. Click an example to
// put it in the ask box; your own skills have Run.

import { h, screen } from "./lab.js";
import { mountWhatCanIDo } from "./whatcanido.js";

const STATES = { ready: "Ready", setup: "Set up", cloud: "On Claude", off: "Off" };

export function createSkills(root, { act, onOpenChange, ask }) {
  const $ = (selector) => root.querySelector(selector);
  const grid = $("#skills-grid"), search = $("#skills-search"), filters = $("#skills-filters"), keys = $("#skills-keys");
  let board = { entries: [], counts: {}, hotkeys: {} }, filter = "all";
  const view = screen(root, { onOpenChange, onOpen: refresh });
  mountWhatCanIDo(root, "skills", { onPhrase: (phrase) => { view.close(); ask(phrase); } });

  async function refresh() {
    const result = await act("skills_board");
    if (!result.ok) return;
    board = result;
    render();
    search.focus();
  }

  function matches(entry, words) {
    const text = `${entry.group} ${entry.name} ${entry.what} ${entry.say.join(" ")} ${entry.note}`.toLowerCase();
    return words.every((word) => text.includes(word));
  }

  function card(entry) {
    return h("article", { class: `skill-card ${entry.state}` },
      h("header", {}, h("b", {}, entry.name), h("span", { class: `skill-state ${entry.state}` }, STATES[entry.state] || entry.state)),
      h("p", {}, entry.what),
      entry.note ? h("p", { class: "skill-note" }, entry.note) : null,
      entry.say.length ? h("div", { class: "skill-says" }, entry.say.map((phrase) => h("button", {
        type: "button", class: "skill-say", title: "Put this in the ask box",
        onclick: () => { view.close(); ask(phrase); },
      }, `“${phrase}”`))) : null,
      entry.skill ? h("button", { type: "button", class: "box small on", onclick: () => act("skill_run", { name: entry.skill }) }, "Run") : null);
  }

  function render() {
    const words = search.value.toLowerCase().split(/\s+/).filter(Boolean);
    const shown = board.entries.filter((entry) => (filter === "all" || entry.state === filter) && matches(entry, words));
    const groups = [...new Set(shown.map((entry) => entry.group))];
    grid.replaceChildren(...(groups.length ? groups.map((group) => h("section", { class: "skill-group" },
      h("h4", {}, group), h("div", { class: "skill-cards" }, shown.filter((entry) => entry.group === group).map(card))))
      : [h("p", { class: "lab-empty" }, h("b", {}, "Nothing matches"), h("span", {}, "Try other words."))]));
    filters.replaceChildren(...["all", "ready", "setup", "cloud", "off"].map((state) => h("button", {
      type: "button", class: `box small${filter === state ? " on" : ""}`, "aria-pressed": String(filter === state),
      onclick: () => { filter = state; render(); },
    }, state === "all" ? `All ${board.entries.length}` : `${STATES[state]} ${board.counts[state] ?? 0}`)));
    const names = { talk: "talk", stop: "stop", clip: "keep a highlight", yes: "yes", no: "no" };
    keys.textContent = Object.entries(board.hotkeys || {}).map(([which, label]) => `${label}: ${names[which] || which}`).join("  ·  ");
  }

  search.addEventListener("input", render);
  $("#skills-close").onclick = () => view.close();
  return view;
}
