// Building mode: the 3D bench (ui/circuit/, from the owner's Robotics Lab) on a screen of its own, with Nova beside it.
// While it's open the bench goes to Nova with every question (build_sync): parts, wires and the bench's own checks as
// text. Nova builds on it through build_command events: a blueprint is drawn by the bench, which reports what it placed
// and what its checks say. The Blueprint panel holds the parts list and the build steps; projects are saved by name.
import { h, screen } from "./lab.js";
import { mountWhatCanIDo } from "./whatcanido.js";

const SYNC_MS = 500;
const START_TIMEOUT_MS = 60_000;
const BENCH_KEYS = ["Escape", "Delete", "Backspace", "r", "R"];  // the bench's own, once the owner has clicked in it

export function createBuild(root, { act, toast, onOpenChange }) {
  const host = root.querySelector("#build-bench"), nameBox = root.querySelector("#build-name"), reply = root.querySelector("#build-reply");
  const dirtyMark = root.querySelector("#build-dirty");
  const planTitle = root.querySelector("#build-plan-title"), planHint = root.querySelector("#build-plan-hint"),
    planBom = root.querySelector("#build-bom"), planStepsHead = root.querySelector("#build-steps-head"),
    planSteps = root.querySelector("#build-steps"), planNotes = root.querySelector("#build-notes");
  let bench = null, starting = null, armed = false, dirty = false, edited = false, applying = false, syncTimer = 0;
  let plan = { title: "", bom: [], steps: [], notes: "" };
  const view$ = screen(root, { onOpenChange, onOpen: () => { start(); sync(); } });

  function start() {
    if (!starting) {
      starting = (async () => {
        try {
          const [{ createBench }, { BOARDS }] = await Promise.all([import("./circuit/lab/lab.js"), import("./circuit/boards/index.js")]);
          await new Promise((resolve, reject) => {
            const giveUp = setTimeout(() => reject(new Error("it didn't start in time")), START_TIMEOUT_MS);
            bench = createBench(host, { boards: BOARDS, start: "uno", onChange: changed, onReady: () => { clearTimeout(giveUp); armed = true; resolve(); } });
            host.bench = bench;  // a handle for tests and the console
          });
          renderPlan();
          sync();
        } catch (error) {
          host.replaceChildren(h("p", { class: "build-note" }, `The 3D bench couldn't start here (${String(error.message || error).slice(0, 120)}).`));
        }
      })();
    }
    return starting;
  }

  function setDirty(on) { dirty = on; dirtyMark.hidden = !on; }
  function changed() {
    if (!armed) return;
    setDirty(true);
    edited ||= !applying;  // the owner's own changes since the last save, blueprint or open
    renderPlan();
    clearTimeout(syncTimer);
    syncTimer = setTimeout(sync, SYNC_MS);
  }
  function sync(extra = {}) {
    clearTimeout(syncTimer);
    if (!view$.isOpen()) { act("build_sync", { open: false }); return Promise.resolve({ ok: true }); }
    const ready = bench && armed;
    return act("build_sync", { open: true, name: nameBox.value, title: plan.title, text: ready ? bench.describe() : "The bench is still starting.",
      circuit: ready ? bench.getState() : null, bom: plan.bom, steps: plan.steps, notes: plan.notes, ...extra });
  }

  // ---------- the Blueprint panel: what's on the bench, what else to buy, the steps ----------
  function renderPlan() {
    const counts = new Map();
    for (const item of bench?.items || []) counts.set(item.name, (counts.get(item.name) || 0) + 1);
    planTitle.textContent = plan.title || "Blueprint";
    planHint.hidden = counts.size > 0 && (plan.steps.length > 0 || plan.bom.length > 0);
    planBom.replaceChildren(
      ...[...counts].map(([name, count]) => h("li", {}, h("b", {}, `×${count}`), h("span", {}, name))),
      ...plan.bom.map((entry) => h("li", { class: "extra" }, h("b", {}, `×${entry.qty}`), h("span", {}, entry.item), entry.note ? h("small", {}, entry.note) : null)));
    planStepsHead.hidden = plan.steps.length === 0;
    planSteps.replaceChildren(...plan.steps.map((step) => h("li", {}, step)));
    planNotes.textContent = plan.notes;
  }

  // ---------- Nova's blueprint ----------
  async function blueprint(event) {
    await start();
    if (!bench) { sync({ applied: event.token, result: { missing: ["the bench didn't start"] } }); return; }
    if (edited && !event.plan.keep) {  // a blueprint starts the bench fresh: the owner's own work is kept first
      const kept = await act("build_save", { name: "Before Nova's build", title: plan.title, circuit: bench.getState(), bom: plan.bom, steps: plan.steps, notes: plan.notes });
      if (kept.ok) toast("Your bench was saved as “Before Nova's build”.", "info");
    }
    let result;
    applying = true;
    try { result = bench.applyPlan(event.plan); } catch (error) { result = { missing: [String(error.message || error).slice(0, 80)] }; }
    applying = false;
    edited = false;
    plan = { title: event.plan.title, bom: event.plan.bom, steps: event.plan.steps, notes: event.plan.notes };
    if (event.plan.title && !nameBox.value) nameBox.value = event.plan.title;
    renderPlan();
    setDirty(true);
    sync({ applied: event.token, result });  // the bench's own checks go back to Nova, so she can fix what it flags
  }

  function command(event) {
    if (event.command === "open") { if (!view$.isOpen()) view$.open(); return; }
    if (event.command === "close") { close(); return; }
    if (event.command === "blueprint" && view$.isOpen()) blueprint(event);
    if (event.command === "anatomy" && view$.isOpen() && event.svg) showAnatomy(event.svg);
  }

  // ---------- Explain with Anatomy: the bench as an isometric figure ----------
  // The figure is drawn by building.py (Anatomy: one shaded box per part, wires arcing part to part, a framed
  // card with a live readout) and comes back as a standalone SVG string; it shows in the Blueprint panel.
  const anatomyIntro = h("p", { class: "build-note" }, "Draws the bench as an isometric figure: one shaded box per part, wires arcing between them, and a live readout of the board, the part and wire counts, and the bench's checks.");
  const anatomyBody = h("div", { class: "build-anatomy-body" }, anatomyIntro);
  const anatomyPanel = h("details", { class: "build-anatomy" },
    h("summary", {}, "Explain with Anatomy"), anatomyBody);
  anatomyPanel.style.cssText = "margin-top: 16px; padding: 10px 12px; border: 1px solid var(--line-strong); border-radius: 6px; background: rgba(10, 9, 6, 0.5);";
  anatomyPanel.querySelector("summary").style.cssText = "cursor: pointer; font: 600 11px var(--mono); letter-spacing: 0.14em; text-transform: uppercase; color: var(--accent);";
  root.querySelector("#build-plan").append(anatomyPanel);
  mountWhatCanIDo(root.querySelector("#build-plan"), "build", {
    onPhrase: (phrase) => {
      if (phrase === "explain this circuit with Anatomy") { explainWithAnatomy(); return; }
      const box = root.querySelector("#build-question");
      box.value = phrase;
      box.focus();
    },
  });

  function showAnatomy(svg) {
    anatomyPanel.open = true;
    const holder = h("div", {});
    holder.innerHTML = svg;  // our own generated markup, with every label escaped in building.py
    const svgEl = holder.querySelector("svg");
    if (svgEl) svgEl.style.cssText = "display: block; width: 100%; height: auto;";
    anatomyBody.replaceChildren(anatomyIntro, holder);
  }

  async function explainWithAnatomy() {
    await start();
    await sync();  // the bench as it is now goes first, so the figure matches it
    anatomyPanel.open = true;
    anatomyBody.replaceChildren(anatomyIntro, h("p", { class: "build-note" }, "Drawing the figure…"));
    const answer = await act("build_anatomy");
    if (!answer.ok || !answer.svg) {
      const missing = String(answer.error || "").includes("Unknown action");
      anatomyBody.replaceChildren(h("p", { class: "build-note" }, missing
        ? "Anatomy isn't wired up in this Nova yet — the Build wiring still needs applying."
        : `Couldn't draw the figure (${String(answer.error || "Nova didn't answer").slice(0, 120)}).`));
      return;
    }
    showAnatomy(answer.svg);
  }

  // ---------- projects ----------
  async function save() {
    if (!bench || !armed) return false;
    const answer = await act("build_save", { name: nameBox.value, title: plan.title, circuit: bench.getState(), bom: plan.bom, steps: plan.steps, notes: plan.notes });
    if (!answer.ok) return false;
    nameBox.value = answer.name;
    setDirty(false);
    edited = false;
    listSaved(answer.saved);
    toast(`Saved “${answer.name}”.`, "ok");
    return true;
  }
  function listSaved(saved) {
    root.querySelector("#build-saved").replaceChildren(...(saved.length ? saved.map((entry) => h("li", {},
      h("button", { type: "button", onclick: () => load(entry.name) }, h("b", {}, entry.name), h("small", {}, entry.saved)),
      h("button", { type: "button", class: "build-x", title: "Delete", onclick: async () => listSaved((await act("build_delete", { name: entry.name })).saved || []) }, "✕")))
      : [h("li", { class: "muted small" }, "Nothing saved yet.")]));
  }
  async function load(name) {
    if (dirty && !(await ask(`Open “${name}”? The bench has changes that aren't saved.`, ["Save first", "save"], ["Don't save", "drop"]))) return;
    const answer = await act("build_load", { name });
    if (!answer.ok || !answer.circuit) return;
    await start();
    if (!bench) return;
    plan = { title: answer.title, bom: answer.bom, steps: answer.steps, notes: answer.notes };
    nameBox.value = answer.name;
    bench.setState(answer.circuit);
    renderPlan();
    setDirty(false);
    edited = false;
    root.querySelector("#build-open").open = false;
    sync();
  }
  async function startOver() {
    if (dirty && !(await ask("Start a new project? The bench has changes that aren't saved.", ["Save first", "save"], ["Don't save", "drop"]))) return;
    await start();
    if (!bench) return;
    plan = { title: "", bom: [], steps: [], notes: "" };
    nameBox.value = "";
    bench.freeBuild();
    bench.addItem("board:uno", {});
    bench._changed();
    renderPlan();
    setDirty(false);
    edited = false;
  }
  function ask(question, ...choices) {  // Save / Don't save / Cancel
    const dialog = root.querySelector("#build-dialog");
    dialog.querySelector("p").textContent = question;
    return new Promise((resolve) => {
      const finish = async (choice) => {
        dialog.hidden = true;
        if (choice === "save") resolve(await save());
        else resolve(choice === "drop");
      };
      dialog.querySelector(".build-choices").replaceChildren(
        ...choices.map(([label, choice], index) => h("button", { type: "button", class: `box small${index ? "" : " on"}`, onclick: () => finish(choice) }, label)),
        h("button", { type: "button", class: "box small", onclick: () => finish("cancel") }, "Cancel"));
      dialog.hidden = false;
      dialog.querySelector("button").focus();
    });
  }

  function close() {
    if (!view$.isOpen()) return;
    view$.close();
    sync();  // tells Nova it's closed; the bench stays as it is for when it opens again
  }

  const anatomyButton = h("button", { type: "button", class: "box small",
    title: "Draw the bench as an isometric Anatomy figure", onclick: explainWithAnatomy }, "Explain with Anatomy");
  root.querySelector("#build-close").before(anatomyButton);
  root.querySelector("#build-save").onclick = save;
  root.querySelector("#build-new").onclick = startOver;
  root.querySelector("#build-close").onclick = close;
  root.querySelector("#build-open").addEventListener("toggle", async (event) => { if (event.target.open) listSaved((await act("build_list")).saved || []); });
  nameBox.addEventListener("input", () => { setDirty(true); clearTimeout(syncTimer); syncTimer = setTimeout(sync, SYNC_MS); });
  document.addEventListener("pointerdown", (event) => { if (bench && !host.contains(event.target)) bench.focused = false; }, true);
  root.querySelector("#build-ask").addEventListener("submit", (event) => {
    event.preventDefault();
    const box = root.querySelector("#build-question"), text = box.value.trim();
    if (!text) return;
    sync();  // the bench as it is now goes with the question
    act("send", { text });
    box.value = "";
    showReply("…");
  });
  function showReply(text) { reply.hidden = false; reply.textContent = text; }

  return {
    open: () => view$.open(),
    close,
    isOpen: view$.isOpen,
    command,
    showReply,
    handleKey(event) {
      const editing = document.activeElement?.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "");
      // The bench claims its own keys while the owner is working in it, so Esc cancels a wire instead of leaving.
      if (bench?.focused && !editing) return BENCH_KEYS.includes(event.key);
      if (event.key === "Escape") {
        if (!root.querySelector("#build-dialog").hidden) return false;
        if (editing) { document.activeElement.blur(); return true; }
        close();
        return true;
      }
      if (editing) return false;
      if (event.key.toLowerCase() === "s" && (event.ctrlKey || event.metaKey)) { save(); return true; }
      return false;
    },
  };
}
