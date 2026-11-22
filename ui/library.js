// Nova's Library: big cards on a 3D shelf. Topics come from the second brain; projects, repos and ideas to build are
// the owner's own. It moves with the mouse, the keys, the voice ("next", "open 3", "open robotics") and hand gestures
// (✋ swipe, ✊ open, 👎 back, ✌ close). Nova owns the data (Markdown in the vault); this page only shows it.

import { h } from "./lab.js";
import { askPhrase, mountWhatCanIDo } from "./whatcanido.js";

const SHELVES = { topics: "Topics", projects: "Projects", ideas: "Ideas", needs: "Needs you" };
const STATUSES = { idea: "Idea", building: "Building", shipped: "Shipped", paused: "Paused" };
const STATUS_ORDER = { building: 0, idea: 1, paused: 2, shipped: 3 };
const KIND_LABEL = { topic: "Topic", about: "About", project: "Project", idea: "Idea", new: "New", empty: "Empty" };
const VISIBLE = 5; // cards shown on each side of the one in front

const pad = (number) => String(number).padStart(2, "0");
const fill = (parent, ...children) => { parent.append(...children.filter(Boolean)); return parent; };
const plain = (text) => String(text || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/đ/gi, "d").toLowerCase();

function ago(stamp) {
  if (!stamp) return "";
  const then = new Date(stamp.replace(" ", "T"));
  if (Number.isNaN(then.getTime())) return "";
  const minutes = Math.max(0, Math.round((Date.now() - then.getTime()) / 60000));
  if (minutes < 60) return minutes <= 1 ? "just now" : `${minutes} min ago`;
  if (minutes < 60 * 24) return `${Math.round(minutes / 60)} h ago`;
  return `${Math.round(minutes / 1440)} d ago`;
}

function host(repo) {
  if (!repo) return "";
  try { const url = new URL(repo); return (url.host + url.pathname).replace(/\/$/, ""); } catch { return repo.split(/[\\/]/).filter(Boolean).slice(-2).join("\\"); }
}

// A small seeded random, so each card always gets the same point cloud.
function seeded(text) {
  let seed = 2166136261;
  for (const char of String(text)) seed = Math.imul(seed ^ char.charCodeAt(0), 16777619);
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let value = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    value = (value + Math.imul(value ^ (value >>> 7), 61 | value)) ^ value;
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
}

// The card's point cloud: a wavy sheet of dots, denser the more there is in it.
function cloud(name, count) {
  const random = seeded(name);
  const phase = random() * 6.28, waves = 1.6 + random() * 2.2;
  return Array.from({ length: count }, () => {
    const x = random() * 2 - 1, z = random() * 2 - 1;
    return [x, 0.36 * Math.sin(x * waves * 2 + phase) * Math.cos(z * 2.1) + (random() - 0.5) * 0.1, z, 0.9 + random() * 1.7];
  });
}

function drawCloud(canvas, points, angle, rgb, bright) {
  const ratio = Math.min(2, window.devicePixelRatio || 1);
  const width = canvas.clientWidth, height = canvas.clientHeight;
  if (!width || !height) return;
  if (canvas.width !== Math.round(width * ratio)) { canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio); }
  const context = canvas.getContext("2d");
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, width, height);
  const cos = Math.cos(angle), sin = Math.sin(angle), tilt = 0.42;
  for (const [x, y, z, size] of points) {
    const rx = x * cos - z * sin, rz = x * sin + z * cos;
    const ty = y * Math.cos(tilt) - rz * Math.sin(tilt), tz = y * Math.sin(tilt) + rz * Math.cos(tilt);
    const depth = 1 / (2.2 + tz);
    const sx = width / 2 + rx * width * 1.05 * depth, sy = height / 2 + ty * Math.max(height, width * 0.5) * 1.5 * depth;
    context.fillStyle = `rgba(${rgb}, ${(bright ? 0.4 : 0.2) + (bright ? 0.6 : 0.3) * (1 - (tz + 1) / 2)})`;
    context.fillRect(sx, sy, size * depth * 2, size * depth * 2);
  }
}

export function createLibrary(root, { act, toast, confirm, onOpenChange }) {
  const $ = (selector) => root.querySelector(selector);
  const track = $("#lib-track"), ruler = $("#lib-ruler"), detail = $("#lib-detail"), orbit = $("#lib-orbit");
  const form = $("#lib-form"), search = $("#lib-search"), flashBox = $("#lib-flash");
  let data = { topics: [], projects: [], needs: [] };
  let opened = false, shelf = "topics", topic = null, index = 0, query = "", expanded = false;
  const remembered = {}; // where each shelf was, to come back to it
  let cards = [], elements = [], editing = null, loading = null;

  const accent = (() => {  // the accent only changes in Settings: don't ask the style engine every frame
    let cached = "", key = "";
    return () => {
      const now = document.documentElement.dataset.accent || "";
      if (now !== key) {
        key = now;
        cached = getComputedStyle(document.documentElement).getPropertyValue("--accent-rgb").trim() || "255, 176, 64";
      }
      return cached;
    };
  })();
  mountWhatCanIDo(root, "library", { onPhrase: askPhrase });

  // ---------- what is on the shelf ----------
  function shelfCards() {
    const projects = data.projects || [];
    const byNewest = (a, b) => String(b.updated).localeCompare(String(a.updated));
    let list;
    if (shelf === "topics") list = (data.topics || []).map((item) => ({ kind: "topic", key: `t:${item.name}`, title: item.name, topic: item }));
    else if (shelf === "projects") list = projects.filter((item) => item.status !== "idea").sort((a, b) => STATUS_ORDER[a.status] - STATUS_ORDER[b.status] || byNewest(a, b))
      .map((item) => ({ kind: "project", key: `p:${item.title}`, title: item.title, project: item }));
    else if (shelf === "ideas") list = projects.filter((item) => item.status === "idea").sort(byNewest)
      .map((item) => ({ kind: "idea", key: `p:${item.title}`, title: item.title, project: item }));
    else if (shelf === "needs") list = (data.needs || []).map((item) => ({ kind: item.status === "idea" ? "idea" : "project", key: `p:${item.title}`, title: item.title, project: item, why: item.why }));
    else {
      const inside = (topic.projects || []).slice().sort((a, b) => STATUS_ORDER[a.status] - STATUS_ORDER[b.status] || byNewest(a, b));
      list = [{ kind: "about", key: `a:${topic.name}`, title: topic.name, about: topic },
        ...inside.map((item) => ({ kind: item.status === "idea" ? "idea" : "project", key: `p:${item.title}`, title: item.title, project: item }))];
    }
    if (query) {
      const words = plain(query);
      list = list.filter((card) => card.kind === "about" || plain([card.title, card.topic?.summary, card.project?.topic, card.project?.next,
        card.project?.note, card.project?.repo].join(" ")).includes(words));
    }
    if (!query && shelf !== "topics" && shelf !== "needs") {
      list.push({ kind: "new", key: "new", title: shelf === "ideas" ? "New idea" : "New project",
        preset: { status: shelf === "ideas" ? "idea" : shelf === "projects" ? "building" : "idea", topic: shelf === "topic" ? topic.name : "" } });
    }
    if (!list.length) list.push({ kind: "empty", key: "empty", title: query ? "Nothing matches" : shelf === "needs" ? "All clear" : "Nothing here yet" });
    return list;
  }

  function cardBody(card, number) {
    const top = h("header", {}, h("span", { class: "lib-num" }, pad(number)), h("span", { class: "lib-kind" }, KIND_LABEL[card.kind] || card.kind));
    const canvas = h("canvas", { class: "lib-field", "aria-hidden": "true" });
    const parts = [top, canvas];
    if (card.kind === "topic" || card.kind === "about") {
      const item = card.topic || card.about;
      if (item.needs) top.append(h("span", { class: "lib-flag" }, `${item.needs} need you`));
      else if (card.kind === "about" && item.wiki) top.append(h("span", { class: "lib-flag dim" }, "Wiki"));
      parts.push(h("h3", {}, card.title),
        h("p", { class: "lib-sum" }, item.summary || (card.kind === "about" ? "No wiki page yet: Nova writes one when you ingest sources about it." : "Projects and ideas you filed here.")),
        h("dl", { class: "lib-stats" },
          h("div", {}, h("dt", {}, "Notes"), h("dd", {}, pad(item.notes || 0))),
          h("div", {}, h("dt", {}, "Ideas"), h("dd", {}, pad(card.kind === "about" ? (item.projects || []).filter((p) => p.status === "idea").length : item.ideas || 0))),
          h("div", {}, h("dt", {}, "Projects"), h("dd", {}, pad(card.kind === "about" ? (item.projects || []).filter((p) => p.status !== "idea").length : item.projects || 0)))),
        h("footer", {}, card.kind === "about" ? (item.facts && item.facts[0] ? `Newest: ${item.facts[0].replace(/\s*\(from \[\[.*$/, "")}` : "Open the projects with → / swipe")
          : item.updated ? `Updated ${ago(item.updated)}` : "—"));
    } else if (card.project) {
      const item = card.project;
      top.append(h("span", { class: `lib-status ${item.status}` }, STATUSES[item.status] || item.status));
      parts.push(h("h3", {}, card.title),
        h("p", { class: "lib-sum" }, card.why || (item.next ? `Next → ${item.next}` : item.note ? item.note.split("\n")[0] : "No next step yet.")),
        h("dl", { class: "lib-stats" },
          h("div", {}, h("dt", {}, "Topic"), h("dd", {}, item.topic || "—")),
          h("div", {}, h("dt", {}, "Repo"), h("dd", {}, item.repo ? host(item.repo) : "—")),
          h("div", {}, h("dt", {}, "Added"), h("dd", {}, item.added ? item.added.slice(5) : "—"))),
        h("footer", {}, item.updated ? `Updated ${ago(item.updated)}` : "—"));
    } else if (card.kind === "new") {
      parts.push(h("div", { class: "lib-plus", "aria-hidden": "true" }, "+"), h("h3", {}, card.title),
        h("p", { class: "lib-sum" }, "Save a repo you're building or an idea you want to build. It goes into your second brain."));
    } else {
      parts.push(h("h3", {}, card.title), h("p", { class: "lib-sum" },
        query ? "Try other words, or clear the search." : shelf === "needs" ? "No builds or ideas waiting on you."
          : shelf === "topics" ? "Topics appear as your second brain grows, and when you file a project under one." : "Add the first one with + New."));
    }
    return parts;
  }

  function build() {
    cards = shelfCards();
    index = Math.max(0, Math.min(index, cards.length - 1));
    elements = cards.map((card, number) => {
      const element = h("article", { class: `lib-card ${card.kind}${card.project ? ` ${card.project.status}` : ""}`, "data-index": number },
        ...cardBody(card, number + 1));
      const size = card.topic ? 170 + Math.min(260, (card.topic.notes || 0) * 10 + (card.topic.projects + card.topic.ideas) * 24)
        : card.about ? 200 + Math.min(240, (card.about.notes || 0) * 10) : card.project ? { idea: 150, building: 280, shipped: 360, paused: 120 }[card.project.status] || 180 : 40;
      element.points = cloud(card.key, size);
      return element;
    });
    track.replaceChildren(...elements);
    ruler.replaceChildren(...cards.map((card, number) => h("button", {
      class: "lib-tick", type: "button", title: card.title, "aria-label": `${number + 1}: ${card.title}`,
      onclick: () => go(number),
    }, cards.length <= 24 || number % 5 === 0 || number === cards.length - 1 ? h("span", {}, pad(number + 1)) : null)));
    root.querySelectorAll("[data-shelf]").forEach((button) => button.classList.toggle("on", button.dataset.shelf === shelf));
    $("#lib-needs-count").textContent = (data.needs || []).length ? String(data.needs.length) : "";
    $("#lib-crumb").textContent = shelf === "topic" ? ` / ${topic.name}` : ` / ${SHELVES[shelf]}`;
    const color = accent();
    elements.forEach((element) => requestAnimationFrame(() => drawCloud(element.querySelector(".lib-field"), element.points, 0.6, color, false)));
    place();
  }

  // ---------- the 3D shelf ----------
  function place() {
    const width = track.clientWidth || 1000;
    const cardWidth = elements[0]?.offsetWidth || 260;
    elements.forEach((element, number) => {
      const offset = number - index, side = Math.sign(offset), distance = Math.abs(offset);
      element.classList.toggle("center", offset === 0);
      element.classList.toggle("far", distance > VISIBLE);
      if (offset === 0) element.style.transform = "translate3d(0, 0, 70px)";
      else {
        const x = side * (cardWidth * 0.8 + (distance - 1) * Math.min(cardWidth * 0.26, width * 0.06));
        element.style.transform = `translate3d(${x}px, 0, ${-150 - (distance - 1) * 70}px) rotateY(${-side * 54}deg)`;
      }
      element.style.zIndex = String(100 - distance);
      element.style.opacity = distance > VISIBLE ? "0" : String(1 - Math.max(0, distance - 1) * 0.15);
    });
    [...ruler.children].forEach((tick, number) => tick.classList.toggle("on", number === index));
    const shelfName = shelf === "topic" ? topic.name : SHELVES[shelf];
    $("#lib-counter").textContent = `${shelfName.toUpperCase()} · ${pad(cards.length ? index + 1 : 0)} / ${pad(cards.filter((card) => card.kind !== "new" && card.kind !== "empty").length)}`;
    renderDetail();
  }

  function go(number) {
    if (!cards.length) return;
    const next = Math.max(0, Math.min(cards.length - 1, number));
    if (next !== index) expanded = false;
    index = next;
    place();
  }
  const move = (step) => go(index + step);

  // ---------- the panel under the shelf ----------
  function button(label, onclick, extra = "") { return h("button", { class: `box small ${extra}`, type: "button", onclick }, label); }

  function renderDetail() {
    const card = cards[index];
    if (!card) { detail.replaceChildren(); return; }
    const left = h("div", { class: "lib-detail-text" });
    const right = h("div", { class: "lib-detail-actions" });
    if (card.kind === "topic") {
      const item = card.topic;
      fill(left, h("h4", {}, item.name), h("p", {}, item.summary || "Your projects and ideas filed under this topic."),
        chips(item.related));
      right.append(button("Open topic ⏎", () => enterTopic(item.name), "on"));
    } else if (card.kind === "about") {
      const item = card.about;
      fill(left, h("h4", {}, `${item.name} · ${item.notes} note${item.notes === 1 ? "" : "s"} from ${item.sources} source${item.sources === 1 ? "" : "s"}`),
        item.facts.length ? h("ul", { class: "lib-facts" }, ...item.facts.slice(0, expanded ? 12 : 3).map((fact) => h("li", {}, fact.replace(/\s*\(from \[\[.*$/, ""))))
          : h("p", {}, "Nothing in the wiki about it yet."), chips(item.related));
      if (item.facts.length > 3) right.append(button(expanded ? "Fewer notes" : "More notes ⏎", () => { expanded = !expanded; renderDetail(); }));
      right.append(button("+ Project here", () => openForm(null, { topic: item.name, status: "building" })),
        button("+ Idea here", () => openForm(null, { topic: item.name, status: "idea" })));
    } else if (card.project) {
      const item = card.project;
      fill(left, h("h4", {}, item.title, item.topic ? h("button", { class: "lib-chip", type: "button", onclick: () => enterTopic(item.topic) }, `# ${item.topic}`) : null),
        card.why && !card.why.startsWith("Next:") ? h("p", { class: "lib-why" }, card.why) : null,
        h("p", {}, item.next ? `Next step → ${item.next}` : "No next step yet: Edit to add one."),
        expanded && item.note ? h("pre", { class: "lib-note" }, item.note) : null,
        h("div", { class: "lib-states" }, ...Object.entries(STATUSES).map(([status, label]) =>
          h("button", { class: `lib-state ${status}${item.status === status ? " on" : ""}`, type: "button", "aria-pressed": String(item.status === status),
            onclick: () => setStatus(item, status) }, label))));
      if (item.repo) right.append(button(/^https?:/.test(item.repo) ? "Open repo ↗" : "Open folder", () => act("library_open", { title: item.title }), "on"));
      if (item.note) right.append(button(expanded ? "Hide notes" : "Notes ⏎", () => { expanded = !expanded; renderDetail(); }));
      right.append(button("Edit", () => openForm(item)), button("Obsidian", () => act("library_open", { title: item.title, obsidian: true })));
    } else if (card.kind === "new") {
      fill(left, h("h4", {}, card.title), h("p", {}, "A repo you're building, or an idea to build later. Or just say “Hey Nova, add an idea to my library: …”"));
      right.append(button("+ New ⏎", () => openForm(null, card.preset), "on"));
    } else {
      fill(left, h("h4", {}, card.title), h("p", {}, "Say “Hey Nova, save an idea to my library: …”, or press + New."));
    }
    detail.replaceChildren(left, right);
  }

  function chips(related) {
    if (!related || !related.length) return null;
    return h("div", { class: "lib-chips" }, h("span", { class: "muted" }, "Related"),
      ...related.slice(0, 8).map((name) => h("button", { class: "lib-chip", type: "button", onclick: () => enterTopic(name) }, `# ${name}`)));
  }

  // ---------- moving around ----------
  function enter() {
    const card = cards[index];
    if (!card) return;
    if (card.kind === "topic") enterTopic(card.topic.name);
    else if (card.kind === "new") openForm(null, card.preset);
    else if (card.kind === "about" || card.project) { expanded = !expanded; renderDetail(); }
  }

  async function enterTopic(name) {
    if (shelf !== "topic") remembered[shelf] = index;
    const result = await act("library_topic", { name });
    if (result.ok === false) return;
    topic = result;
    shelf = "topic";
    index = 0;
    expanded = false;
    clearSearch();
    build();
  }

  function setShelf(name) {
    if (!SHELVES[name]) return;
    if (shelf !== "topic") remembered[shelf] = index;
    shelf = name;
    index = remembered[name] || 0;
    expanded = false;
    clearSearch();
    build();
  }

  function back() {
    if (!form.hidden) { closeForm(); return; }
    if (expanded) { expanded = false; renderDetail(); return; }
    if (query) { clearSearch(); build(); return; }
    if (shelf === "topic") { shelf = "topics"; index = remembered.topics || 0; build(); return; }
    if (shelf !== "topics") { setShelf("topics"); return; }
    close();
  }

  function pick(number) {
    if (number < 1 || number > cards.length) { flash(`No card ${number}`); return; }
    go(number - 1);
    if (cards[index].kind === "topic") enter();
  }

  function goto(target) {
    if (!target) return;
    if (target.kind === "topic") { enterTopic(target.name); return; }
    const project = (data.projects || []).find((item) => item.title === target.name);
    if (!project) return;
    shelf = project.status === "idea" ? "ideas" : "projects";
    clearSearch();
    build();
    go(cards.findIndex((card) => card.project && card.project.title === project.title));
  }

  function clearSearch() { query = ""; search.value = ""; }

  async function setStatus(item, status) {
    if (item.status === status) return;
    const result = await act("library_save", { title: item.title, previous: item.title, status });
    if (result.ok === false) return;
    await refresh(result, item.title);
    flash(`${item.title} → ${STATUSES[status]}`);
  }

  // ---------- adding and editing ----------
  function openForm(item, preset = {}) {
    editing = item;
    const values = item || { title: "", status: "idea", topic: "", repo: "", next: "", note: "", ...preset };
    for (const name of ["title", "status", "topic", "repo", "next", "note"]) form.elements[name].value = values[name] || "";
    $("#lib-form-title").textContent = item ? `Edit · ${item.title}` : values.status === "idea" ? "New idea" : "New project";
    $("#lib-delete").hidden = !item;
    $("#lib-topics").replaceChildren(...(data.topics || []).map((entry) => h("option", { value: entry.name })));
    form.hidden = false;
    form.elements.title.focus();
  }

  function closeForm() { form.hidden = true; editing = null; }

  async function refresh(result, focusTitle) {
    data = result;
    if (shelf === "topic") {
      const inside = await act("library_topic", { name: topic.name });
      if (inside.ok !== false) topic = inside;
    }
    build();
    if (focusTitle) {
      const found = cards.findIndex((card) => card.project && card.project.title === focusTitle);
      if (found >= 0) go(found);
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(["title", "status", "topic", "repo", "next", "note"].map((name) => [name, form.elements[name].value]));
    const result = await act("library_save", { ...values, previous: editing ? editing.title : "", new: !editing });
    if (result.ok === false) return;
    const wasIdea = values.status === "idea";
    closeForm();
    if (shelf !== "topic" && shelf !== "needs") shelf = wasIdea ? "ideas" : "projects";
    await refresh(result, result.saved);
    toast(`Saved to your library: ${result.saved}.`, "ok");
  });
  $("#lib-cancel").addEventListener("click", closeForm);
  $("#lib-delete").addEventListener("click", async () => {
    if (!editing || !(await confirm("Delete from the library?", `“${editing.title}” and its notes will be removed from your vault.`, "Delete"))) return;
    const result = await act("library_delete", { title: editing.title });
    if (result.ok === false) return;
    closeForm();
    await refresh(result);
  });

  // ---------- mouse, wheel, touch and keys ----------
  track.addEventListener("click", (event) => {
    const element = event.target.closest(".lib-card");
    if (!element || dragged) return;
    const number = Number(element.dataset.index);
    if (number === index) enter(); else go(number);
  });
  let wheel = 0, wheelAt = 0;
  $("#lib-stage").addEventListener("wheel", (event) => {
    event.preventDefault();
    wheel += Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY;
    if (Math.abs(wheel) > 50 && performance.now() - wheelAt > 160) { move(Math.sign(wheel)); wheel = 0; wheelAt = performance.now(); }
  }, { passive: false });
  let dragFrom = null, dragged = false;
  $("#lib-stage").addEventListener("pointerdown", (event) => { dragFrom = event.clientX; dragged = false; });
  addEventListener("pointermove", (event) => {
    if (dragFrom === null) return;
    const distance = event.clientX - dragFrom;
    if (Math.abs(distance) > 80) { move(-Math.sign(distance)); dragFrom = event.clientX; dragged = true; }
  });
  addEventListener("pointerup", () => { dragFrom = null; setTimeout(() => { dragged = false; }, 0); });
  $("#lib-prev").addEventListener("click", () => move(-1));
  $("#lib-next").addEventListener("click", () => move(1));
  $("#lib-close").addEventListener("click", () => close());
  $("#lib-add").addEventListener("click", () => openForm(null, { status: shelf === "projects" ? "building" : "idea", topic: shelf === "topic" ? topic.name : "" }));
  root.querySelectorAll("[data-shelf]").forEach((tab) => tab.addEventListener("click", () => setShelf(tab.dataset.shelf)));
  search.addEventListener("input", () => { query = search.value.trim(); index = 0; build(); });

  function handleKey(event) {
    if (!opened) return false;
    if (!form.hidden) { if (event.key === "Escape") { closeForm(); return true; } return false; }
    const typing = /^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement?.tagName || "");
    if (typing) { if (event.key === "Escape" && document.activeElement === search) { search.blur(); clearSearch(); build(); return true; } return false; }
    const keys = { ArrowRight: () => move(1), ArrowLeft: () => move(-1), Enter: enter, Escape: back, Backspace: back,
      Home: () => go(0), End: () => go(cards.length - 1) };
    if (keys[event.key]) { keys[event.key](); return true; }
    if (/^[1-9]$/.test(event.key)) { pick(Number(event.key)); return true; }
    return false;
  }

  // ---------- voice and gestures (Nova sends what was said or shown) ----------
  const SAID = { next: "Next", previous: "Previous", open: "Open", back: "Back", close: "Close" };
  function flash(text, by = "") {
    flashBox.textContent = `${by === "gesture" ? "✋ " : by === "voice" ? "🎙 " : ""}${text}`.toUpperCase();
    flashBox.classList.remove("show"); void flashBox.offsetWidth; flashBox.classList.add("show");
  }

  async function command(event) {
    if (event.command === "show") {
      if (!opened) await open();
      if (event.target) goto(event.target);
      return;
    }
    if (!opened) return;
    const label = SAID[event.command] || (event.command === "shelf" ? SHELVES[event.shelf] : event.command === "pick" ? `Card ${event.number}` : event.name || "");
    flash(label, event.by);
    if (event.command === "next") move(1);
    else if (event.command === "previous") move(-1);
    else if (event.command === "open") enter();
    else if (event.command === "back") back();
    else if (event.command === "close") close();
    else if (event.command === "shelf") setShelf(event.shelf);
    else if (event.command === "pick") pick(event.number);
    else if (event.command === "goto") goto(event);
  }

  // ---------- the moving parts: the orbit rings and the card in front ----------
  let angle = 0, last = performance.now();
  function frame(now) {
    if (!opened) return;
    requestAnimationFrame(frame);
    const elapsed = Math.min(0.1, (now - last) / 1000);
    last = now;
    angle += elapsed * 0.35;
    const color = accent();
    const center = elements[index];
    if (center) drawCloud(center.querySelector(".lib-field"), center.points, angle, color, true);
    drawOrbit(color, now / 1000);
  }

  function drawOrbit(rgb, time) {
    const ratio = Math.min(2, window.devicePixelRatio || 1);
    const width = orbit.clientWidth, height = orbit.clientHeight;
    if (!width || !height) return;
    if (orbit.width !== Math.round(width * ratio)) { orbit.width = Math.round(width * ratio); orbit.height = Math.round(height * ratio); }
    const context = orbit.getContext("2d");
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, width, height);
    const rings = [[height * 0.13, 0.055, 1], [height * 0.88, 0.065, -1]];
    for (const [y, flat, direction] of rings) {
      const radiusX = width * 0.47, radiusY = height * flat;
      for (let dot = 0; dot < 220; dot++) {
        const a = (dot / 220) * Math.PI * 2 + time * 0.08 * direction;
        const front = Math.sin(a);
        context.fillStyle = `rgba(${rgb}, ${0.08 + 0.32 * (front + 1) / 2})`;
        const size = dot % 11 === 0 ? 2.2 : 1.1;
        context.fillRect(width / 2 + Math.cos(a) * radiusX, y + front * radiusY, size, size);
      }
      const marker = time * 0.5 * direction;
      context.strokeStyle = `rgba(${rgb}, 0.7)`;
      context.beginPath();
      context.arc(width / 2 + Math.cos(marker) * radiusX, y + Math.sin(marker) * radiusY, 5, 0, Math.PI * 2);
      context.stroke();
    }
  }

  // ---------- open and close ----------
  async function load() {
    loading = act("library");
    const result = await loading;
    loading = null;
    if (result.ok === false) return;
    data = result;
    if (shelf === "topic" && topic) {
      const inside = await act("library_topic", { name: topic.name });
      if (inside.ok !== false) topic = inside;
    }
    build();
  }

  async function open() {
    if (!opened) {
      opened = true;
      root.hidden = false;
      onOpenChange(true);
      last = performance.now();
      requestAnimationFrame(frame);
    }
    await load();
  }

  function close() {
    if (!opened) return;
    opened = false;
    closeForm();
    root.hidden = true;
    onOpenChange(false);
  }

  addEventListener("resize", () => { if (opened) place(); });
  return { open, close, isOpen: () => opened, command, handleKey, reload: () => (opened ? load() : null) };
}
