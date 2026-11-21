// Building mode: the 3D bench (ui/circuit/, from the owner's Robotics Lab) on a screen of its own, with Nova beside it.
// While it's open the bench goes to Nova with every question (build_sync): parts, wires and the bench's own checks as
// text. Nova builds on it through build_command events: a blueprint is drawn by the bench, which reports what it placed
// and what its checks say. The Blueprint panel holds the parts list and the build steps; projects are saved by name.
import { h, screen } from "./lab.js";

const SYNC_MS = 500;
const START_TIMEOUT_MS = 60_000;
const BENCH_KEYS = ["Escape", "Delete", "Backspace", "r", "R", "f", "F"];  // the bench's own, once the owner has clicked in it

export function createBuild(root, { act, toast, onOpenChange }) {
  const host = root.querySelector("#build-bench"), nameBox = root.querySelector("#build-name"), reply = root.querySelector("#build-reply");
  const dirtyMark = root.querySelector("#build-dirty");
  let bench = null, starting = null, armed = false, dirty = false, syncTimer = 0;
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
    renderPlan();
    clearTimeout(syncTimer);
    syncTimer = setTimeout(sync, SYNC_MS);
  }
  function sync(extra = {}) {
    clearTimeout(syncTimer);
    if (!view$.isOpen()) { act("build_sync", { open: false }); return; }
    const ready = bench && armed;
    act("build_sync", { open: true, name: nameBox.value, title: plan.title, text: ready ? bench.describe() : "The bench is still starting.",
      circuit: ready ? bench.getState() : null, bom: plan.bom, steps: plan.steps, notes: plan.notes, ...extra });
  }

  // ---------- the Blueprint panel: what's on the bench, what else to buy, the steps ----------
  function renderPlan() {
    const counts = new Map();
    for (const item of bench?.items || []) counts.set(item.name, (counts.get(item.name) || 0) + 1);
    root.querySelector("#build-plan-title").textContent = plan.title || "Blueprint";
    root.querySelector("#build-plan-hint").hidden = counts.size > 0 && (plan.steps.length > 0 || plan.bom.length > 0);
    root.querySelector("#build-bom").replaceChildren(
      ...[...counts].map(([name, count]) => h("li", {}, h("b", {}, `×${count}`), h("span", {}, name))),
      ...plan.bom.map((entry) => h("li", { class: "extra" }, h("b", {}, `×${entry.qty}`), h("span", {}, entry.item), entry.note ? h("small", {}, entry.note) : null)));
    root.querySelector("#build-steps-head").hidden = plan.steps.length === 0;
    root.querySelector("#build-steps").replaceChildren(...plan.steps.map((step) => h("li", {}, step)));
    root.querySelector("#build-notes").textContent = plan.notes;
  }

  // ---------- Nova's blueprint ----------
  async function blueprint(event) {
    await start();
    if (!bench) return;
    const result = bench.applyPlan(event.plan);
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
  }

  // ---------- projects ----------
  async function save() {
    if (!bench || !armed) return false;
    const answer = await act("build_save", { name: nameBox.value, title: plan.title, circuit: bench.getState(), bom: plan.bom, steps: plan.steps, notes: plan.notes });
    if (!answer.ok) return false;
    nameBox.value = answer.name;
    setDirty(false);
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
    if (!answer.ok) return;
    await start();
    plan = { title: answer.title, bom: answer.bom, steps: answer.steps, notes: answer.notes };
    nameBox.value = answer.name;
    if (answer.circuit) bench.setState(answer.circuit);
    renderPlan();
    setDirty(false);
    root.querySelector("#build-open").open = false;
    sync();
  }
  async function startOver() {
    if (dirty && !(await ask("Start a new project? The bench has changes that aren't saved.", ["Save first", "save"], ["Don't save", "drop"]))) return;
    await start();
    plan = { title: "", bom: [], steps: [], notes: "" };
    nameBox.value = "";
    bench.freeBuild();
    bench.addItem("board:uno", {});
    bench._changed();
    renderPlan();
    setDirty(false);
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
      // The bench claims its own keys while the owner is working in it, so Esc cancels a wire instead of leaving.
      if (bench?.focused) return BENCH_KEYS.includes(event.key);
      const editing = document.activeElement?.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "");
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
