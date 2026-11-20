// Advance mode's board, to the right of the orb: the Library, what Nova can do, the owner's widgets, separate apps.
// Nova owns the data (advance_mode.py); this only draws it and sends the owner's clicks back.
import { h } from "./lab.js";

const STATE_LABEL = { ready: "Ready", setup: "Set up", cloud: "Cloud", off: "Off" };
const APP_ACTION = { window: "Open window", docker: "Start", download: "Get it", web: "Open", own: "Open" };

export function createAdvance(root, { act, openLibrary, openSkills, ask, toast }) {
  let board = null, apps = [], editing = false, clockTimer = 0, state = {};
  const rows = {
    library: root.querySelector("#adv-library"),
    skills: root.querySelector("#adv-skills"),
    widgets: root.querySelector("#adv-widgets"),
    apps: root.querySelector("#adv-apps"),
  };

  async function load() {
    const answer = await act("advance_board");
    if (!answer.ok) return;
    board = answer;
    apps = answer.apps;
    drawLibrary();
    drawSkills();
    drawWidgets();
    drawApps();
    act("advance_apps");  // Docker's answer comes later, as an advance_apps event
  }

  function strip(row, cards, empty) {
    row.replaceChildren(...(cards.length ? cards : [h("p", { class: "adv-empty" }, empty)]));
  }

  function drawLibrary() {
    const projects = board.library.projects, topics = board.library.topics;
    const cards = [
      ...topics.map((topic) => h("button", { class: "adv-card topic", type: "button", title: `Open the ${topic.name} shelf`,
        onclick: () => openLibrary({ kind: "topic", name: topic.name }) },
        h("span", { class: "adv-kicker" }, "Topic"), h("b", {}, topic.name), h("small", {}, [[topic.projects, "project"], [topic.ideas, "idea"], [topic.notes, "note"]].filter(([count]) => count).map(([count, word]) => `${count} ${word}${count === 1 ? "" : "s"}`).filter(Boolean).join(" · ") || topic.summary || ""))),
      ...projects.map((project) => h("button", { class: `adv-card status-${project.status}`, type: "button", title: project.next || project.note || "",
        onclick: () => openLibrary({ kind: "project", name: project.title }) },
        h("span", { class: "adv-kicker" }, [project.topic, project.status].filter(Boolean).join(" · ")), h("b", {}, project.title),
        h("small", {}, project.next ? `Next: ${project.next}` : project.repo ? "Repo linked" : ""))),
    ];
    strip(rows.library, cards, "The Library is empty. Say “add Project W to my library”.");
  }

  function drawSkills() {
    const counts = board.counts || {};
    root.querySelector("#adv-skills-count").textContent = `${counts.ready || 0} ready · ${counts.setup || 0} to set up`;
    strip(rows.skills, board.skills.map((skill) => h("button", {
      class: `adv-card skill ${skill.state}`, type: "button", title: skill.what,
      onclick: () => (skill.say[0] ? ask(skill.say[0]) : openSkills()),
    }, h("span", { class: "adv-kicker" }, `${skill.group} · ${STATE_LABEL[skill.state] || skill.state}`), h("b", {}, skill.name),
       h("small", {}, skill.say[0] ? `“${skill.say[0]}”` : skill.note || ""))), "");
  }

  // ---------- widgets ----------
  const chosen = () => ((state.settings || {}).advance_widgets || []);
  function saveWidgets(list) { act("advance_widgets", { widgets: list }); }
  function move(id, by) {
    const list = [...chosen()], at = list.indexOf(id), to = at + by;
    if (to < 0 || to >= list.length) return;
    [list[at], list[to]] = [list[to], list[at]];
    saveWidgets(list);
  }

  function clockText() {
    const now = new Date();
    return [now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      now.toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" })];
  }
  function left(ends) {
    const seconds = Math.max(0, Math.round((Number(ends) - Date.now()) / 1000));
    const minutes = Math.floor(seconds / 60);
    return `${minutes >= 60 ? Math.floor(minutes / 60) + ":" + String(minutes % 60).padStart(2, "0") : minutes}:${String(seconds % 60).padStart(2, "0")}`;
  }
  const lines = (items, empty) => (items.length ? items.map((item) => h("li", {}, item)) : [h("li", { class: "dim" }, empty)]);

  const WIDGET_BODY = {
    clock: () => { const [time, date] = clockText(); return [h("b", { class: "adv-big", "data-clock": "" }, time), h("small", {}, date)]; },
    weather: () => (state.weather_now ? [h("b", { class: "adv-big" }, state.weather_now.short), h("small", {}, state.weather_now.place)]
      : [h("small", {}, "Set a place in SETTINGS → Location.")]),
    timers: () => [h("ul", {}, lines((state.timers || []).map((timer) => `${timer.done ? "Done" : left(timer.ends)} · ${timer.label || "Timer"}`), "No timers. “Timer for 10 minutes”"))],
    reminders: () => [h("ul", {}, lines((state.reminders || []).slice(0, 4).map((item) => item.text), "Nothing coming up."))],
    tasks: () => [h("ul", {}, lines((state.tasks || []).slice(0, 5), "No tasks."))],
    music: () => (state.music ? [h("b", {}, state.music.title), h("small", {}, [state.music.artist, state.music.playing ? "playing" : "paused"].filter(Boolean).join(" · ")),
      h("div", { class: "adv-row" }, ...[["previous", "⏮"], ["play_pause", state.music.playing ? "❚❚" : "▶"], ["next", "⏭"]]
        .map(([action, label]) => h("button", { class: "box small", type: "button", onclick: () => act("media", { action }) }, label)))]
      : [h("small", {}, "Nothing playing.")]),
    pc: () => { const system = state.system || {}; return [h("ul", {}, lines([system.ram && `RAM ${system.ram}`, system.gpu && `GPU ${system.gpu}`, state.model && `Model ${state.model}`].filter(Boolean), "—"))]; },
    brain: () => { const brain = state.brain || {}; return [h("b", {}, brain.label || "Nobody yet"), h("small", {}, brain.why || "Ask something.")]; },
    news: () => [h("ul", {}, lines(((state.brief || {}).headlines || []).slice(0, 4).map((item) => item.title || item.text || ""), "Turn on the brief (BRIEF)."))],
  };

  function drawWidgets() {
    if (!board) return;
    const names = board.widgets, list = chosen();
    const cards = list.map((id, index) => h("article", { class: "adv-widget", "data-widget": id },
      h("header", {}, h("span", { class: "adv-kicker" }, names[id]),
        editing ? h("span", { class: "adv-edit" },
          h("button", { type: "button", title: "Move left", disabled: index === 0, onclick: () => move(id, -1) }, "←"),
          h("button", { type: "button", title: "Move right", disabled: index === list.length - 1, onclick: () => move(id, 1) }, "→"),
          h("button", { type: "button", title: "Remove", onclick: () => saveWidgets(list.filter((item) => item !== id)) }, "✕")) : null),
      ...WIDGET_BODY[id]()));
    const missing = Object.keys(names).filter((id) => !list.includes(id));
    if (editing && missing.length) {
      const select = h("select", { "aria-label": "Add a widget" }, h("option", { value: "" }, "+ Add a widget"),
        ...missing.map((id) => h("option", { value: id }, names[id])));
      select.onchange = () => { if (select.value) saveWidgets([...list, select.value]); };
      cards.push(h("article", { class: "adv-widget add" }, select));
    }
    strip(rows.widgets, cards, "No widgets. Press Edit to add some.");
    root.querySelector("#adv-widgets-edit").textContent = editing ? "Done" : "Edit";
  }

  // ---------- separate apps ----------
  function appButtons(app) {
    const buttons = [];
    if (app.kind === "docker") {
      if (app.state === "running") buttons.push(["Open", () => act("app_open", { id: app.id })], ["Stop", () => act("app_stop", { id: app.id })]);
      else if (app.state === "no-docker") buttons.push(["Get Docker", () => act("open_url", { url: "https://www.docker.com/products/docker-desktop/" })]);
      else buttons.push([app.state === "stopped" ? "Start" : "Get and start", () => act("app_open", { id: app.id })]);
    } else if (app.kind === "download") {
      buttons.push([app.state === "installed" ? "Open" : "Get it", () => act("app_open", { id: app.id })]);
    } else {
      buttons.push([APP_ACTION[app.kind], () => act("app_open", { id: app.id })]);
    }
    if (app.page && app.kind !== "web") buttons.push(["Page", () => act("app_page", { id: app.id })]);
    if (app.kind === "own") buttons.push(["✕", async () => { const answer = await act("app_remove", { id: app.id }); if (answer.ok) { apps = answer.apps; drawApps(); } }]);
    return buttons.map(([label, run]) => h("button", { class: "box small", type: "button", onclick: run }, label));
  }

  function drawApps() {
    const cards = apps.map((app) => h("article", { class: `adv-card app ${app.kind} ${app.state}` },
      h("span", { class: "adv-kicker" }, [app.kind === "own" ? "Yours" : app.kind === "window" ? "Nova screen" : app.kind === "docker" ? "Docker" : app.kind === "download" ? "Desktop app" : "Web",
        app.state === "running" ? "running" : app.state === "installed" ? "installed" : ""].filter(Boolean).join(" · ")),
      h("b", {}, app.name), h("small", {}, app.what), app.runs_on ? h("small", { class: "dim" }, `AI: ${app.runs_on}`) : null,
      h("div", { class: "adv-row" }, ...appButtons(app))));
    strip(rows.apps, cards, "");
  }

  root.querySelector("#adv-widgets-edit").onclick = () => { editing = !editing; drawWidgets(); };
  root.querySelector("#adv-skills-all").onclick = () => openSkills();
  root.querySelector("#adv-library-all").onclick = () => openLibrary(null);
  root.querySelector("#adv-app-form").onsubmit = async (event) => {
    event.preventDefault();
    const form = event.target;
    const answer = await act("app_add", { name: form.name.value, target: form.target.value });
    if (!answer.ok) return;
    form.reset();
    form.closest("details").open = false;
    apps = answer.apps;
    drawApps();
    toast("Added to your apps.", "info");
  };

  return {
    open() {
      root.hidden = false;
      load();
      clearInterval(clockTimer);
      clockTimer = setInterval(() => {
        const clock = root.querySelector("[data-clock]");
        if (clock) clock.textContent = clockText()[0];
        if (chosen().includes("timers") && (state.timers || []).length) drawWidgets();
      }, 1000);
    },
    close() { root.hidden = true; clearInterval(clockTimer); },
    isOpen: () => !root.hidden,
    reload: load,
    setApps(list) { apps = list; if (board) drawApps(); },
    render(next) {
      const widgetSignature = JSON.stringify([next.settings && next.settings.advance_widgets, next.weather_now, next.timers, next.reminders,
        next.tasks, next.music, next.system, next.model, next.brain, (next.brief || {}).headlines]);
      state = next;
      if (root.hidden || widgetSignature === root.dataset.widgets) return;
      root.dataset.widgets = widgetSignature;
      drawWidgets();
    },
  };
}
