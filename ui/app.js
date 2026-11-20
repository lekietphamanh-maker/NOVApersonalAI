// Nova's HUD: renders the state Nova streams, sends the user's actions back. Nova owns all state.
import { createCore } from "./core.js";
import { createMindMap, ICONS, PALETTE } from "./mindmap.js";
import { createLibrary } from "./library.js";
import { createWorld } from "./world.js";
import { createRoute } from "./route.js";
import { createRea } from "./rea.js";
import { createShannon } from "./shannon.js";
import { createSkills } from "./skills.js";
import { h } from "./lab.js";
import { createAdvance } from "./advance.js";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const token = new URLSearchParams(location.hash.slice(1)).get("token") || "";
const ACCENTS = { gold: "255, 176, 64", cyan: "59, 228, 255", crimson: "255, 59, 92", violet: "163, 123, 255", mint: "76, 245, 181" };
const OUTLETS = { "nbcnews.com": "NBC News", "cnn.com": "CNN", "abcnews.com": "ABC News", "apnews.com": "AP", "reuters.com": "Reuters",
  "npr.org": "NPR", "bbc.com": "BBC", "foxnews.com": "Fox News", "nytimes.com": "New York Times", "vnexpress.net": "VnExpress" };
const SUGGESTED_INTERESTS = ["AI", "game dev", "Python", "gadgets", "fitness", "space", "music", "Vietnam", "startups"];
const READABLE_FILES = [".txt", ".md", ".csv", ".html", ".json", ".py", ".log"];

const core = createCore($("#core"));
const mindmap = createMindMap($("#mindmap"), { onSelect: selectIdea, onChange: mapChanged,
  onExpand: (path) => askAlfredAbout(path) });
let state = {};
const library = createLibrary($("#library"), { act: (...args) => act(...args), toast: (...args) => toast(...args),
  confirm: (...args) => yesNo(...args), onOpenChange: (open) => {
    $("[data-act=library]").classList.toggle("on", open);
    if (open && mapOpen) openMap(false);
    if (open && world.isOpen()) world.close();
    if (open) closeLabs();
    act("library_view", { open });
  } });
const world = createWorld($("#world"), { act: (...args) => act(...args), onOpenChange: (open) => {
  $("[data-act=world]").classList.toggle("on", open);
  if (open && library.isOpen()) library.close();
  if (open && mapOpen) openMap(false);
  if (open) closeLabs();
  if (open && routeView.isOpen()) routeView.close();
} });
const routeView = createRoute($("#route"), { act: (...args) => act(...args), onOpenChange: (open) => {
  $("[data-act=route]").classList.toggle("on", open);
  if (open && world.isOpen()) world.close();
  if (open && library.isOpen()) library.close();
  if (open) closeLabs();
} });
// A route starts on the globe: it flies to the city while the roads are worked out, then dives into the street map.
const ROUTE_FLIGHT_MS = 2200, DIVE_MS = 450;
let routeFlight = 0;
const calm = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
function routeFocus(place) {
  if (calm()) return;
  if (!world.isOpen()) world.open();
  world.flyTo(place.lon, place.lat, 6, ROUTE_FLIGHT_MS);
  routeFlight = performance.now();
}
function showRoute(route) {
  if (calm()) { routeView.show(route); return; }
  if (!routeFlight) {  // no focus came first (an old Nova, or a cached route): fly now
    const middle = (key) => route.places.reduce((sum, place) => sum + place[key], 0) / route.places.length;
    routeFocus({ lon: middle("lon"), lat: middle("lat") });
  }
  const wait = Math.max(0, ROUTE_FLIGHT_MS + 100 - (performance.now() - routeFlight));
  routeFlight = 0;
  setTimeout(() => {
    $("#world").classList.add("dive-out");
    setTimeout(() => {
      $("#world").classList.remove("dive-out");
      routeView.show(route);  // opening the route closes the globe
      $("#route").classList.add("dive-in");
      setTimeout(() => $("#route").classList.remove("dive-in"), 1000);
    }, DIVE_MS);
  }, wait);
}

// Full-screen views: opening one closes the others.
function labOpened(name, open) {
  $(`[data-act=${name}]`).classList.toggle("on", open);
  if (!open && solo === name) window.close();
  if (!open) return;
  for (const other of [world, routeView, library, rea, shannon, skills]) if (other && other !== labs[name] && other.isOpen()) other.close();
}
const labs = {};
function closeLabs() { for (const lab of Object.values(labs)) if (lab.isOpen()) lab.close(); }
const rea = labs.rea = createRea($("#rea"), { act: (...args) => act(...args), onOpenChange: (open) => labOpened("rea", open) });
const shannon = labs.shannon = createShannon($("#shannon"), { act: (...args) => act(...args), onOpenChange: (open) => labOpened("shannon", open) });
const skills = labs.skills = createSkills($("#skills"), { act: (...args) => act(...args), onOpenChange: (open) => labOpened("skills", open),
  ask: (phrase) => { const box = $("#text"); box.value = phrase; box.focus(); } });
// A Nova screen opened as its own app window from Advance mode (…#token=…&app=rea): only that screen, and closing it
// closes the window.
const soloApp = new URLSearchParams(location.hash.slice(1)).get("app");
const solo = labs[soloApp] ? soloApp : "";
if (solo) { document.body.classList.add("solo"); document.title = `Nova · ${solo[0].toUpperCase()}${solo.slice(1)}`; }
const advance = createAdvance($("#advance-board"), { act: (...args) => act(...args), toast: (...args) => toast(...args),
  openLibrary: (target) => (target ? library.command({ command: "show", target }) : library.open()),
  openSkills: () => skills.open(),
  ask: (phrase) => { const box = $("#text"); box.value = phrase; box.focus(); } });
function renderAdvance() {
  const on = Boolean((state.settings || {}).advance) && !solo;
  document.body.classList.toggle("advance", on);
  // The Now playing widget takes the floating music card's place on the board.
  document.body.classList.toggle("music-widget", on && ((state.settings || {}).advance_widgets || []).includes("music"));
  $("[data-act=advance]").classList.toggle("on", on);
  if (on && !advance.isOpen()) advance.open();
  else if (!on && advance.isOpen()) advance.close();
  advance.render(state);
}
let online = false;
let offlineTimer = 0;
let openPane = null;
let shownApproval = null;
let modalOnClose = null;
const chatIds = new Set();

// ---------- talking to Nova ----------

async function act(name, args = {}) {
  let result;
  try {
    const response = await fetch("/api/action", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Nova-Token": token },
      body: JSON.stringify({ name, args }),
    });
    result = await response.json();
  } catch {
    toast("Nova is not answering.", "error");
    return { ok: false };
  }
  if (result.need_consent) {
    if (await consent(result.need_consent, result.detail || {})) return act(name, { ...args, consented: true });
    return { ok: false, cancelled: true };
  }
  if (result.ok === false && result.error) toast(result.error, "warn");
  return result;
}

function connect() {
  const events = new EventSource(`/api/events?token=${encodeURIComponent(token)}`);
  events.onopen = () => setOnline(true);
  events.onerror = () => setOnline(false); // EventSource reconnects by itself
  events.onmessage = (message) => handle(JSON.parse(message.data));
}

function setOnline(value) {
  online = value;
  clearTimeout(offlineTimer);
  if (value) $("#offline").hidden = true;
  else offlineTimer = setTimeout(() => { $("#offline").hidden = false; }, 6000);
  renderCore();
}

function handle(event) {
  switch (event.type) {
    case "snapshot":
      state = event.state;
      $("#chat").replaceChildren();
      chatIds.clear();
      event.chat.forEach((item) => addChat(item, false));
      render();
      (event.notices || []).forEach((notice) => toast(notice.text, notice.tone, notice.action));
      if (new URLSearchParams(location.hash.slice(1)).get("open") === "creative") {
        history.replaceState(null, "", `#token=${encodeURIComponent(token)}`); // not again on reload
        act("creative");
      }
      if (solo && !labs[solo].isOpen()) labs[solo].open();
      if (new URLSearchParams(location.hash.slice(1)).get("open") === "library") {
        history.replaceState(null, "", `#token=${encodeURIComponent(token)}`);
        library.open();
      } else if (library.isOpen()) act("library_view", { open: true }); // Nova restarted: the Library is still here
      break;
    case "open_pane": if (event.pane === "notes") openMap(true); else if (openPane !== event.pane) setPane(event.pane); break;
    case "state":
      for (const [key, value] of Object.entries(event.patch)) {
        state[key] = value && typeof value === "object" && !Array.isArray(value) && state[key] && typeof state[key] === "object"
          ? { ...state[key], ...value } : value;
      }
      render();
      break;
    case "chat": addChat(event.item, true); break;
    case "advance_apps": advance.setApps(event.apps); break;
    case "level": core.setLevel(event.level); showLevel(event.level); break;
    case "toast": toast(event.text, event.tone, event.action); break;
    case "review": showReview(event.title, event.warning, event.text); break;
    case "creative": openCreative(event.url); break;
    case "close_creative": if (!$("#creative-layer").hidden) closeCreative(); break;
    case "audio_status": audioStatus(event.text, event.tone); break;
    case "reply_delta": $("#reply").textContent = event.text; break;
    case "bands": musicBands = event.bands; break;
    case "library_command": library.command(event); break;
    case "library_changed": library.reload(); break;
    case "world_focus": world.open(event); break;
    case "world_data": if (world.isOpen()) world.setData(event); break;
    case "route_focus": routeFocus(event); break;
    case "route_view": showRoute(event.route); break;
    case "route_error": routeFlight = 0; routeView.open(); routeView.error(event.text); break;
    case "rea_job": rea.job(event.job); break;
    case "rea_step": rea.step(event); break;
    case "rea_ready": rea.ready(event); break;
    case "rea_command": rea.command(event.command); break;
    case "shannon_job": shannon.job(event.job); break;
    case "shannon_line": shannon.line(event); break;
    case "shannon_ready": shannon.ready(event); break;
    case "shannon_command": shannon.command(event.command); break;
  }
}

// ---------- rendering ----------

// ---------- music: the cover spinning as a vinyl disc inside a ring of bars that move with the sound ----------
let musicBands = new Array(24).fill(0);
const coverImage = new Image();
let coverKey = "";
let discAngle = 0;
let discLast = performance.now();
function renderMusic() {
  const music = state.music;
  $("#music").hidden = !music;
  if (!music) return;
  $("#music-title").textContent = music.title;
  $("#music-artist").textContent = [music.artist, music.app].filter(Boolean).join(" · ");
  $("#music-play").textContent = music.playing ? "❚❚" : "▶";
  if (music.cover && music.key !== coverKey) { coverKey = music.key; coverImage.src = music.cover; }
  if (!music.cover) coverKey = "";
}
function drawMusic(now) {
  requestAnimationFrame(drawMusic);
  const music = state.music;
  const elapsed = (now - discLast) / 1000;
  discLast = now;
  if (!music || $("#music").hidden) return;
  if (music.playing) discAngle += elapsed * 3.46; // 33 rpm
  else musicBands = musicBands.map((level) => level * 0.9);
  const canvas = $("#music-disc"), context = canvas.getContext("2d");
  const size = canvas.width, center = size / 2, radius = size * 0.27;
  const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent-rgb").trim() || "255, 176, 64";
  context.clearRect(0, 0, size, size);
  const count = 72;
  context.lineWidth = 4;
  context.lineCap = "round";
  for (let index = 0; index < count; index++) {
    const mirrored = index <= count / 2 ? index : count - index;
    const level = musicBands[Math.min(musicBands.length - 1, Math.floor((mirrored * musicBands.length) / (count / 2 + 1)))] || 0;
    const angle = -Math.PI / 2 + (2 * Math.PI * index) / count;
    const inner = radius * 1.12, outer = radius * (1.2 + 0.78 * level);
    context.strokeStyle = `rgba(${accent}, ${0.45 + 0.55 * level})`;
    context.beginPath();
    context.moveTo(center + Math.cos(angle) * inner, center + Math.sin(angle) * inner);
    context.lineTo(center + Math.cos(angle) * outer, center + Math.sin(angle) * outer);
    context.stroke();
  }
  context.fillStyle = "#09090d";
  context.beginPath(); context.arc(center, center, radius, 0, Math.PI * 2); context.fill();
  context.lineWidth = 1;
  for (let groove = 0; groove < 5; groove++) {
    context.strokeStyle = "rgba(255, 255, 255, 0.07)";
    context.beginPath(); context.arc(center, center, radius * (0.6 + 0.08 * groove), 0, Math.PI * 2); context.stroke();
  }
  context.save();
  context.translate(center, center);
  context.rotate(discAngle);
  context.beginPath(); context.arc(0, 0, radius * 0.52, 0, Math.PI * 2); context.clip();
  if (coverKey && coverImage.complete && coverImage.naturalWidth) {
    context.drawImage(coverImage, -radius * 0.52, -radius * 0.52, radius * 1.04, radius * 1.04);
  } else {
    context.fillStyle = `rgb(${accent})`;
    context.fillRect(-radius, -radius, radius * 2, radius * 2);
    context.fillStyle = "rgba(255, 255, 255, 0.35)";
    context.beginPath(); context.moveTo(0, 0); context.arc(0, 0, radius, 0, 0.7); context.fill();
  }
  context.restore();
  context.lineWidth = 3;
  context.strokeStyle = `rgba(${accent}, 0.8)`;
  context.beginPath(); context.arc(center, center, radius, 0, Math.PI * 2); context.stroke();
  context.fillStyle = "#06060a";
  context.beginPath(); context.arc(center, center, radius * 0.07, 0, Math.PI * 2); context.fill();
  context.strokeStyle = "rgba(255, 255, 255, 0.16)";
  context.lineWidth = 6;
  context.beginPath(); context.arc(center, center, radius * 0.88, 3.5, 4.3); context.stroke(); // a still sheen: reads as spinning
}
requestAnimationFrame(drawMusic);

let hotkeyCapture = null; // recording a new hotkey: { which, held: Set of key codes, most: [] }

function render() {
  const switches = state.switches || {};
  $("#takeover").hidden = !state.acting;
  $$("[data-switch]").forEach((button) => button.classList.toggle("on", Boolean(switches[button.dataset.switch])));
  $("[data-switch=assist]").hidden = !state.windows;
  $("#speak-toggle").setAttribute("aria-pressed", String(Boolean(switches.speak)));
  $("#speak-toggle").textContent = switches.speak ? "🔊" : "🔈";
  const voice = state.voice || {};
  const status = $("#status-text");
  status.textContent = voice.text || "";
  status.className = `status-line ${voice.tone === "warn" || voice.tone === "error" || voice.tone === "ok" ? voice.tone : ""}`;
  $("#edition").textContent = state.edition === "usb" ? "USB EDITION" : "LOCAL CORE";
  renderModel();
  renderAnswering();
  renderTelegram();
  renderUpdate();
  renderDiscover();
  renderClaude();
  renderFreeCloud();
  renderAccent();
  renderAdvance();
  renderCore();
  renderTasks();
  renderSkills();
  renderReminders();
  renderBrief();
  renderConnections();
  renderGoogleMcp();
  renderKnowledge();
  renderTuning();
  renderApproval();
  renderReadouts();
  renderTimers();
  renderSteps();
  renderFacts();
  renderNotes();
  renderGestures();
  renderDownloads();
  renderNewsDesk();
  $("#keep-running").checked = (state.settings || {}).keep_running !== false;
  $("#mini-orb").checked = (state.settings || {}).mini_orb !== false;
  if (document.activeElement?.id !== "owner-name") $("#owner-name").value = (state.settings || {}).owner_name || "";
  $("#send").disabled = Boolean(state.busy);
}

function renderReadouts() {
  const model = state.model || {};
  const coreStatus = $("#ro-core");
  coreStatus.textContent = !online ? "OFFLINE" : model.ollama === "offline" ? "MODEL OFFLINE" : state.busy ? "WORKING" : "ONLINE";
  coreStatus.classList.toggle("bad", !online || model.ollama === "offline");
  const brain = state.brain || {};
  const why = { personal: "PERSONAL, KEPT LOCAL", offline: "OFFLINE", screen: "SCREEN, KEPT LOCAL", online: "ONLINE", asked: "ASKED FOR CLAUDE",
    auto: "AUTO · EVERYDAY, ON THIS PC", "hard question": "AUTO · HARD QUESTION" };
  $("#ro-model").textContent = /^(Claude|Ollama Cloud)/.test(brain.label || "")
    ? `${brain.label} · ${why[brain.why] || "ONLINE"}`.toUpperCase()
    : model.name ? `${model.name}${model.placement ? " · " + model.placement : ""}${brain.why && brain.why !== "off" ? ` · ${why[brain.why] || brain.why}` : ""}` : "…";
  $("#ro-latency").textContent = state.latency_ms ? `${(state.latency_ms / 1000).toFixed(1)} S` : "—";
  const timing = state.timing || {};
  $("#ro-latency").title = timing.summary ? `Last answer: ${timing.summary}` : "";
  $("#timing-last").textContent = timing.summary ? `Last answer${timing.local ? " (the model on this PC)" : ""}: first words after ${(timing.latency_ms / 1000).toFixed(1)} s · ${timing.summary}` : "";
  const heart = state.heart || {};
  $("#ro-heart-row").hidden = !heart.on;
  const weatherNow = state.weather_now;
  $("#ro-weather-row").hidden = !weatherNow;
  $("#ro-weather").textContent = weatherNow ? `${weatherNow.short} · ${weatherNow.place}`.toUpperCase() : "—";
  const place = state.place;
  $("#location-info").textContent = place
    ? `Weather and local news for ${place.label}${place.source === "device" ? ` (this PC's location${place.how ? `, from ${place.how}` : ""}; checked again every hour)` : ""}.`
    : "Not set. Nova uses it for the weather and local news (“Hey Nova, what's the weather?”).";
  $("#location-forget").hidden = !place;
  renderMusic();
  const keys = state.hotkeys || {};
  if (!hotkeyCapture) {
    $("#hotkey-talk").textContent = keys.talk || "Ctrl+Alt";
    $("#hotkey-stop").textContent = keys.stop || "Esc";
    $("#hotkey-clip").textContent = keys.clip || "F9";
    $("#hotkey-yes").textContent = keys.yes || "F8";
    $("#hotkey-no").textContent = keys.no || "F10";
    $("#hotkey-dictate").textContent = keys.dictate || "Ctrl+Win";
  }
  const secondBrain = state.second_brain || {};
  $("#ro-brain-row").hidden = !secondBrain.on;
  $("#ro-brain").textContent = secondBrain.running
    ? `${secondBrain.status} · ${secondBrain.notes_today} today${secondBrain.last ? ` · last ${secondBrain.last}` : ""}`.toUpperCase()
    : secondBrain.on ? "PAUSED" : "—";
  $("#brain-toggle").textContent = secondBrain.on ? "Turn off" : "Turn on";
  $("#brain-now").hidden = !secondBrain.running;
  $("#brain-ingest").hidden = !secondBrain.on;
  $("#brain-info").textContent = secondBrain.on
    ? `${secondBrain.running ? `On: ${secondBrain.status}` : "Paused"}. ${secondBrain.notes_today} summaries today, ${secondBrain.gathered} things gathered since the last one. Sources go to ${secondBrain.vault}\\raw, topic pages to wiki (drop your own articles and PDFs in raw, then Ingest).`
      + (secondBrain.videos && !secondBrain.videos_ready ? " Install Whisper (Voice & audio) to also write down what videos say." : "")
    : "Off. Nova can keep notes of what you read and watch on this PC, summed up into your Obsidian vault every 20 minutes. Only on this PC.";
  if (document.activeElement?.id !== "brain-vault") $("#brain-vault").value = secondBrain.vault || "";
  if (document.activeElement?.id !== "brain-exclude") $("#brain-exclude").value = secondBrain.exclude || "";
  $("#brain-videos").checked = secondBrain.videos !== false;
  const pcs = state.pcs || {};
  const seen = (pcs.others || []).map((other) => `${other.pc} was here ${other.seen}`).join(", ");
  $("#pcs-toggle").textContent = pcs.on ? "Turn off" : "Turn on";
  $("#pcs-wiki").hidden = !pcs.on || !pcs.wiki || pcs.wiki === pcs.pc;
  $("#pcs-steps").hidden = Boolean(pcs.on && seen);
  $("#pcs-info").textContent = pcs.error || (pcs.on
    ? `On. This PC is ${pcs.pc}; it shares what Nova remembers and the second brain through ${pcs.folder}. `
      + (seen ? `${seen}.` : "No other PC seen yet: is Syncthing sharing this folder, and is this on there too?")
      + (pcs.wiki ? ` ${pcs.wiki === pcs.pc ? "This PC" : pcs.wiki} writes the wiki.` : "")
    : "Off. Use Nova on a second PC (a laptop) with the same memory and second brain: the two PCs keep one folder in sync, directly, with no cloud.");
  $("#facts-where").textContent = pcs.on ? "Shared with your other PC." : "Kept on this PC only.";
  $("#ro-heart").textContent = heart.bpm ? `${heart.bpm} BPM${heart.rmssd ? ` · HRV ${heart.rmssd} MS` : ""}` : "WAITING…";
  $("#heart-toggle").textContent = heart.on ? "Disconnect heart rate" : "Connect heart rate";
  $("#heart-toggle").classList.toggle("on", !heart.on);
  $("#heart-status").textContent = heart.on ? heart.status || "" : "";
}

function renderTimers() {
  const timers = state.timers || [];
  const box = $("#timers");
  if (box.dataset.signature !== JSON.stringify(timers)) {
    box.dataset.signature = JSON.stringify(timers);
    box.replaceChildren(...timers.map((timer) => {
      const element = document.createElement("div");
      element.className = `timer ${timer.done ? "done" : ""}`;
      element.dataset.ends = String(timer.ends);
      const name = document.createElement("span");
      name.textContent = timer.label || "Timer";
      const cancel = Object.assign(document.createElement("button"), { textContent: "✕" });
      cancel.setAttribute("aria-label", `Cancel ${timer.label || "timer"}`);
      cancel.onclick = () => act("cancel_timer", { id: timer.id });
      element.append(document.createElement("b"), name, cancel);
      return element;
    }));
  }
  $$(".timer", box).forEach((element) => {
    const left = Math.max(0, Math.round((Number(element.dataset.ends) - Date.now()) / 1000));
    const hours = Math.floor(left / 3600), minutes = Math.floor((left % 3600) / 60), seconds = left % 60;
    element.firstChild.textContent = `${hours ? hours + ":" : ""}${String(minutes).padStart(hours ? 2 : 1, "0")}:${String(seconds).padStart(2, "0")}`;
  });
}

function renderSteps() {
  const walkthrough = state.walkthrough;
  const list = $("#steps");
  list.hidden = !walkthrough;
  $("#steps-actions").hidden = !walkthrough || walkthrough.done;
  if (!walkthrough) return;
  list.replaceChildren(...walkthrough.steps.map((step, index) => {
    const item = document.createElement("li");
    item.textContent = step;
    item.className = walkthrough.done || index < walkthrough.index ? "done" : index === walkthrough.index ? "now" : "";
    return item;
  }));
}

function renderFacts() {
  const facts = state.facts || [];
  const list = $("#facts");
  if (list.dataset.signature === JSON.stringify(facts)) return;
  list.dataset.signature = JSON.stringify(facts);
  list.replaceChildren(...(facts.length ? facts : [{ id: 0, fact: "Nothing yet." }]).map((item) => {
    const row = document.createElement("li");
    row.append(Object.assign(document.createElement("span"), { textContent: item.fact }));
    if (item.id) {
      const forget = Object.assign(document.createElement("button"), { textContent: "✕" });
      forget.setAttribute("aria-label", `Forget ${item.fact}`);
      forget.onclick = () => act("forget_fact", { id: item.id });
      row.append(forget);
    }
    return row;
  }));
}

function renderDownloads() {
  const switches = state.switches || {}, heart = state.heart || {}, pcs = state.pcs || {};
  $("#need-iphone-state").textContent = switches.phone ? "PHONE ON" : "";
  $("#need-fitness-state").textContent = heart.on ? "CONNECTED" : "";
  $("#need-laptop-state").textContent = pcs.on ? ((pcs.others || []).length ? "SHARING" : "ON · WAITING") : "";
  const items = state.downloads || [];
  const list = $("#downloads-list");
  if (list.dataset.signature === JSON.stringify(items)) return;
  list.dataset.signature = JSON.stringify(items);
  const missing = items.filter((item) => item.done === false && !item.optional).length;
  const optional = items.filter((item) => item.done === false && item.optional).length;
  $("#downloads-count").textContent = missing ? `${missing} needed` : optional ? `${optional} optional` : items.length ? "all set" : "";
  if (missing && !$("#downloads").dataset.touched) $("#downloads").open = true;
  list.replaceChildren(...items.map((item) => {
    const row = document.createElement("li");
    row.className = item.done ? "done" : item.done === false ? "todo" : "";
    const mark = Object.assign(document.createElement("span"), { className: "mark", textContent: item.done ? "✓" : item.done === false ? "○" : "·" });
    const words = document.createElement("div");
    words.append(Object.assign(document.createElement("b"), { textContent: `${item.name}${item.optional ? " · optional" : ""}` }),
      Object.assign(document.createElement("span"), { className: "about", textContent: [item.why, item.size].filter(Boolean).join(" · ") }));
    row.append(mark, words);
    if (!item.done && (item.action || item.url || item.focus)) {
      const button = Object.assign(document.createElement("button"), { className: `box small ${item.optional ? "" : "on"}`,
        textContent: item.url ? "Get it ↗" : item.focus ? "Set up" : "Download" });
      button.onclick = async () => {
        if (item.url) act("open_url", { url: item.url });
        else if (item.focus) { $(item.focus).scrollIntoView({ block: "center" }); $(item.focus).focus(); }
        else await act(item.action.name, item.action.args || {});
        setTimeout(() => act("downloads"), 2500);
      };
      row.append(button);
    } else row.append(document.createElement("span"));
    return row;
  }));
}

const NEWS_TOPICS = ["world", "politics", "business", "finance", "technology", "ai", "science", "health", "entertainment",
  "sports", "environment", "education", "general"];
function renderNewsDesk() {
  const news = state.news || {};
  const last = news.last;
  $("#news-toggle").textContent = news.on ? "Turn off" : "Turn on";
  $("#news-toggle").classList.toggle("on", !news.on);
  $("#news-run").hidden = !news.on;
  $("#news-run").disabled = Boolean(news.running);
  $("#news-run").textContent = news.running ? "Collecting…" : "Collect now";
  $("#news-key-forget").hidden = !news.key;
  $("#news-key").placeholder = news.key ? "GNews key saved on this PC (paste a new one to replace it)" : "GNews API key (free at gnews.io, optional)";
  $("#news-info").textContent = !news.on
    ? "Off. Every morning at 06:00 Nova can collect the news from GNews, GDELT and news sites, have the AI on this PC summarize and score each article, and keep it in a searchable database, so “what happened today?” gets answers with sources."
    : `On: every day at ${news.at || "06:00"} (or as soon as Nova runs, if the PC was off). ${news.total || 0} articles saved.`
      + (last ? ` Last run ${String(last.finished_at || last.started_at).slice(0, 16).replace("T", " ")} UTC: ${last.added} new, ${last.processed} read by the AI${last.failed ? `, ${last.failed} unreadable` : ""}.` : " Not run yet.")
      + (news.key ? "" : " Without a GNews key it uses GDELT and the news sites' feeds.");
  $("#news-status").textContent = news.status || "";
  const problems = (last && last.errors) || [];
  let list = $("#news-problems");
  if (!list) { list = Object.assign(document.createElement("ul"), { id: "news-problems", className: "news-problems" }); $("#news-status").after(list); }
  list.replaceChildren(...problems.map((problem) => Object.assign(document.createElement("li"), { textContent: problem })));
  const topics = $("#news-category");
  if (topics.options.length === 1) topics.append(...NEWS_TOPICS.map((topic) => new Option(topic === "ai" ? "AI" : topic[0].toUpperCase() + topic.slice(1), topic)));
}

async function searchNews() {
  const result = await act("news_search", { query: $("#news-query").value, days: Number($("#news-days").value), category: $("#news-category").value });
  if (!result.ok) return;
  const box = $("#news-results");
  if (!result.items.length) { box.replaceChildren(Object.assign(document.createElement("p"), { className: "muted small", textContent: "No articles for that yet." })); return; }
  box.replaceChildren(...result.items.map((item) => {
    const button = document.createElement("button");
    button.className = "news-item";
    button.append(Object.assign(document.createElement("b"), { textContent: item.title }),
      Object.assign(document.createElement("span"), { className: "meta", textContent:
        [item.publisher, item.published_at.slice(0, 16).replace("T", " ") + " UTC", item.category, item.importance ? `${item.importance}/10` : ""].filter(Boolean).join(" · ") }),
      Object.assign(document.createElement("span"), { className: "about", textContent: item.summary || "" }));
    button.onclick = () => act("open_url", { url: item.url });
    return button;
  }));
}

const POSES = { Pointing_Up: "☝", ILoveYou: "🤟" };

// Settings → This PC: live load every 3 s while Settings is open (Nova samples only while asked).
async function pollPc() {
  if (openPane !== "settings") return;
  const stats = await act("pc_stats");
  if (stats.ok !== false) renderPc(stats);
  setTimeout(pollPc, 3000);
}
function renderPc(stats) {
  const bar = (id, percent) => { $(id).style.width = `${Math.max(0, Math.min(100, percent || 0))}%`; };
  $("#live-cpu").textContent = stats.cpu !== undefined ? `${Math.round(stats.cpu)}%` : "—"; bar("#live-cpu-bar", stats.cpu);
  $("#live-ram").textContent = stats.ram_total ? `${stats.ram_used} / ${stats.ram_total} GB` : "—"; bar("#live-ram-bar", stats.ram_total ? 100 * stats.ram_used / stats.ram_total : 0);
  $("#live-gpu").textContent = stats.gpu !== undefined ? `${Math.round(stats.gpu)}%` : "n/a"; bar("#live-gpu-bar", stats.gpu);
  $("#live-vram").textContent = stats.vram_gb !== undefined ? `${stats.vram_gb}${stats.vram_total ? ` / ${stats.vram_total}` : ""} GB` : "n/a";
  bar("#live-vram-bar", stats.vram_total ? 100 * (stats.vram_gb || 0) / stats.vram_total : 0);
  const models = stats.models || [];
  $("#live-model").textContent = stats.ollama ? stats.ollama
    : models.length ? models.map((model) => `${model.name}: ${model.size_gb} GB, ${model.vram_gb} GB of it in graphics memory → runs on ${model.where} (measured by Ollama)`).join(" · ")
    : `${stats.model || "The model"} isn't loaded right now (Ollama loads it on the next question).`;
  $("#gpu-tip").textContent = stats.tip || "";
}
function renderGestures() {
  const gestures = state.gestures || {};
  const actions = gestures.actions || {};
  const select = $("#gesture-action");
  if (select.dataset.signature !== JSON.stringify(actions)) {
    select.replaceChildren(...Object.entries(actions).map(([value, label]) => new Option(label, value)));
    select.dataset.signature = JSON.stringify(actions);
  }
  $("#gesture-phrase").hidden = select.value !== "ask";
  const recording = Boolean(gestures.recording);
  $("#gesture-add").disabled = recording;
  $("#gesture-add").textContent = $("#gesture-pose").value !== "record" ? "Save" : recording ? "Recording… hold it" : "Record · hold your pose 3 s";
  $("#gesture-status").textContent = recording ? "RECORDING · HOLD YOUR POSE IN FRONT OF THE WEBCAM…" : "";
  $("#gesture-status").className = `status-line ${recording ? "ok" : ""}`;
  const list = $("#gesture-list");
  const custom = gestures.custom || [];
  if (list.dataset.signature === JSON.stringify(custom)) return;
  list.dataset.signature = JSON.stringify(custom);
  list.replaceChildren(...(custom.length ? custom : [{ id: "", name: "None yet: name one, pick what it does, then hold the pose while Nova records it." }]).map((item) => {
    const row = document.createElement("li");
    const how = item.pose ? POSES[item.pose] || item.pose : `🖐 own pose`;
    const does = (actions[item.action] || item.action || "") + (item.action === "ask" && item.phrase ? `: “${item.phrase}”` : "");
    row.append(Object.assign(document.createElement("span"), { textContent: item.id ? `${item.name} · ${how} → ${does}` : item.name }));
    if (item.id) {
      const remove = Object.assign(document.createElement("button"), { textContent: "✕" });
      remove.setAttribute("aria-label", `Delete ${item.name}`);
      remove.onclick = () => act("gesture_delete", { id: item.id });
      row.append(remove);
    }
    return row;
  }));
}

function renderCore() {
  const voice = state.voice || {};
  let mode = "idle", label = "";
  if (!online) mode = "offline";
  else if (state.speaking) mode = "speak";
  else if (state.busy) mode = "think";
  else if (voice.tone === "listen" || voice.tone === "record") mode = "listen";
  else if ((state.switches || {}).mic) mode = "armed";
  if (voice.tone === "error" && renderCore.lastError !== voice.text) { core.flashError(); renderCore.lastError = voice.text; }
  if (state.approval) label = "WAITING FOR YOU";
  core.setMode(mode, label);
}

function renderAccent() {
  const settings = state.settings || {};
  const accent = settings.advance && !solo ? "crimson" : ACCENTS[settings.accent] ? settings.accent : "gold";
  document.documentElement.dataset.accent = accent;
  core.setAccent(ACCENTS[accent]);
  mindmap.setAccent(ACCENTS[accent]);
  $$("#swatches button").forEach((button) => button.classList.toggle("on", button.dataset.accent === accent));
}

function renderClaude() {
  const claude = state.claude || {}, api = claude.api || { entries: [], providers: [] }, cloud = claude.cloud || { agents: [] };
  const models = Object.entries(claude.models || {});
  const select = $("#claude-model");
  if (select.dataset.signature !== JSON.stringify(models)) {
    select.replaceChildren(...models.map(([id, name]) => new Option(name + (id === "claude-sonnet-5-5" ? " (default)" : id === "claude-opus-5-5" ? ": smartest" : ": fastest, cheapest"), id)));
    select.dataset.signature = JSON.stringify(models);
  }
  if (document.activeElement !== select) select.value = claude.model || "claude-sonnet-5-5";
  if (document.activeElement !== $("#claude-effort")) $("#claude-effort").value = claude.effort || "medium";
  const providers = $("#api-provider");
  if (providers.dataset.signature !== String(api.providers.length)) {
    providers.replaceChildren(...api.providers.map((item) => new Option(item.label, item.key)));
    providers.dataset.signature = String(api.providers.length);
    providerChanged();
  }
  $("#api-list").replaceChildren(...(api.entries.length ? api.entries.map((entry) => h("li", { class: entry.id === api.active ? "on" : "" },
    h("span", {}, h("b", {}, entry.label), h("small", {}, ` ${entry.provider_label}${entry.has_key ? "" : " · no key"}`)),
    entry.id === api.active ? h("span", { class: "brain-active" }, "in use") :
      h("button", { class: "box small", type: "button", onclick: () => act("api_brain_use", { id: entry.id }) }, "Use"),
    h("button", { class: "box small", type: "button", onclick: () => act("api_brain_remove", { id: entry.id }) }, "Remove")))
    : [h("li", { class: "muted small" }, "No API brain yet: add one below with your key.")]));
  $("#cloud-agents").replaceChildren(...cloud.agents.map((agent) => h("li", { class: agent.key === cloud.agent ? "on" : "" },
    h("span", {}, h("b", {}, agent.label), h("small", {}, ` ${agent.account}${agent.full ? " · uses Nova's tools" : " · answers only"}`)),
    agent.installed ? h("button", { class: "box small", type: "button", onclick: () => act("cloud_agent_connect", { agent: agent.key }) }, "Connect account")
      : h("button", { class: "box small", type: "button", onclick: () => act("cloud_agent_install", { agent: agent.key }) }, "Install"),
    agent.key === cloud.agent ? h("span", { class: "brain-active" }, "in use") :
      h("button", { class: "box small", type: "button", onclick: () => act("cloud_agent_use", { agent: agent.key }) }, "Use"))));
  const onPlan = claude.via === "plan";
  $("#claude-connectors-row").hidden = cloud.agent !== "claude-code" || claude.usb;
  $("#cloud-fallback-row").hidden = Boolean(claude.usb);
  $("#cloud-fallback").checked = Boolean(claude.cloud_fallback);
  $("#claude-connectors").checked = Boolean(claude.connectors);
  $("#need-claude-state").textContent = claude.on ? "on" : "";
  const brain = state.brain || {};
  const lastAnswer = claude.on && brain.label ? ` Last answer: ${brain.label}${brain.why && !/^(online|asked)$/.test(brain.why) ? ` (${brain.why})` : ""}.` : "";
  const activeEntry = api.entries.find((entry) => entry.id === api.active);
  const activeAgent = cloud.agents.find((agent) => agent.key === cloud.agent);
  $("#claude-info").textContent = claude.usb ? "The USB Edition stays fully offline."
    : activeEntry ? `${activeEntry.label}: billed per question to your account with that provider.${claude.on && !onPlan ? " It's answering now." : " Choose API brain above to use it."}` + (!onPlan ? lastAnswer : "")
    : "Any AI with an API key: Claude, OpenAI, Gemini, OpenRouter, Groq, DeepSeek, Mistral, xAI, Together, or your own server.";
  $("#cloud-info").textContent = claude.usb ? "" : activeAgent ? (activeAgent.installed
    ? `${activeAgent.label} on ${activeAgent.account}: no API key, it counts toward that account's usage.${claude.on && onPlan ? " It's answering now." : " Choose Cloud brain above to use it."}` + (onPlan ? lastAnswer : "")
    : `${activeAgent.label} isn't on this PC yet: Install, then Connect account and sign in.`) : "";
}

function providerChanged() {
  const providers = (state.claude?.api?.providers) || [];
  const chosen = providers.find((item) => item.key === $("#api-provider").value) || providers[0];
  if (!chosen) return;
  $("#api-base").value = chosen.base_url;
  $("#api-base").hidden = chosen.kind === "anthropic";
  $("#api-key").placeholder = chosen.kind === "anthropic" ? "Anthropic API key (sk-ant-…)" : `API key${chosen.key === "custom" ? " (if the server needs one)" : ""}`;
  $("#api-hint").textContent = chosen.hint ? `Key from: ${chosen.hint}` : "";
  $("#api-models").replaceChildren(...(chosen.kind === "anthropic" ? Object.keys(state.claude?.models || {}) : []).map((id) => new Option(id, id)));
}

function renderTelegram() {
  const telegram = state.telegram || {};
  $("#need-telegram").hidden = Boolean(telegram.usb);
  $("#telegram-toggle").textContent = telegram.on ? "Turn Telegram off" : "Turn Telegram on";
  $("#telegram-toggle").classList.toggle("on", !telegram.on);
  $("#telegram-unpair").hidden = !telegram.owner;
  $("#telegram-token-forget").hidden = !telegram.token;
  $("#telegram-token").placeholder = telegram.token ? "Token saved. Paste a new one to switch bots." : "Bot token from @BotFather (123456789:AA…)";
  $("#telegram-code-row").hidden = !telegram.code;
  $("#telegram-code").textContent = telegram.code || "";
  $("#need-telegram-state").textContent = telegram.on && telegram.owner ? "on" : "";
  const relayBrain = $("#telegram-relay-brain").value;
  $("#telegram-relay-key").hidden = !(relayBrain === "ollama" || (relayBrain === "claude" && !telegram.claude_key));
  $("#telegram-relay-key").placeholder = relayBrain === "ollama" ? "ollama.com API key (ollama.com → Settings → Keys)" : "Anthropic API key (sk-ant-…)";
  $("#telegram-relay-remove").hidden = !telegram.relay;
  $("#telegram-relay-setup").textContent = telegram.relay_busy ? "Working…" : telegram.relay ? "Set up again" : "Set up relay";
  $("#telegram-relay-setup").disabled = Boolean(telegram.relay_busy) || !telegram.token;
  $("#telegram-relay-info").textContent = !telegram.token ? "Save your bot token above first."
    : telegram.relay ? `Relay on: with the PC off, ${telegram.relay === "claude" ? "Claude Haiku" : telegram.relay === "ollama" ? "Ollama Cloud" : "Nova"} answers on Telegram and reminders still come. To change it, set it up again.`
    : "Not set up: with the PC off, your messages wait until it's back on.";
  $("#telegram-info").textContent = !telegram.token ? "No bot yet: follow step 1."
    : !telegram.on ? "Token saved. Turn Telegram on to start."
    : [telegram.status, telegram.owner ? `Answers only ${telegram.owner === "you" ? "you" : telegram.owner}.` : "Not paired yet: send the code below to your bot."].filter(Boolean).join(" ");
}

function renderAnswering() {
  const answering = state.answering || {};
  const claude = state.claude || {};
  for (const [id, value] of [["#brain-choice", answering.brain || "local"], ["#private-topics", answering.private || "secrets"]]) {
    if (document.activeElement !== $(id)) $(id).value = value;
  }
  $("#brain-choice").disabled = Boolean(answering.usb);
  $("#private-topics").disabled = answering.brain === "local";
  const apiEntry = (claude.api?.entries || []).find((entry) => entry.id === claude.api?.active);
  const cloudAgent = (claude.cloud?.agents || []).find((agent) => agent.key === claude.cloud?.agent);
  const name = answering.brain === "api" ? `Your API brain (${apiEntry ? apiEntry.label : "none added yet"})`
    : answering.brain === "cloud" ? `Your Cloud brain (${cloudAgent ? cloudAgent.label : "Claude Code"})`
    : answering.brain === "free" ? "Ollama Cloud" : "";
  const answers = state.answers || [];
  const list = $("#answers");
  if (list.dataset.signature !== JSON.stringify(answers)) {
    list.dataset.signature = JSON.stringify(answers);
    list.replaceChildren(...(answers.length ? answers : [{ time: "", brain: "Nothing asked yet", why: "" }]).map((entry) =>
      Object.assign(document.createElement("li"), { textContent: [entry.time, entry.brain, entry.why].filter(Boolean).join(" · ") })));
  }
  $("#answering-info").textContent = answering.usb ? "The USB Edition stays fully offline: the AI on this PC answers everything."
    : answering.brain === "local" ? "The AI on this PC answers everything: private, and it works offline."
    : answering.brain === "auto" ? `The AI on this PC answers everyday questions; hard ones (code, research, analysis, long or multi-part questions) go to ${claude.via === "plan" ? (cloudAgent ? cloudAgent.label : "your Cloud brain") : apiEntry ? apiEntry.label : "Ollama Cloud"} while this PC is online. Passwords and mail: Nova asks first. Say “ask Claude …” to send any question, “privately …” to keep it here.`
    : `${name} answers while this PC is online; offline, the AI on this PC does. `
      + (answering.private === "personal" ? "Anything personal (mail, notes, what Nova remembers, where you are, your screen, health, money, family) stays on this PC."
        : "Weather, news and everyday questions go to it. Passwords and mail: Nova asks you out loud first (“yes” sends it, “no” keeps it here). Start with “privately” to keep any question here.");
}

function renderFreeCloud() {
  const free = state.free_cloud || {};
  const claude = state.claude || {};
  $("#free-cloud-signin").hidden = !free.on || free.status === "ready";
  if (document.activeElement !== $("#free-cloud-model")) $("#free-cloud-model").value = free.model || "gpt-oss:120b-cloud";
  const when = claude.on && claude.key ? "when Claude can't answer" : "whenever this PC is online";
  $("#free-cloud-info").textContent = free.usb ? "The USB Edition stays fully offline."
    : !free.on ? "Free with an Ollama account: a much larger open model on Ollama's servers. Ollama limits free use per session and per week. Choose Ollama Cloud above to use it."
    : `${free.model} answers ${when}. Status: ${free.status || "checking…"}.`
      + (free.status && free.status !== "ready" && /sign in/.test(free.status) ? " Sign in once with your Ollama account (free at ollama.com)." : "");
}

function renderModel() {
  const model = state.model || {};
  const chip = $("#model-chip");
  const placement = model.placement || "";
  chip.textContent = model.name ? `${model.name}${placement ? " · " + placement : ""}` : "MODEL …";
  chip.className = `chip ${model.ollama === "offline" ? "off" : /GPU/.test(placement) ? "gpu" : /CPU/.test(placement) ? "cpu" : ""}`;
  $("#model-info").textContent = model.name
    ? `Using ${model.name}. Best for this PC: ${model.recommended || model.name}${model.reason ? ` (${model.reason})` : ""}.`
    : "Checking Ollama…";
  const select = $("#model-select");
  const options = [["auto", `Auto — pick for this PC${model.recommended ? ` (${model.recommended})` : ""}`],
    ...(model.installed || []).map((name) => [name, name])];
  const wanted = (state.settings || {}).model || "auto";
  if (select.dataset.signature !== JSON.stringify(options)) {
    select.replaceChildren(...options.map(([value, text]) => new Option(text, value)));
    select.dataset.signature = JSON.stringify(options);
  }
  select.value = options.some(([value]) => value === wanted) ? wanted : "auto";
  const offer = model.offer;
  $("#model-offer").hidden = !offer;
  if (offer) {
    $("#model-offer-text").textContent = `${offer.stronger ? `This PC can run a stronger model, ${offer.name}` : `${offer.name} would be faster on this PC`} (${offer.reason}). Download about ${offer.size_gb} GB?`;
    $("#model-offer-button").disabled = Boolean(model.downloading);
    $("#model-offer-button").textContent = model.downloading ? "Downloading…" : `Download ${offer.name}`;
  }
  $("#vision-info").textContent = model.vision
    ? `Vision: ${model.vision}. In creative mode Nova can name anything you show the camera.`
    : "Vision: none. Creative mode names 80 everyday kinds of objects; a vision model (about 3 GB, runs on this PC) can name anything.";
  $("#vision-button").hidden = Boolean(model.vision);
  $("#vision-button").disabled = Boolean(model.vision_downloading);
  $("#vision-button").textContent = model.vision_downloading ? "Downloading…" : "Download vision model · 3.2 GB";
  facts($("#model-facts"), [["Ollama", model.ollama || "…"], ["Placement", placement || "—"], ["Context", model.context || "—"]]);
  const installed = model.installed || [];
  for (const id of ["#version-base", "#compare-a", "#compare-b"]) {
    const select = $(id);
    if (select.dataset.signature !== JSON.stringify(installed)) {
      const keep = select.value;
      select.replaceChildren(...installed.map((name) => new Option(name, name)));
      select.dataset.signature = JSON.stringify(installed);
      if (installed.includes(keep)) select.value = keep;
      else if (id === "#compare-b" && installed.length > 1) select.value = installed[1];
    }
  }
  const versions = installed.filter((name) => name.startsWith("nova-"));
  const list = $("#versions-list");
  if (list.dataset.signature !== JSON.stringify(versions)) {
    list.dataset.signature = JSON.stringify(versions);
    list.replaceChildren(...(versions.length ? versions : [""]).map((name) => {
      const row = document.createElement("li");
      row.append(Object.assign(document.createElement("span"), { textContent: name || "No custom versions yet." }));
      if (name) {
        const remove = Object.assign(document.createElement("button"), { textContent: "✕" });
        remove.setAttribute("aria-label", `Delete ${name}`);
        remove.onclick = async () => { if (await yesNo("Delete this version?", `${name} will be removed from Ollama. The model it was made from stays.`, "Delete")) act("version_delete", { name }); };
        row.append(remove);
      }
      return row;
    }));
  }
  $("#compare-result").textContent = state.compare || "";
  const system = state.system || {};
  facts($("#system-facts"), [["Nova build", state.build], ["CPU", system.cpu], ["RAM", system.ram], ["Graphics", system.gpu], ["OS", system.os], ["Memory", system.memory]]);
}

function facts(list, rows) {
  list.replaceChildren(...rows.filter(([, value]) => value).flatMap(([name, value]) => {
    const term = document.createElement("dt"); term.textContent = name;
    const detail = document.createElement("dd"); detail.textContent = String(value);
    return [term, detail];
  }));
}

function renderTasks() {
  const tasks = state.tasks || [];
  const list = $("#tasks");
  if (list.dataset.signature === JSON.stringify(tasks)) return;
  list.dataset.signature = JSON.stringify(tasks);
  list.replaceChildren(...(tasks.length ? tasks : ["No saved tasks yet."]).map((task) => {
    const item = document.createElement("li"); item.textContent = task; return item;
  }));
}

function renderReminders() {
  const items = state.reminders || [];
  const list = $("#reminders");
  const signature = JSON.stringify(items);
  if (list.dataset.signature === signature) return;
  list.dataset.signature = signature;
  list.replaceChildren(...(items.length ? items : [null]).map((item) => {
    const row = document.createElement("li");
    if (!item) { row.textContent = "None ahead. Say “remind me at 5 pm to call mom”."; return row; }
    row.className = "option-row";
    const cancel = Object.assign(document.createElement("button"), { className: "box small", textContent: "✕", title: "Cancel this reminder" });
    cancel.onclick = () => act("reminder_cancel", { id: item.id });
    row.append(Object.assign(document.createElement("span"), { textContent: item.text }), cancel);
    return row;
  }));
}

function renderSkills() {
  const skills = state.skills || { list: [] };
  const list = $("#skills");
  const signature = JSON.stringify(skills);
  if (list.dataset.signature === signature) return;
  list.dataset.signature = signature;
  list.replaceChildren(...(skills.list.length ? skills.list : [null]).map((skill) => {
    const item = document.createElement("li");
    if (!skill) { item.textContent = "No skills yet: ask Nova to make one, e.g. “make a skill that sums up my week every Friday”."; return item; }
    const words = document.createElement("span");
    const when = skill.schedule === "manual" ? "when you ask" : skill.schedule;
    const where = skill.brain === "claude-code" ? " · Claude Code" : "";
    words.append(Object.assign(document.createElement("b"), { textContent: skill.title }), document.createElement("br"),
      Object.assign(document.createElement("span"), { className: "muted small",
        textContent: `“${skill.says[0] || skill.title}” · ${when}${where}${skill.last ? ` · last ${skill.last}` : ""}` }));
    const run = Object.assign(document.createElement("button"), { className: "box small", textContent: "Run" });
    run.onclick = () => act("skill_run", { name: skill.name });
    item.className = "option-row";
    item.append(words, run);
    return item;
  }));
  const working = (skills.working || []).length ? ` Claude Code is working on: ${skills.working.join(", ")}.` : "";
  $("#skills-info").textContent = "Tasks written down once in your vault (skills/). Say a skill's phrase, press Run, or let its schedule run it; results go to outputs/."
    + (skills.claude_code ? " Long work can go to Claude Code on your plan." : " Install Claude Code to hand long work to it.") + working;
}

function renderDiscover() {
  const discover = state.discover || {};
  const signature = JSON.stringify(discover);
  if ($("#discover").dataset.signature === signature) return;
  $("#discover").dataset.signature = signature;
  const items = discover.items || [];
  $("#discover").replaceChildren(...items.map((item) => {
    const row = Object.assign(document.createElement("li"), { className: "option-row" });
    const words = document.createElement("span");
    const link = Object.assign(document.createElement("a"), { href: "#", textContent: item.repo });
    link.onclick = (event) => { event.preventDefault(); act("open_url", { url: item.url }); };
    words.append(link, document.createElement("br"),
      Object.assign(document.createElement("span"), { textContent: item.about || "" }), document.createElement("br"),
      Object.assign(document.createElement("span"), { className: "muted small", textContent: `Why: ${item.why}${item.license ? ` · ${item.license}` : ""}` }));
    const add = Object.assign(document.createElement("button"), { className: "box small on", textContent: "Add to Nova",
      title: "Claude Code studies it (read-only, pinned to its current commit) and proposes how Nova could use it" });
    add.onclick = () => act("discover_add", { repo: item.repo });
    const skip = Object.assign(document.createElement("button"), { className: "box small", textContent: "Not for me" });
    skip.onclick = () => act("discover_skip", { repo: item.repo });
    row.append(words, add, skip);
    return row;
  }));
  $("#discover-offers").replaceChildren(...(discover.offers || []).map((offer) => {
    const row = Object.assign(document.createElement("li"), { className: "option-row" });
    row.append(Object.assign(document.createElement("span"), { textContent: `Proposed skill from ${offer.repo}` }));
    const read = Object.assign(document.createElement("button"), { className: "box small on", textContent: "Read and add" });
    read.onclick = async () => {
      const choice = await modal(`A skill from ${offer.repo}`, `${offer.note}\n\nThe full study is in ${offer.report}. A skill is text Nova follows with her own tools; nothing from the project runs.`,
        [{ label: "Add skill", value: "add", primary: true }, { label: "Don't add", value: "drop" }, { label: "Later", value: null, cancel: true }]);
      if (choice === "add") act("discover_install_skill", { repo: offer.repo });
      if (choice === "drop") act("discover_drop_skill", { repo: offer.repo });
    };
    row.append(read);
    return row;
  }));
  const studying = (discover.studying || []).length ? ` Studying now: ${discover.studying.join(", ")}.` : "";
  $("#discover-info").textContent = (discover.status || "GitHub projects picked from your interests" + (discover.username ? " and your GitHub" : "")
    + ". Add to Nova has Claude Code study one (read-only, pinned to a commit, license noted) and propose a skill or a project; nothing is installed into Nova.")
    + (discover.added || discover.skipped ? ` You've added ${discover.added} and skipped ${discover.skipped}; the picks learn from that.` : "")
    + (discover.claude_code ? "" : " Studying needs Claude Code.") + studying;
  $("#discover-refresh").disabled = Boolean(discover.busy);
  if (document.activeElement !== $("#discover-user")) $("#discover-user").value = discover.username || "";
  $("#discover-token-forget").hidden = !discover.token;
  $("#reverse-toggle").textContent = discover.reverse_on ? "Turn off" : "Turn on";
  $("#reverse-info").textContent = discover.reverse_on
    ? "On: say “reverse engineer <app, site, file or project> and tell me how <part> works”. It runs REA (rea-agents 6.9.0) through Claude Code in the background; the report goes to outputs/ and your Library under Reverse engineering." + (discover.reverse_problem ? ` Not ready: ${discover.reverse_problem}.` : "")
    : "Off. REA works out how apps, sites and binaries are built, through Claude Code. Needs Claude Code and Node.js 22.23 or newer. Only for software you're allowed to analyse.";
}

function renderUpdate() {
  const update = state.update || {};
  $("#update-card").hidden = Boolean(update.usb);
  if (document.activeElement !== $("#update-auto")) $("#update-auto").checked = update.auto !== false;
  $("#update-install").hidden = !update.ready;
  $("#update-page").hidden = !update.page;
  $("#update-check").disabled = $("#update-rollback").disabled = Boolean(update.busy) || update.version === "dev";
  $("#update-rollback").hidden = !update.can_install;
  $("#update-info").textContent = update.version === "dev" ? "Running from source: updates come with git pull."
    : [`This is Nova ${update.version}.`, update.status || (update.available ? `Nova ${update.available} is out.` : ""),
       update.can_install ? "" : "Installed from a zip: install Nova-Setup.exe once and updates install themselves."].filter(Boolean).join(" ");
}

function renderConnections() {
  const switches = state.switches || {};
  $("#gmail-toggle").hidden = switches.gmail === null || switches.gmail === undefined;
  $("#gmail-toggle").textContent = switches.gmail ? "Disconnect Google" : "Connect Google (Gmail, Calendar, Drive)";
  $("#calendar-connect").hidden = !switches.gmail || Boolean(switches.calendar);
  $("#drive-connect").hidden = !switches.gmail || Boolean(switches.drive);
  $("#connections-info").textContent = [switches.phone ? "Nova Lite is on." : "Nova Lite is off.",
    switches.gmail ? "Gmail: drafts only, never sends." : "",
    switches.calendar ? "Google Calendar: “what's on today?”, “add dentist Friday at 3”." : switches.gmail ? "Click Add Google Calendar and allow Calendar too." : "",
    switches.drive ? "Google Drive (read-only): “find my budget in Drive”, “read file 1”." : switches.gmail ? "Click Add Google Drive and allow Drive too." : ""].join(" ");
  $("#need-google-state").textContent = switches.gmail ? (switches.calendar && switches.drive ? "connected" : "reconnect for more") : "";
  $("#need-google-connect").hidden = Boolean(switches.gmail) || switches.gmail === null || switches.gmail === undefined;
}

function renderTuning() {
  const tuning = state.tuning;
  if (!tuning) return;
  const result = tuning.result;
  const where = (share) => (share >= 0.97 ? "all on the graphics card" : share > 0 ? `${Math.round(share * 100)}% on the graphics card` : "on the processor");
  $("#tune-info").textContent = tuning.running ? `Tuning… ${tuning.step || ""}`
    : result ? `${result.model}, ${where(result.on_gpu)}, ${Math.round(result.tokens_per_second)} tokens a second, `
      + `first words in ${result.first_token_seconds.toFixed(1)} s, ${Math.round(result.num_ctx / 1024)}K context. `
      + `Tuned for ${result.version} on ${result.tuned_at.replace("T", " ")}.${result.notes?.length ? ` ${result.notes.join("; ")}.` : ""}`
    : "Not tuned yet: Nova measures the models after it starts, or press Tune now.";
  $("#tune-now").disabled = Boolean(tuning.running);
  $("#tune-auto").textContent = `Tune after every update: ${tuning.auto ? "on" : "off"}`;
  $("#tune-auto").classList.toggle("on", Boolean(tuning.auto));
}

function renderKnowledge() {
  const knowledge = state.knowledge;
  if (!knowledge) return;
  const gb = (bytes) => (bytes ? `${(bytes / 1e9).toFixed(bytes < 1e9 ? 2 : 1)} GB` : "");
  const busy = knowledge.downloading;
  $("#knowledge-packs").replaceChildren(...knowledge.packs.map((pack) => {
    const row = document.createElement("li");
    const label = document.createElement("span");
    const downloading = busy && busy.key === pack.key;
    label.textContent = `${pack.title}${pack.file ? ` · on this PC (${gb(pack.size)})` : pack.bytes ? ` · ${gb(pack.bytes)}` : ""}`
      + (downloading ? ` · downloading ${busy.total ? Math.round((busy.done / busy.total) * 100) : 0}%` : "");
    const button = document.createElement("button");
    button.className = "box small";
    button.textContent = pack.file ? "Remove" : "Download";
    button.disabled = Boolean(busy) && !pack.file;
    button.onclick = () => (pack.file ? act("knowledge_remove", { file: pack.file }) : act("knowledge_download", { key: pack.key }));
    row.append(label, button);
    return row;
  }));
  const notes = knowledge.notes || {};
  $("#notes-info").textContent = notes.status || (notes.count
    ? `${notes.count} notes from ${notes.vault} are searchable by meaning. Ask “what did I write about …?”.`
    : `Index your vault (${notes.vault}) once: Nova downloads a small meaning model (about 270 MB) and reads your notes on this PC. Nothing leaves it.`);
  $("#notes-index").disabled = Boolean(notes.busy);
  $("#notes-index").textContent = notes.count ? "Update the index" : "Index my notes";
  $("#cities-info").textContent = knowledge.cities.length
    ? `Kept for offline routes: ${knowledge.cities.join(", ")}. Places you've routed to before work offline too.`
    : "Routes need the internet the first time in each area. Keep your city's roads and they work offline (one download, a few minutes).";
  if (document.activeElement !== $("#keep-city") && !$("#keep-city").value) $("#keep-city").value = knowledge.city || "";
}

function renderGoogleMcp() {
  const mcp = state.google_mcp || {};
  const ready = Boolean(mcp.on && mcp.running);
  $("#google-mcp-toggle").textContent = mcp.on ? "Turn off" : "Turn on";
  $("#google-mcp-toggle").hidden = Boolean(mcp.usb);
  $("#google-mcp-new-key").hidden = !ready;
  $("#google-mcp-setup").hidden = !ready;
  if (ready) {
    $("#google-mcp-code").value = mcp.claude_code || "";
    $("#google-mcp-desktop").value = mcp.claude_desktop || "";
  }
  $("#need-claude-apps-state").textContent = ready ? "on" : "";
  if (document.activeElement !== $("#node-path")) $("#node-path").value = (state.settings || {}).node_path || "";
  $("#google-mcp-info").textContent = mcp.usb ? "Not on the USB Edition."
    : mcp.error ? `Not serving: ${mcp.error}.`
    : !mcp.on ? "Off."
    : !mcp.google ? "On, but Google isn't connected yet: connect it first."
    : `Serving ${mcp.drive ? "Gmail and Google Drive" : "Gmail (add Google Drive in Connections for Drive too)"} at ${mcp.url || "this PC"} while Nova runs. The key below is private: don't share it.`;
}

// ---------- chat and captions ----------

function addChat(item, animate) {
  if (chatIds.has(item.id)) return;
  chatIds.add(item.id);
  const bubble = document.createElement("div");
  bubble.className = `message ${item.role}`;
  const who = document.createElement("span");
  who.className = "who";
  who.textContent = `${item.label}${item.time ? " · " + item.time : ""}`;
  bubble.append(who, document.createTextNode(item.text));
  if (item.role === "assistant") {
    const slide = { kind: "text", title: "Nova", body: item.text };
    const button = Object.assign(document.createElement("button"), { className: "to-tv", textContent: "→ TV", title: "Show it on the TV" });
    button.onclick = () => act("tv_show", slide);
    who.append(button);
    bubble.draggable = true;
    bubble.addEventListener("dragstart", () => startSlide(slide));
    bubble.addEventListener("dragend", endSlide);
  }
  const chat = $("#chat");
  chat.append(bubble);
  while (chat.children.length > 120) chat.firstChild.remove();
  $("#pane-history").scrollTop = $("#pane-history").scrollHeight;
  if (item.role === "user") { caption("#heard", item.text, animate); if (animate) caption("#reply", "", false); }
  if (item.role === "assistant") caption("#reply", item.text, animate);
}

function caption(selector, text, animate) {
  const element = $(selector);
  element.textContent = text;
  if (animate) { element.classList.remove("fade-in"); void element.offsetWidth; element.classList.add("fade-in"); }
}

function showLevel(level) {
  const rms = Math.max(level / 12, 1e-5);
  const db = Math.max(-90, 20 * Math.log10(rms));
  showLevel.peak = Math.max(db, (showLevel.peak ?? -90) - 0.6);
  $("#lvl").textContent = `LVL ${db.toFixed(1)} dB`;
  $("#pk").textContent = `PK ${showLevel.peak.toFixed(1)} dB`;
}

// ---------- side panel ----------

// ---------- idea maps ----------

// ---------- brainstorm map ----------
let mapOpen = false, mapSignature = "", mapTitle = "", saveTimer = 0;

function openMap(on = true) {
  mapOpen = on;
  document.body.classList.toggle("mapping", on);
  mindmap.show(on);
  $("[data-act=map]").classList.toggle("on", on);
  if (on && world.isOpen()) world.close();
  if (!on && openPane === "notes") setPane("notes");
}

function renderNotes() {
  const notes = state.notes;
  if (!notes) return;
  mindmap.setExpanding(notes.expanding);
  $("#map-ask").disabled = notes.expanding !== null && notes.expanding !== undefined;
  $("#map-ask").textContent = $("#map-ask").disabled ? "✦ Thinking…" : "✦ Ask Nova";
  const data = { title: notes.title, outline: notes.outline, positions: notes.positions || {}, details: notes.details || {},
    styles: notes.styles || {}, links: notes.links || [] };
  const signature = JSON.stringify(data);
  // Only when the PC's copy changed (render() runs for every update). Nova changed the map (voice, Ask
  // Nova, a map you opened): show it. Your own autosave coming back is ignored: the screen may be newer.
  // A freshly opened window has nothing yet, so it takes the PC's copy whoever saved it last.
  if (signature !== mapSignature && (notes.source !== "you" || !mapSignature)
      && !["map-title", "map-outline"].includes(document.activeElement?.id)) {
    mapSignature = signature;
    clearTimeout(saveTimer); // Nova's version is newer (your edits were saved before it changed the map)
    saveTimer = 0;
    mapTitle = notes.title;
    mindmap.setData(data);
    showWhere();
    $("#map-title").value = notes.title;
    $("#map-outline").value = notes.outline;
  }
  const saved = $("#map-saved");
  if (saved.dataset.signature !== JSON.stringify(notes.maps)) {
    saved.dataset.signature = JSON.stringify(notes.maps);
    saved.replaceChildren(new Option(notes.maps.length ? "Open a saved map…" : "No saved maps yet", ""),
      ...notes.maps.map((item, index) => new Option(`${item.title} · ${item.saved.slice(0, 10)}`, String(index))));
  }
}

// Every change on the map or in the editor is saved a moment later.
function mapChanged(data) {
  if (document.activeElement !== $("#map-title")) $("#map-title").value = data.title;
  if (document.activeElement !== $("#map-outline")) $("#map-outline").value = data.outline;
  $("#map-saved-state").textContent = "SAVING…";
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveMapNow, 600);
}

async function saveMapNow() {
  clearTimeout(saveTimer);
  saveTimer = 0;
  const data = mindmap.data();
  const result = await act("notes_save", { ...data, previous: mapTitle });
  if (result.ok !== false) mapTitle = data.title;
  $("#map-saved-state").textContent = result.ok === false ? "NOT SAVED" : data.outline.trim() ? "SAVED" : "";
}

// Before Nova changes the map, your latest edits reach the PC first, so nothing of yours is overwritten.
async function flushMapSave() {
  if (saveTimer) await saveMapNow();
}

async function askAlfredAbout(path) {
  await flushMapSave();
  act("map_expand", { path });
}

function showWhere() {
  $("#map-quick-where").textContent = `ADD TO: ${mindmap.selectedLabel()}`;
}

// Colour swatches and icons on the note card; "" is "automatic" / "no icon".
function styleButtons(box, values, make, pick) {
  box.replaceChildren(...values.map((value) => {
    const button = make(value);
    button.type = "button";
    button.dataset.value = value;
    button.onclick = () => showStyle(mindmap.setStyle(pick(value)));
    return button;
  }));
}
styleButtons($("#map-colors"), ["", ...Object.keys(PALETTE)], (color) => {
  const button = Object.assign(document.createElement("button"), { title: color || "Automatic", textContent: color ? "" : "A" });
  if (color) button.style.setProperty("--swatch", `rgb(${PALETTE[color].join(", ")})`);
  else button.className = "auto";
  return button;
}, (color) => ({ color }));
styleButtons($("#map-icons"), ["", ...ICONS], (icon) => Object.assign(document.createElement("button"), { title: icon ? "Icon" : "No icon",
  textContent: icon || "∅" }), (icon) => ({ icon }));

function showStyle(info) {
  if (!info) return;
  $$("#map-colors button").forEach((button) => button.classList.toggle("on", button.dataset.value === info.color));
  $$("#map-icons button").forEach((button) => button.classList.toggle("on", button.dataset.value === info.icon));
  const preset = ["", ...ICONS].includes(info.icon);
  if (document.activeElement?.id !== "map-own-icon") $("#map-own-icon").value = preset ? "" : info.icon;
  $("#map-link").textContent = info.links ? `🔗 Link to another idea (${info.links} linked)` : "🔗 Link to another idea";
}

// Selecting an idea shows its notes, tells the typing bar where new ideas go, and highlights its line in the editor.
function selectIdea(line, info) {
  showWhere();
  $("#map-note").hidden = !info;
  if (info) {
    $("#map-note-title").textContent = info.label;
    $("#map-note-text").value = info.note;
    showStyle(info);
  }
  if (openPane !== "notes" || line === undefined) return;
  const outline = $("#map-outline");
  const lines = outline.value.split("\n");
  const start = lines.slice(0, line).reduce((total, text) => total + text.length + 1, 0);
  outline.setSelectionRange(start, start + (lines[line] || "").length);
}

function setPane(name) {
  openPane = openPane === name ? null : name;
  document.body.classList.toggle("drawer-open", Boolean(openPane));
  $("#drawer").setAttribute("aria-hidden", String(!openPane));
  $$(".pane").forEach((pane) => pane.classList.toggle("on", pane.id === `pane-${openPane}`));
  $$("[data-pane]").forEach((button) => button.classList.toggle("on", button.dataset.pane === openPane));
  if (openPane === "notes" && !mapOpen) openMap(true);
  if (openPane === "settings") { loadAudioDevices(); act("downloads"); pollPc(); }
  if (openPane === "history") $("#pane-history").scrollTop = $("#pane-history").scrollHeight;
}

// ---------- daily brief ----------

function renderBrief() {
  const settings = state.settings || {};
  const interests = settings.interests || [];
  const on = Boolean((state.switches || {}).brief);
  const outlets = settings.news_outlets || [];
  const signature = JSON.stringify([interests, outlets, settings.brief_region, on, state.brief, state.brief_loading,
    state.weather_now, state.local_news]);
  if (renderBrief.signature === signature) return;
  renderBrief.signature = signature;
  $("#interests").replaceChildren(...interests.map((interest) => {
    const chip = document.createElement("span");
    chip.className = "chip-item";
    chip.textContent = interest;
    const remove = document.createElement("button");
    remove.textContent = "✕";
    remove.setAttribute("aria-label", `Remove ${interest}`);
    remove.onclick = () => act("settings", { interests: interests.filter((other) => other !== interest) });
    chip.append(remove);
    return chip;
  }));
  $("#interest-suggestions").replaceChildren(...SUGGESTED_INTERESTS.filter((item) => !interests.includes(item)).slice(0, 7).map((item) => {
    const button = document.createElement("button");
    button.textContent = `+ ${item}`;
    button.onclick = () => act("settings", { interests: [...interests, item] });
    return button;
  }));
  $("#outlets").replaceChildren(...(outlets.length ? outlets : [""]).map((site) => {
    const chip = document.createElement("span");
    chip.className = "chip-item";
    chip.textContent = site ? OUTLETS[site] || site : "Google News top stories";
    if (site) {
      const remove = Object.assign(document.createElement("button"), { textContent: "✕" });
      remove.setAttribute("aria-label", `Remove ${OUTLETS[site] || site}`);
      remove.onclick = () => act("settings", { news_outlets: outlets.filter((other) => other !== site) });
      chip.append(remove);
    }
    return chip;
  }));
  $("#outlet-suggestions").replaceChildren(...Object.entries(OUTLETS).filter(([site]) => !outlets.includes(site)).slice(0, 6).map(([site, name]) => {
    const button = document.createElement("button");
    button.textContent = `+ ${name}`;
    button.onclick = () => act("settings", { news_outlets: [...outlets, site] });
    return button;
  }));
  $("#brief-region").value = settings.brief_region || "US";
  $("#brief-setup").classList.toggle("compact", on);
  $("#brief-toggle").textContent = on ? "Turn off" : "Turn on";
  $("#brief-toggle").classList.toggle("on", !on);
  $("#brief-refresh").hidden = !on;
  $("#brief-refresh").disabled = Boolean(state.brief_loading);
  $("#brief-refresh").textContent = state.brief_loading ? "Loading…" : "Refresh now";

  const content = $("#brief-content");
  const brief = state.brief;
  if (!on || !brief) { content.replaceChildren(); return; }
  const parts = [];
  const date = document.createElement("div");
  date.className = "brief-date";
  date.append(Object.assign(document.createElement("span"), { textContent: `TODAY · ${brief.date}` }));
  parts.push(date);
  const section = (title, items, describe) => {
    if (!items || !items.length) return;
    parts.push(Object.assign(document.createElement("h4"), { className: "section-title", textContent: title }));
    items.forEach((item) => parts.push(briefItem(item, describe(item))));
  };
  const weatherNow = state.weather_now;
  if (weatherNow) {
    parts.push(Object.assign(document.createElement("h4"), { className: "section-title", textContent: `Weather · ${weatherNow.label}` }));
    weatherNow.lines.forEach((line) => parts.push(Object.assign(document.createElement("p"), { className: "weather-line", textContent: line })));
  }
  section(weatherNow ? `Local news · ${weatherNow.place}` : "Local news", state.local_news, (item) => [item.source, item.time].filter(Boolean).join(" · "));
  section("Headlines", brief.headlines, (item) => [item.source, item.time].filter(Boolean).join(" · "));
  (brief.topics || []).forEach((topic) => {
    section(topic.interest, topic.news, (item) => [item.source, item.time].filter(Boolean).join(" · "));
    section(`${topic.interest} · on GitHub`, topic.repos, repoMeta);
  });
  section("New on GitHub", brief.repos, repoMeta);
  section("Hacker News", brief.hacker_news, (item) => `${item.points} points${item.match ? " · your topic" : ""}`);
  section("On this day", brief.on_this_day, () => "Wikipedia");
  if (brief.errors && brief.errors.length) {
    parts.push(Object.assign(document.createElement("p"), { className: "muted small", textContent: `Couldn't load: ${brief.errors.join("; ")}` }));
  }
  content.replaceChildren(...parts);
}

const repoMeta = (item) => [`★ ${item.stars}`, item.language].filter(Boolean).join(" · ");

function briefItem(item, meta) {
  const button = document.createElement("button");
  button.className = "brief-item";
  button.append(document.createTextNode(item.title));
  if (item.about) button.append(Object.assign(document.createElement("span"), { className: "about", textContent: item.about }));
  if (meta) button.append(Object.assign(document.createElement("span"), { className: "meta", textContent: meta }));
  button.onclick = () => act("open_url", { url: item.url });
  return button;
}

// ---------- dialogs ----------

function modal(title, body, buttons, { wide = false } = {}) {
  return new Promise((resolve) => {
    $("#modal-title").textContent = title;
    const bodyElement = $("#modal-body");
    bodyElement.replaceChildren(...(Array.isArray(body) ? body : [document.createTextNode(body)]));
    $(".modal-card").classList.toggle("wide", wide);
    const close = (value) => { $("#modal").hidden = true; modalOnClose = null; resolve(value); };
    modalOnClose = () => close(buttons.find((button) => button.cancel)?.value ?? null);
    $("#modal-buttons").replaceChildren(...buttons.map((button) => {
      const element = document.createElement("button");
      element.className = `box ${button.primary ? "on" : ""} ${button.danger ? "danger" : ""}`;
      element.textContent = button.label;
      if (button.key) element.append(Object.assign(document.createElement("span"), { className: "key-hint", textContent: `[${button.key}]` }));
      element.dataset.key = button.key || "";
      element.onclick = async () => {
        if (button.run) await button.run();
        if (!button.keepOpen) close(button.value);
      };
      return element;
    }));
    $("#modal").hidden = false;
    $("#modal-buttons .on")?.focus();
  });
}

const yesNo = (title, text, yes = "Turn on") =>
  modal(title, text, [{ label: "Cancel", value: false, cancel: true }, { label: yes, value: true, primary: true }]);

const CONSENT = {
  free_cloud: () => ["Use Ollama Cloud as Nova's brain", "While this is chosen and the PC is online, Nova sends your questions to a large open model on Ollama's servers, through Ollama on this PC and your free Ollama account.\n\n• Sent: your question, the recent conversation and what it needs: with the default setting that can be your name, what Nova remembers, your city (for the weather and news) and your notes or library when you ask about them. Web searches go to DuckDuckGo (only the search words).\n• Passwords, codes, bank details and mail: Nova asks you out loud first, every time; “no” keeps them on this PC.\n• Start with “privately” to keep any question here, or choose “Anything personal stays on this PC” in Settings. Offline, everything stays here.\n\nOllama limits free use per session and per week; then the AI on this PC answers. Change it any time."],
  claude: () => ["Use Claude as Nova's brain", "While Claude is chosen and the PC is online, Nova sends your questions to Claude (Anthropic's AI, on your Claude plan through Claude Code, or with your own API key) and speaks Claude's answer.\n\n• Sent: your question, the recent conversation and what it needs: with the default setting that can be your name, what Nova remembers, your city (for the weather and news) and your notes or library when you ask about them. Web searches go to DuckDuckGo (only the search words); Claude reads the results.\n• Passwords, codes, bank details and mail: Nova asks you out loud first, every time; “no” keeps them on this PC.\n• Start with “privately” to keep any question here, or choose “Anything personal stays on this PC” in Settings. Offline, everything stays here.\n\nOn your Claude plan it counts toward the plan's usage limit (no extra bill); with an API key Anthropic bills per question (about half a cent with Sonnet at medium effort). Change it any time."],
  connectors: () => ["Claude with your claude.ai Gmail and Drive", "When Claude answers on your Claude plan, it may also use the Gmail and Google Drive connectors you connected on claude.ai, when you ask about your mail or files.\n\n• Your mail and files are read by Claude (Anthropic) through your own claude.ai account, under its privacy terms.\n• Nova lets it read, search and save drafts only: sending mail and sharing, changing or deleting files are blocked.\n• Connect them first on claude.ai → Settings → Connectors, with the account Claude Code is signed in with.\n\nTurn it off any time."],
  google_mcp: () => ["Nova's Gmail and Drive for your Claude apps", "Nova will serve its Gmail and Google Drive tools on this PC (127.0.0.1, port 47821) for Claude Code and Claude Desktop.\n\n• Only programs on this PC that have the private key can use it; you paste the key into your Claude apps. Don't share it.\n• Those apps can read your unread mail, save drafts (never send) and search and read your Drive files. What they read goes to Claude (Anthropic) under your Claude account.\n• Your Claude app asks you before each tool, so Nova doesn't ask again.\n• New key shuts out every app set up with the old one.\n\nTurn it off any time."],
  knowledge: (detail) => [`Download ${detail.title}?`, `${detail.gb ? `About ${detail.gb} GB` : "Its size is shown once you click Show download sizes"}, from Kiwix's library (the same Wikipedia files offline libraries and Project NOMAD use), into Nova's data folder.\n\nAfter that Nova can look things up in it with the internet off. It downloads in the background; you can keep using Nova, and if it's cut off it carries on from where it stopped.`, "Download"],
  reverse: () => ["Reverse engineering with REA", "Nova will be able to hand “reverse engineer …” jobs to Claude Code (on your plan) with REA, an open-source reverse engineering toolkit (github.com/morluto/rea, pinned to rea-agents 6.9.0, run with npx).\n\n• Only use it on software, sites and files you're allowed to analyse; respect licenses and terms of service. Nova asks Claude not to patch, crack or bypass anything.\n• REA reads files and can run or drive the target with your Windows permissions.\n• What it finds goes to Claude (your plan), and the report to outputs/ and your Library.\n• It needs Claude Code and Node.js 22.23 or newer.\n\nTurn it off any time."],
  shannon: () => ["Shannon attacks your app for real", "Shannon (github.com/KeygraphHQ/shannon, pinned to 3.5.0) is an AI pentester: it reads your project's code, then really tries to break into the running app (injection, XSS, logins, access control, SSRF) and reports only what it could prove, with the fix.\n\n• Only your own apps, running on this PC or your home network. Nova refuses other addresses. Use a test copy: it can change or delete data in the app it attacks.\n• It runs in Docker inside WSL2 and talks to Claude with your Claude API key: your code and the app's answers go to Anthropic, and a full run costs API credit (it can be tens of dollars) and takes an hour or two.\n• The report goes to the project's Security checks folder and your Library.\n\nYou are asked this once.", "I understand, run it"],
  telegram_relay: () => ["Nova on Telegram with the PC off", "Nova will put a small relay on your own Cloudflare account (free). While your PC is off, Telegram sends your messages there instead.\n\n• Kept on your Cloudflare account: your bot token, your Telegram id, your name and what Nova remembers (so she still knows you), the reminders of the next three days (so they still come), the key of the online brain you chose, and the messages sent while the PC was off, until the PC is back and reads them.\n• While the PC is off, the brain you chose (Claude Haiku with your API key, or Ollama Cloud) answers; it can talk and plan, not use the PC. Voice notes and files wait for the PC.\n• When the PC starts, it takes Telegram back and the conversation continues there.\n\nRemove relay takes all of it off your Cloudflare account."],
  telegram: () => ["Nova on Telegram", "Nova will answer your own private Telegram bot from this PC, wherever you are.\n\n• Only you: the first account that sends the pairing code becomes the owner; everyone else is ignored without a reply.\n• Your messages and Nova's answers travel through Telegram's servers (bot chats are not end-to-end encrypted). Don't send passwords there.\n• Voice notes are turned into text on this PC and not kept.\n• Nova can send you your own files when you ask (from Desktop, Documents, Downloads, Pictures, Videos, Music).\n• With Screen assist on, she can also work the PC for you from the chat. When she needs a yes or no, she asks in the chat.\n\nNothing on this PC opens to the internet: Nova asks Telegram for new messages. Turn it off any time."],
  mic: () => ["Turn the microphone on", "While the mic is on, Nova listens for its name. Say “Hey Nova, …” with your request, or “Hey Nova”, wait for the beep, then speak. After that Nova keeps listening for a minute: no need to say its name again. “Thanks” ends it early.\n\nAudio is analyzed on this PC in memory and never saved. It can sometimes miss its name or wake by mistake. The mic stays on until you switch it off, also after restarting Nova."],
  gestures: () => ["Turn webcam gestures on", "Nova watches the webcam for hand gestures while it runs:\n\n👍 hold thumbs up: volume up     👎 hold thumbs down: volume down\n✋ swipe an open hand right / left: next / previous song or video\n✊ hold a fist: play / pause     ✌ hold a peace sign: creative mode\nand any gestures of your own (Settings → Gestures).\n\nFrames are analyzed on this PC in memory and never saved or sent. It stays on until you switch it off."],
  phone: () => ["Nova Lite for iPhone", "Nova will accept connections from your phone on this Wi-Fi network. Only a phone that scanned your private QR code can use it.\n\nWindows may ask whether Nova may use the network: allow it on private networks. Use this on your home Wi-Fi, not on public networks."],
  assist: () => ["Screen assist and autopilot", "While it is on (it stays on until you switch it off):\n\n• Each time you ask something, Nova reads the app you were last using (its text and controls from Windows UI Automation, never password fields) and sends it to the model on this PC only. Ask her to review or do your homework or an article and she reads all of it, scrolling by herself.\n• Nova can point, pin notes, scroll, open programs and websites, and click, type and press keys with your real mouse and keyboard, step after step, without asking you each time.\n• She does not ask before any step, money and sending included: you told her to just do what you ask. SCREEN → Ask before risky steps brings that question back.\n• Hold Ctrl+Alt anywhere to talk; release to send. Esc stops Nova at once. SCREEN → Autopilot turns the no-asking off.\n• A page or file can hold text written to trick an AI. Watch the screen while Nova works on something you don't trust.\n\nYou are asked this once."],
  second_brain: () => ["Turn on your second brain", "While it is on, Nova keeps notes of what you do on this PC in your Obsidian vault:\n\n• Every 15 seconds she reads the text of the window you're using (password fields and text boxes are skipped). If you allow it, she also listens to the videos and reels you watch and writes down what they say (Whisper, on this PC).\n• Every 20 minutes the AI model on this PC sums it up into raw/activity/date.md, then folds it into wiki/ pages, one per topic, linked to each other (Andrej Karpathy's “LLM wiki”). The raw text and sound are kept only in memory and thrown away after each summary.\n• Never read: private or incognito windows, password managers, banking, calls and chats (other people's words), Nova itself, and anything you add to the “Never read” list.\n\nNothing leaves this PC, unless you sync the vault with your own other PC (Your other PC, below). Turn it off here or say “Hey Nova, pause my second brain”."],
  location: () => ["Use your location", "Nova uses your location for the weather and local news:\n\n• Weather comes from Open-Meteo (free, no account), which gets only your city's coordinates.\n• Local news headlines come from Google News, which gets your city's name.\n• With “Use this PC's location”, Windows' location service finds where this PC is (if it's off: your internet connection's approximate city, from ipinfo.io), and OpenStreetMap turns it into a city name.\n\nYour location is kept only in Nova's settings on this PC. “Forget my location” removes it."],
  news: () => ["Turn on the news desk", "Every morning at 06:00 (or as soon as Nova runs that day) Nova collects the news:\n\n• GNews (with your free key, if you add one), GDELT and the news sites' own feeds get only ordinary requests for today's headlines: nothing about you.\n• The AI on this PC reads each article and writes a short summary, key facts, names, place and an importance score. It keeps allegations as allegations and leaves out what the article doesn't say.\n• Everything is kept in news.sqlite3 in Nova's data folder, with each article's link, publisher and dates, so Nova answers “what happened today?” with sources.\n\nIt uses the network and the AI on this PC for a few minutes each morning. Turn it off here any time."],
  brief: () => ["Daily brief", "Once a day Nova fetches:\n• top headlines and news on your interests (Google News)\n• new GitHub repos on your interests (GitHub)\n• the Hacker News front page\n• “On this day” (Wikipedia)\n\nOnly your interest words are sent, as search terms. Nothing else about you leaves this PC. The brief is kept for today only."],
  read_screen: () => ["Read the screen", "Nova will briefly minimize, read the chosen display with Windows accessibility text or local OCR, mask detected password fields, and show you the text to review. Nothing is sent to the model or saved unless you choose to add it to the chat.", "Read it"],
  whisper: (detail) => ["Install Whisper", `Download Whisper speech recognition (about ${detail.mb} MB) from GitHub and Hugging Face into Nova's data folder?\n\nIt understands accents and broken English much better. It runs on this PC; your voice is never uploaded.`, "Download"],
  voice: (detail) => ["Download voice", `Download the natural voice “${detail.name}” (about ${detail.mb} MB) into Nova's data folder? It runs on this PC.`, "Download"],
  vision: (detail) => ["Download a vision model", `Download ${detail.name} (about ${detail.size_gb} GB) with Ollama?\n\nIt lets Nova name anything you show the camera in creative mode, not just 80 everyday kinds. The photo of the object goes only to Ollama on this PC; nothing is uploaded.`, "Download"],
  model: (detail) => ["Download a better model", `Download ${detail.name} (about ${detail.size_gb} GB) with Ollama?\n\n${detail.reason ? `This PC: ${detail.reason}.\n` : ""}It uses the internet and disk space. Nova keeps using the current model until the download finishes.`, "Download"],
};

async function consent(key, detail) {
  const [title, text, yes] = (CONSENT[key] || (() => ["Continue?", String(key)]))(detail);
  return yesNo(title, text, yes || "Turn on");
}

function renderApproval() {
  const approval = state.approval;
  if (!approval && shownApproval) {
    shownApproval = null; // answered elsewhere or cancelled with Esc
    $("#modal").hidden = true;
    modalOnClose = null;
    return;
  }
  if (!approval || shownApproval === approval.id) return;
  shownApproval = approval.id;
  modal(approval.title, approval.body, [
    { label: "No", value: false, key: "N", cancel: true },
    { label: "Yes", value: true, key: "Y", primary: true },
  ]).then((yes) => act("approve", { id: approval.id, yes: Boolean(yes) }));
}

function showReview(title, warning, text) {
  const note = Object.assign(document.createElement("p"), { className: "note", textContent: warning });
  const pre = Object.assign(document.createElement("pre"), { textContent: text || "(no text found)" });
  modal(title, [note, pre], [
    { label: "Discard", value: false, cancel: true },
    { label: "Add to chat", value: true, primary: true, run: () => {
      const input = $("#text");
      input.value = `I reviewed and chose to share this selected text. Help me understand it:\n\n${text.slice(0, 6000)}`;
      input.focus();
    } },
  ], { wide: true });
}

async function screenMenu() {
  const switches = state.switches || {};
  const select = document.createElement("select");
  select.className = "field";
  (state.displays || []).forEach((label, index) => select.append(new Option(label, String(index + 1))));
  const row = (title, text, control) => {
    const element = document.createElement("div");
    element.className = "option-row";
    const words = document.createElement("div");
    words.append(Object.assign(document.createElement("b"), { textContent: title }), document.createElement("br"),
      Object.assign(document.createElement("span"), { className: "muted small", textContent: text }));
    element.append(words, control);
    return element;
  };
  const button = (label, onClick, on = false) => {
    const element = Object.assign(document.createElement("button"), { className: `box ${on ? "on" : ""}`, textContent: label });
    element.onclick = () => { $("#modal").hidden = true; modalOnClose = null; onClick(); };
    return element;
  };
  const displayPicker = document.createElement("div");
  displayPicker.className = "row";
  displayPicker.style.marginTop = "0";
  displayPicker.append(select, button("Read", () => readScreen(select.value)));
  const rows = [
    row("Read a file", "A text file you pick. Stays on this PC.", button("Choose file", () => $("#file-input").click())),
  ];
  if (state.windows) {
    const autopilot = !!(state.settings || {}).autopilot;
    const vision = (state.settings || {}).screen_vision !== false;
    rows.unshift(row("See the screen with Claude", vision ? "With Claude set up (SETTINGS → Claude), screen jobs go to Claude: it sees a screenshot of each step, with every control numbered. The screenshots go to Anthropic. Without Claude, the AI on this PC does them from the list of controls." : "Off: the AI on this PC does screen jobs from the list of controls; no screenshot leaves this PC.",
      button(vision ? "Turn off" : "Turn on", () => act("autopilot", { screen_vision: !vision }), !vision)));
    const byVoice = (state.settings || {}).ask_by_voice !== false;
    rows.unshift(row("Questions by voice", byVoice ? "When Nova has to ask yes or no she says it out loud: hold the talk key and answer. No pop-up." : "Questions pop up in the window with Yes and No buttons.",
      button(byVoice ? "Turn off" : "Turn on", () => act("autopilot", { ask_by_voice: !byVoice }), !byVoice)));
    const askRisky = !!(state.settings || {}).ask_risky;
    rows.unshift(row("Ask before risky steps", askRisky ? "Nova asks out loud before money, sending, deleting, passwords and bank pages." : "Off: Nova does those too when you ask for them.",
      button(askRisky ? "Turn off" : "Turn on", () => act("autopilot", { ask_risky: !askRisky }), askRisky)));
    rows.unshift(row("Autopilot", autopilot ? "Nova does what you ask herself, no questions. Esc stops her." : "Nova asks you before every click, key press and typed text.",
      button(autopilot ? "Turn off" : "Turn on", () => act("autopilot", { on: !autopilot }), !autopilot)));
    rows.unshift(row("Screen assist", "Nova reads your app, points, scrolls, and works in it with your real mouse and keyboard. Esc stops her.",
      button(switches.assist ? "Turn off" : "Turn on", () => act("assist", { on: !switches.assist }), !switches.assist)));
    if ((state.displays || []).length) rows.splice(5, 0, row("Read the screen", "Review the text before sharing it.", displayPicker));
  }
  modal("Screen", rows, [{ label: "Close", value: null, cancel: true }]);
}

async function readScreen(display) {
  if (await consent("read_screen", {})) act("read_screen", { display: Number(display) });
}

function readFile(file) {
  if (!file) return;
  const extension = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
  if (!READABLE_FILES.includes(extension)) { toast("Nova reads only plain-text files you pick.", "warn"); return; }
  if (file.size > 512000) { toast("Files are limited to 500 KB.", "warn"); return; }
  const reader = new FileReader();
  reader.onload = () => showReview(`File · ${file.name}`, "A file you picked · read-only · not sent or saved yet", String(reader.result).slice(0, 6000));
  reader.onerror = () => toast("Couldn't read that file as text.", "warn");
  reader.readAsText(file);
}

async function showPairing(result) {
  if (!result || !result.url) return;
  const steps = document.createTextNode("1. Put the phone on the same Wi-Fi as this PC.\n2. Scan this code with the phone's camera and open the link.\n3. The page walks you through installing Nova's certificate once (for a private connection and the mic), then opens Nova Lite.\n4. In Safari, tap Share → Add to Home Screen.\nKeep this code private: anyone who scans it can use Nova.");
  const image = Object.assign(document.createElement("img"), { className: "qr", src: result.qr, alt: "Pairing QR code" });
  const address = Object.assign(document.createElement("p"), { className: "muted small",
    textContent: `${result.url.split("#")[0]} · certificate ${result.fingerprint || ""}` });
  const choice = await modal("Pair your iPhone", [steps, image, address], [
    { label: "Turn off", value: "off", danger: true },
    { label: "New code", value: "new" },
    { label: "Done", value: null, primary: true, cancel: true },
  ]);
  if (choice === "off") act("phone", { on: false });
  if (choice === "new") showPairing(await act("phone_new_code"));
}

// ---------- settings ----------

async function loadAudioDevices() {
  const result = await act("audio_devices");
  if (!result.ok) return;
  const fill = (select, items, current) => {
    select.replaceChildren(new Option("System default", ""), ...items.map((item) => new Option(item.label, item.key)));
    select.value = current || "";
  };
  fill($("#audio-input"), result.inputs, result.input_key);
  fill($("#audio-output"), result.outputs, result.output_key);
  $("#audio-voice").replaceChildren(new Option("Windows built-in voice (female)", ""),
    ...result.voices.map((voice) => new Option(`${voice.name}${voice.installed ? "" : ` (download ${voice.mb} MB)`}`, voice.name)));
  $("#audio-voice").value = result.voice || "";
  $("#whisper-info").textContent = result.whisper_installed
    ? "Speech recognition: Whisper (best for accents and broken English)."
    : "Speech recognition: basic. Whisper understands accents and broken English much better.";
  $("#install-whisper").hidden = result.whisper_installed;
  $("#install-whisper").textContent = `Install Whisper · ${result.whisper_mb} MB`;
}

function audioStatus(text, tone = "") {
  const element = $("#audio-status");
  element.textContent = text;
  element.className = `status-line ${tone}`;
}

const audioChoice = () => ({ input_key: $("#audio-input").value || null, output_key: $("#audio-output").value || null });

// ---------- toasts ----------

function toast(text, tone = "info", action = null) {
  const element = document.createElement("div");
  element.className = `toast ${tone}`;
  const words = document.createElement("div");
  words.textContent = text;
  if (action) {
    const button = Object.assign(document.createElement("button"), { className: "box on", textContent: action.label });
    button.onclick = () => { act(action.name, action.args || {}); dismiss(); };
    words.append(document.createElement("br"), button);
  }
  const close = Object.assign(document.createElement("button"), { className: "icon-button", textContent: "✕" });
  close.setAttribute("aria-label", "Dismiss");
  const dismiss = () => { element.classList.add("leaving"); setTimeout(() => element.remove(), 320); };
  close.onclick = dismiss;
  element.append(words, close);
  $("#toasts").append(element);
  while ($("#toasts").children.length > 4) $("#toasts").firstChild.remove();
  setTimeout(dismiss, action ? 20000 : tone === "info" || tone === "ok" ? 5000 : 12000);
}

// ---------- creative mode ----------

function openCreative(url) {
  const accent = ACCENTS[(state.settings || {}).accent] || ACCENTS.gold;
  const name = (state.settings || {}).owner_name || ""; // the ASCII lens writes you with your name's letters
  $("#creative-frame").src = `${url}#accent=${encodeURIComponent(accent)}&name=${encodeURIComponent(name)}`;
  $("#creative-layer").hidden = false;
}

function closeCreative() {
  $("#creative-frame").src = "about:blank"; // frees the camera; Nova notices the page stopped polling
  $("#creative-layer").hidden = true;
}

// ---------- wiring ----------

$$("[data-pane]").forEach((button) => button.addEventListener("click", () => setPane(button.dataset.pane)));
$("#drawer-close").onclick = () => setPane(openPane);
$("[data-act=camera]").onclick = () => act("creative");
$("[data-act=screen]").onclick = screenMenu;
$("[data-act=map]").onclick = () => openMap(!mapOpen);
$("[data-act=advance]").onclick = () => act("advance", { on: !(state.settings || {}).advance });
$("[data-act=library]").onclick = () => (library.isOpen() ? library.close() : library.open());
$("[data-act=world]").onclick = () => (world.isOpen() ? world.close() : world.open());
$("[data-act=route]").onclick = () => (routeView.isOpen() ? routeView.close() : routeView.open());
$("[data-act=rea]").onclick = () => (rea.isOpen() ? rea.close() : rea.open());
$("[data-act=shannon]").onclick = () => (shannon.isOpen() ? shannon.close() : shannon.open());
$("[data-act=skills]").onclick = () => (skills.isOpen() ? skills.close() : skills.open());
$("#map-add").onclick = () => mindmap.addIdea();
$("#map-outline-toggle").onclick = () => setPane("notes");
$("#map-tidy").onclick = () => mindmap.tidy();
$("#map-undo").onclick = () => mindmap.undo();
$("#map-redo").onclick = () => mindmap.redo();
$("#map-close").onclick = () => openMap(false);
$("#map-export").onclick = () => mindmap.exportImage();
$("#map-copy").onclick = async () => {
  const { title, outline } = mindmap.data();
  try { await navigator.clipboard.writeText(`${title}\n${outline.split("\n").map((line) => "  " + line).join("\n")}`); toast("Map copied as text.", "ok"); }
  catch { toast("Couldn't copy.", "warn"); }
};
$("#map-quick").addEventListener("submit", (event) => {
  event.preventDefault();
  const box = $("#map-quick-text");
  if (mindmap.addTyped(box.value)) box.value = ""; // stays focused, so you can keep typing ideas
});
$("#map-quick-text").addEventListener("paste", (event) => {
  const text = event.clipboardData?.getData("text") || "";
  if (text.includes("\n")) { event.preventDefault(); mindmap.addTyped(text); }
});
$("#map-ask").onclick = () => askAlfredAbout(mindmap.selectedPath());
// Written straight onto the selected idea (saving to the PC is debounced separately).
$("#map-note-text").addEventListener("input", (event) => mindmap.setNote(event.target.value));
$("#map-link").onclick = () => mindmap.startLink();
$("#map-own-icon").addEventListener("input", (event) => showStyle(mindmap.setStyle({ icon: event.target.value })));
$("#map-new").onclick = () => { mapTitle = ""; act("notes_new"); };
$("#map-delete").onclick = async () => {
  const title = $("#map-title").value.trim();
  if (title && await yesNo("Delete this map?", `“${title}” will be removed from this PC.`, "Delete")) act("notes_delete", { title });
};
$("#map-saved").onchange = (event) => act("notes_load", { index: Number(event.target.value) });
const typedMap = () => mindmap.setText($("#map-title").value, $("#map-outline").value);
$("#map-title").addEventListener("input", typedMap);
$("#map-outline").addEventListener("input", typedMap);
$("#keep-running").onchange = (event) => act("settings", { keep_running: event.target.checked });
$("#mini-orb").onchange = (event) => act("settings", { mini_orb: event.target.checked });
$("#owner-name").onchange = (event) => act("settings", { owner_name: event.target.value });
$("#location-save").onclick = () => act("location_city", { place: $("#location-city").value });
$("#location-city").addEventListener("keydown", (event) => { if (event.key === "Enter") $("#location-save").click(); });
$("#location-device").onclick = () => act("location_device");
$("#location-forget").onclick = () => act("location_forget");
// ---------- hotkeys: press the new keys together, release, saved ----------
const KEY_NAMES = { Control: "Ctrl", Alt: "Alt", Shift: "Shift", Meta: "Win", " ": "Space", Escape: "Esc" };
function startHotkeyCapture(which) {
  hotkeyCapture = { which, held: new Set(), most: [] };
  $(`#hotkey-${which}`).textContent = "Press keys…";
  $("#hotkey-help").textContent = "Press the new keys together, then let go. Click Change again to cancel.";
}
function keyLabel(event) {
  return KEY_NAMES[event.key] || (event.key.length === 1 ? event.key.toUpperCase() : event.key);
}
addEventListener("keydown", (event) => {
  if (!hotkeyCapture) return;
  event.preventDefault();
  event.stopImmediatePropagation();
  hotkeyCapture.held.add(event.keyCode);
  if (hotkeyCapture.held.size >= hotkeyCapture.most.length) {
    hotkeyCapture.most = [...hotkeyCapture.held];
    hotkeyCapture.names = { ...(hotkeyCapture.names || {}), [event.keyCode]: keyLabel(event) };
    $(`#hotkey-${hotkeyCapture.which}`).textContent = hotkeyCapture.most.map((code) => hotkeyCapture.names[code]).join("+");
  }
}, true);
addEventListener("keyup", (event) => {
  if (!hotkeyCapture) return;
  event.preventDefault();
  hotkeyCapture.held.delete(event.keyCode);
  if (hotkeyCapture.held.size === 0 && hotkeyCapture.most.length) {
    const { which, most } = hotkeyCapture;
    hotkeyCapture = null;
    $("#hotkey-help").textContent = "Click Change, then press and release the new keys together (up to three).";
    Promise.resolve(act("hotkey", { which, keys: most.slice(0, 3) })).finally(render); // refused: the saved keys again
  }
}, true);
$("#skills-suggest").onclick = () => act("skills_suggest");
$("#outputs-open").onclick = () => act("open_outputs");
for (const which of ["talk", "stop", "clip", "yes", "no", "dictate"]) {
  $(`#hotkey-${which}-change`).onclick = () => {
    if (hotkeyCapture) { hotkeyCapture = null; render(); return; }
    startHotkeyCapture(which);
  };
}
// ---------- slide things onto the TV: drag a reply or the now-playing card to the drop zone ----------
let slidePayload = null;
function startSlide(payload) { slidePayload = payload; $("#tv-drop").hidden = false; }
function endSlide() { slidePayload = null; setTimeout(() => { $("#tv-drop").hidden = true; $("#tv-drop").classList.remove("over"); }, 50); }
$("#tv-drop").addEventListener("dragover", (event) => { event.preventDefault(); $("#tv-drop").classList.add("over"); });
$("#tv-drop").addEventListener("dragleave", () => $("#tv-drop").classList.remove("over"));
$("#tv-drop").addEventListener("drop", (event) => {
  event.preventDefault();
  if (slidePayload) act("tv_show", slidePayload);
  else if (event.dataTransfer.files.length) slideFile(event.dataTransfer.files[0]);
  endSlide();
});
// A photo or a text file dragged in from Explorer (or a picture from a web page) slides onto the TV too.
const draggingFiles = (event) => [...(event.dataTransfer?.types || [])].includes("Files");
addEventListener("dragenter", (event) => { if (!slidePayload && draggingFiles(event)) $("#tv-drop").hidden = false; });
addEventListener("dragover", (event) => { if (draggingFiles(event)) event.preventDefault(); }); // else a file dropped elsewhere replaces the HUD
addEventListener("drop", (event) => { if (draggingFiles(event)) { event.preventDefault(); endSlide(); } });
addEventListener("dragleave", (event) => { if (!event.relatedTarget && !slidePayload) endSlide(); }); // left the window
async function slideFile(file) {
  const title = file.name.replace(/\.[^.]+$/, "");
  if (file.type.startsWith("image/")) {
    // a phone photo can be 12 MB: the TV gets at most 1920 px as JPEG
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, 1920 / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale); canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    let quality = 0.85, image = canvas.toDataURL("image/jpeg", quality);
    while (image.length > 2_900_000 && quality > 0.4) image = canvas.toDataURL("image/jpeg", (quality -= 0.15));
    act("tv_show", { kind: "image", title, image });
  } else if (file.type.startsWith("text/") || /\.(md|txt)$/i.test(file.name)) {
    act("tv_show", { kind: "note", title, body: (await file.text()).slice(0, 4000) });
  } else {
    toast("Only pictures and text files can go on the TV.", "info");
  }
}
$("#music").addEventListener("dragstart", () => {
  const music = state.music || {};
  startSlide({ kind: "music", title: music.title || "", body: [music.artist, music.album].filter(Boolean).join(" · "), image: music.cover || "" });
});
$("#music").addEventListener("dragend", endSlide);
async function showScreens(box) {
  const info = await act("screens_info");
  if (!info || !info.ok) return;
  $("#screens-tv").textContent = info.tv;
  $("#screens-qr").src = info.deck_qr;
  $(box).hidden = false;
}
$("#screens-show").onclick = () => showScreens("#screens-info");
$("#deck-show").onclick = () => showScreens("#deck-info");
$("#screens-forget").onclick = () => act("tv_forget");
$("#music-previous").onclick = () => act("media", { action: "previous" });
$("#music-play").onclick = () => act("media", { action: "play_pause" });
$("#music-next").onclick = () => act("media", { action: "next" });
$("#hotkey-reset").onclick = () => act("hotkey", { reset: true });
$("#brain-toggle").onclick = () => act("second_brain", { on: !(state.second_brain || {}).on });
$("#brain-now").onclick = () => act("second_brain_now");
$("#brain-ingest").onclick = () => act("second_brain_ingest");
$("#brain-open").onclick = () => act("open_vault");
$("#brain-vault-save").onclick = () => act("second_brain_settings", { vault: $("#brain-vault").value });
$("#brain-videos").onchange = (event) => act("second_brain_settings", { videos: event.target.checked });
$("#brain-exclude-save").onclick = () => act("second_brain_settings", { exclude: $("#brain-exclude").value });
$("#pcs-toggle").onclick = () => act("pc_sync", { on: !(state.pcs || {}).on });
$("#pcs-wiki").onclick = () => act("wiki_here");
$("#heart-toggle").onclick = () => act("heart", { on: !(state.heart || {}).on });
$("#gesture-pose").onchange = renderGestures;
$("#model-load").onclick = () => act("model_load");
$("#tune-now").onclick = () => act("tune_now");
$("#tune-auto").onclick = () => act("auto_tune", { on: !state.tuning?.auto });
$("#version-create").onclick = async () => {
  const result = await act("version_create", { base: $("#version-base").value, name: $("#version-name").value, system: $("#version-system").value,
    temperature: $("#version-temp").value, num_ctx: $("#version-ctx").value });
  if (result.ok !== false) toast("Making the new version…", "info");
};
$("#compare-run").onclick = () => act("model_compare", { a: $("#compare-a").value, b: $("#compare-b").value });
$("#model-unload").onclick = () => act("model_unload");
$("#downloads").addEventListener("toggle", () => { $("#downloads").dataset.touched = "1"; });
$("#gesture-action").onchange = renderGestures;
$("#gesture-add").onclick = async () => {
  const result = await act("gesture_add", { name: $("#gesture-name").value, pose: $("#gesture-pose").value,
    action: $("#gesture-action").value, phrase: $("#gesture-phrase").value });
  if (result.ok !== false && !result.cancelled) { $("#gesture-name").value = ""; $("#gesture-phrase").value = ""; }
};
$$("[data-switch]").forEach((button) => button.addEventListener("click", async () => {
  const name = button.dataset.switch;
  const result = await act(name, { on: !(state.switches || {})[name] });
  if (name === "phone" && result.ok && result.url) showPairing(result);
}));
$("#speak-toggle").onclick = () => act("speak", { on: !(state.switches || {}).speak });
$("#ask").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (mapOpen) await flushMapSave(); // "Hey Nova, add … to the map" works on what you see
  const input = $("#text");
  const text = input.value.trim();
  if (!text) return;
  if (state.busy) { toast("Nova is still working on the last request. Esc stops it.", "warn"); return; }
  input.value = "";
  act("send", { text });
});
$("#file-input").addEventListener("change", (event) => { readFile(event.target.files[0]); event.target.value = ""; });
$("#creative-close").onclick = closeCreative;
$("#step-next").onclick = () => act("walkthrough_next");
$("#step-stop").onclick = () => act("walkthrough_stop");
addEventListener("message", (event) => {
  if (/^http:\/\/127\.0\.0\.1:\d+$/.test(event.origin) && event.data === "alfred:close-creative") closeCreative();
});
$$("#swatches button").forEach((button) => button.addEventListener("click", () => act("settings", { accent: button.dataset.accent })));
$("#model-select").onchange = (event) => act("set_model", { name: event.target.value });
$("#brain-choice").onchange = async (event) => {
  const result = await act("brain_choose", { brain: event.target.value });
  if (result.ok === false || result.cancelled) render(); // not changed: show the brain still in use
};
$("#private-topics").onchange = (event) => act("privacy", { private: event.target.value });
$("#api-provider").onchange = providerChanged;
$("#api-load-models").onclick = async () => {
  const result = await act("api_brain_models", { provider: $("#api-provider").value, base_url: $("#api-base").value, key: $("#api-key").value });
  if (result && result.models) {
    $("#api-models").replaceChildren(...result.models.map((id) => new Option(id, id)));
    toast(`${result.models.length} models: start typing to pick one.`, "info");
  }
};
$("#api-add-save").onclick = async () => {
  const result = await act("api_brain_add", { provider: $("#api-provider").value, base_url: $("#api-base").value,
    key: $("#api-key").value, model: $("#api-model").value });
  if (result && result.ok !== false) { $("#api-key").value = ""; $("#api-model").value = ""; $("#api-add").open = false; }
};
$("#free-cloud-signin").onclick = () => act("free_cloud_signin");
$("#free-cloud-save").onclick = () => act("free_cloud_settings", { model: $("#free-cloud-model").value });
$("#free-cloud-model").addEventListener("keydown", (event) => { if (event.key === "Enter") $("#free-cloud-save").click(); });
$("#claude-model").onchange = (event) => act("claude_settings", { model: event.target.value });
$("#claude-effort").onchange = (event) => act("claude_settings", { effort: event.target.value });
$("#telegram-token-save").onclick = async () => {
  const result = await act("telegram_token", { token: $("#telegram-token").value });
  if (result && result.ok !== false) $("#telegram-token").value = "";
};
$("#telegram-toggle").onclick = () => act("telegram", { on: !(state.telegram || {}).on });
$("#telegram-unpair").onclick = () => act("telegram_unpair");
$("#telegram-token-forget").onclick = () => act("telegram_token_forget");
$("#telegram-relay-brain").onchange = () => renderTelegram();
$("#discover-refresh").onclick = () => act("discover_refresh", { force: true });
$("#discover-user-save").onclick = () => act("discover_settings", { username: $("#discover-user").value });
$("#discover-token-save").onclick = async () => {
  const result = await act("discover_settings", { token: $("#discover-token").value });
  if (result && result.ok !== false) $("#discover-token").value = "";
};
$("#discover-token-forget").onclick = () => act("discover_settings", { forget_token: true });
$("#reverse-toggle").onclick = () => act("reverse_toggle", { on: !(state.discover || {}).reverse_on });
$("#update-auto").onchange = (event) => act("update_auto", { on: event.target.checked });
$("#update-check").onclick = () => act("update_check");
$("#update-install").onclick = () => act("update_install");
$("#update-rollback").onclick = () => act("update_rollback");
$("#update-page").onclick = () => act("open_url", { url: (state.update || {}).page });
$("#telegram-relay-setup").onclick = async () => {
  const result = await act("telegram_relay", { cloudflare_token: $("#telegram-cloudflare").value,
    brain: $("#telegram-relay-brain").value, brain_key: $("#telegram-relay-key").value });
  if (result && result.ok !== false) { $("#telegram-cloudflare").value = ""; $("#telegram-relay-key").value = ""; }
};
$("#telegram-relay-remove").onclick = async () => {
  if (!$("#telegram-cloudflare").value) return toast("Paste your Cloudflare API token above, then click Remove relay.", "info");
  const result = await act("telegram_relay", { cloudflare_token: $("#telegram-cloudflare").value, remove: true });
  if (result && result.ok !== false) $("#telegram-cloudflare").value = "";
};
$("#model-offer-button").onclick = () => act("pull_model", { name: state.model.offer.name });
$("#test-mic").onclick = () => act("test_mic", audioChoice());
$("#test-speaker").onclick = () => act("test_speaker", audioChoice());
$("#test-voice").onclick = () => act("test_voice");
$("#install-whisper").onclick = () => act("install_whisper");
$("#vision-button").onclick = () => act("pull_vision");
$("#audio-save").onclick = async () => {
  const result = await act("audio_save", { ...audioChoice(), voice: $("#audio-voice").value || null });
  if (result.ok) { audioStatus("Saved.", "ok"); loadAudioDevices(); }
};
$("#phone-pair").onclick = async () => {
  const result = (state.switches || {}).phone ? await act("phone_pairing") : await act("phone", { on: true });
  if (result.ok) showPairing(result);
};
$("#gmail-toggle").onclick = async () => {
  const result = await act("gmail");
  if (result.need_setup) {
    modal("Connect Google", `Gmail, Google Calendar and Google Drive need your own Google sign-in app (free, one time):\n\n1. In Google Cloud Console, create a project and enable the Gmail API, the Google Calendar API and the Google Drive API.\n2. OAuth consent screen: External, and add your own Gmail address as a test user.\n3. Create an OAuth client of type “Desktop app” and download its JSON file.\n4. Save that file as:\n${result.path}\n5. Click Connect again and allow Gmail, Calendar and Drive.\n\nStep by step: Settings → Need to → Google. Nova can list and read unread mail and save drafts you approve (it never sends mail), read and add calendar events, and find and read Drive files (read-only).`,
      [{ label: "OK", value: null, primary: true, cancel: true }]);
  }
};
$("#obs-password-save").onclick = () => { act("obs_password", { password: $("#obs-password").value }); $("#obs-password").value = ""; toast("Saved on this PC.", "ok"); };
$("#knowledge-sizes").onclick = () => { toast("Asking Kiwix's library for the sizes…", "info"); act("knowledge_catalog"); };
$("#notes-index").onclick = () => act("notes_index");
$("#keep-city-save").onclick = () => { toast("Downloading the roads; it can take a few minutes for a big city.", "info"); act("keep_city", { city: $("#keep-city").value }); };
$("#node-path-save").onclick = () => act("node_path", { path: $("#node-path").value });
$("#drive-connect").onclick = () => {
  toast("Google opens in your browser: allow Drive too. If it says the Drive API is off, enable it in Google Cloud Console for your project first.", "info");
  act("gmail", { drive: true });
};
$("#need-google-connect").onclick = () => $("#gmail-toggle").click();
$("#claude-connectors").onchange = (event) => act("claude_connectors", { on: event.target.checked });
$("#cloud-fallback").onchange = (event) => act("cloud_fallback", { on: event.target.checked });
$("#google-mcp-toggle").onclick = () => act("google_mcp", { on: !(state.google_mcp || {}).on });
$("#google-mcp-new-key").onclick = async () => {
  if (await yesNo("Make a new key?", "Every Claude app set up with the old key stops reaching Nova until you paste the new setup into it.", "New key")) act("google_mcp", { new_key: true });
};
$$("[data-copy]").forEach((button) => button.addEventListener("click", async () => {
  try { await navigator.clipboard.writeText($(button.dataset.copy).value); toast("Copied.", "ok"); }
  catch { $(button.dataset.copy).select(); toast("Press Ctrl+C to copy.", "info"); }
}));
$("#calendar-connect").onclick = () => {
  toast("Google opens in your browser: allow Calendar too. If it says the Calendar API is off, enable it in Google Cloud Console for your project first.", "info");
  act("gmail", { calendar: true });
};
$("#interest-input").addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  const value = event.target.value.trim();
  const interests = (state.settings || {}).interests || [];
  if (value && !interests.includes(value)) act("settings", { interests: [...interests, value].slice(0, 4) });
  event.target.value = "";
});
$("#brief-region").onchange = (event) => act("settings", { brief_region: event.target.value });
$("#outlet-input").addEventListener("keydown", async (event) => {
  if (event.key !== "Enter" || !event.target.value.trim()) return;
  const result = await act("settings", { news_outlets: [...((state.settings || {}).news_outlets || []), event.target.value.trim()] });
  if (result.ok !== false) event.target.value = "";
});
$("#brief-toggle").onclick = () => act("brief", { on: !(state.switches || {}).brief });
$("#news-toggle").onclick = () => act("news", { on: !(state.news || {}).on });
$("#news-run").onclick = () => act("news_run");
$("#news-key-save").onclick = async () => { const result = await act("news_key", { key: $("#news-key").value }); if (result.ok !== false) $("#news-key").value = ""; };
$("#news-key-forget").onclick = () => act("news_key_forget");
$("#news-query").addEventListener("keydown", (event) => { if (event.key === "Enter") searchNews(); });
$("#news-days").onchange = searchNews;
$("#news-category").onchange = searchNews;
$("#brief-refresh").onclick = () => act("brief_refresh");

document.addEventListener("keydown", (event) => {
  const typing = /^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement?.tagName || "");
  if (!$("#modal").hidden) {
    if (event.key === "Escape" && modalOnClose) { event.preventDefault(); modalOnClose(); return; }
    const key = event.key.toUpperCase();
    const button = $$("#modal-buttons button").find((candidate) => candidate.dataset.key && candidate.dataset.key === key);
    if (button && !typing) { event.preventDefault(); button.click(); }
    return;
  }
  if (library.isOpen() && openPane === null && library.handleKey(event)) { event.preventDefault(); return; }
  if (rea.isOpen() && openPane === null && !typing && rea.handleKey(event)) { event.preventDefault(); return; }
  if (shannon.isOpen() && openPane === null && !typing && shannon.handleKey(event)) { event.preventDefault(); return; }
  if (mapOpen && !typing && mindmap.handleKey(event)) { event.preventDefault(); return; }
  if (event.key === "Escape") {
    if (!$("#creative-layer").hidden) closeCreative();
    else if (openPane) setPane(openPane);
    else if (world.isOpen()) world.close();
    else if (routeView.isOpen()) routeView.close();
    else if (rea.isOpen()) rea.close();
    else if (shannon.isOpen()) shannon.close();
    else if (skills.isOpen()) skills.close();
    else if (mapOpen) openMap(false);
    else act("stop");
    return;
  }
  if (event.key === "/" && !typing) { event.preventDefault(); $("#text").focus(); }
});

function tick() {
  const now = new Date();
  $("#clock").textContent = now.toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" }).toUpperCase();
}
setInterval(() => { tick(); renderTimers(); }, 1000);
tick();
window.alfred = { act, handle, mindmap, library, state: () => state }; // for tests
if (token) connect(); else $("#offline").hidden = false;
