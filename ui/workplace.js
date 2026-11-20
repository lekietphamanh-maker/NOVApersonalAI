// The Workplace: a board of notes, sketch notes, pictures and files, with Nova beside it. Nova reads the board with
// every question asked while it's open (workplace_sync) and works on it through workplace_command events: highlight
// words, add her note next to something, point at an item. Closing asks whether to save.
import { h, screen } from "./lab.js";
import { createCore } from "./core.js";
import { createProjector } from "./holo.js";

const MAX_PICTURE = 1600;           // px: pictures are shrunk before they go on the board
const MAX_FILE_BYTES = 15_000_000;
const TEXT_FILES = /\.(txt|md|csv|json|py|js|ts|html|css|log|xml|ya?ml)$/i;
const READ_ON_PC = /\.(pdf|docx)$/i;  // Nova reads these on the PC
const INK = ["#f2f4f7", "#ffb040", "#3be4ff", "#ff3b5c"];
const SYNC_MS = 700;
const LABEL = { note: "Note", sketch: "Sketch", picture: "Picture", file: "File", nova: "Nova" };
const SIZE = { note: [260, 200], sketch: [340, 260], picture: [320, 240], file: [320, 260], nova: [280, 170] };
const HOLO_BLUE = "90, 190, 255";
const highlights = typeof Highlight === "function" && globalThis.CSS?.highlights ? CSS.highlights : null;

export function createWorkplace(root, { act, toast, onOpenChange }) {
  const layer = root.querySelector("#wp-layer"), board = root.querySelector("#wp-board"), links = root.querySelector("#wp-links");
  const nameBox = root.querySelector("#wp-name"), picker = root.querySelector("#wp-picker"), reply = root.querySelector("#wp-reply");
  let items = [], selected = new Set(), dirty = false, view = { x: 0, y: 0, zoom: 1 }, syncTimer = 0;
  const view$ = screen(root, { onOpenChange, onOpen: () => { draw(); sync(); project(items.length > 0); } });

  // The orb starts in the middle; tapped (or as soon as something goes on the board) it drops to the bottom and
  // becomes the projector: the items appear as see-through holograms with a beam of light following each one.
  const orbButton = root.querySelector("#wp-orb");
  let orbCore = null, projecting = false;
  const projector = createProjector(root.querySelector("#wp-beams"), { targets: () => {
    const origin = board.getBoundingClientRect();
    return [...layer.querySelectorAll(".wp-item")].map((element) => {
      const box = element.getBoundingClientRect();
      return { box: { left: box.left - origin.left, right: box.right - origin.left, top: box.top - origin.top, bottom: box.bottom - origin.top },
        selected: element.classList.contains("selected") };
    });
  } });
  function project(on) {
    if (!orbCore) { orbCore = createCore(orbButton.querySelector("canvas"), { widget: true }); orbCore.setAccent(HOLO_BLUE); }
    if (on === projecting) return;
    projecting = on;
    root.classList.toggle("projecting", on);
    orbButton.setAttribute("aria-label", on ? "Turn the projector off" : "Start projecting");
    if (on) { projector.start(); draw(); } else projector.stop();
  }
  orbButton.addEventListener("click", () => project(!projecting));

  const newId = () => Math.random().toString(36).slice(2, 10);
  function changed() { dirty = true; clearTimeout(syncTimer); syncTimer = setTimeout(sync, SYNC_MS); }
  function sync() {
    act("workplace_sync", { open: view$.isOpen(), name: nameBox.value, selected: [...selected],
      items: items.map(({ marks, ...item }) => item) });
  }

  // ---------- items ----------
  function place(kind, near) {
    const [w, h_] = SIZE[kind];
    if (near) return { x: near.x + near.w + 40, y: near.y, w, h: h_ };
    const box = board.getBoundingClientRect(), offset = (items.length % 6) * 28;
    return { x: (box.width / 2 - view.x) / view.zoom - w / 2 + offset, y: (box.height / 2 - view.y) / view.zoom - h_ / 2 + offset, w, h: h_ };
  }
  function add(kind, fields = {}, near = null) {
    if (!projecting) project(true);
    const item = { id: newId(), kind, text: "", name: "", image: "", near: near ? near.id : "", marks: [], ...place(kind, near), ...fields };
    if (near && fields.h === undefined) item.y = Math.max(item.y, lowestBeside(near, item));
    items.push(item);
    layer.append(itemElement(item));  // only the new one: a note being typed in keeps its cursor
    afterChange();
    return item;
  }
  function afterChange() {
    drawLinks();
    paintMarks();
    root.querySelector("#wp-empty").hidden = items.length > 0;
    changed();
  }
  function lowestBeside(near, item) {  // Nova's notes on one item stack downwards instead of on top of each other
    const beside = items.filter((other) => other.near === near.id && other.id !== item.id);
    return beside.length ? Math.max(...beside.map((other) => other.y + other.h + 16)) : item.y;
  }
  function remove(id) {
    items = items.filter((item) => item.id !== id && !(item.kind === "nova" && item.near === id));  // Nova's notes on it go too
    selected.delete(id);
    layer.querySelectorAll(".wp-item").forEach((element) => { if (!items.some((item) => item.id === element.dataset.id)) element.remove(); });
    afterChange();
  }

  function draw() {
    layer.querySelectorAll(".wp-item").forEach((element) => element.remove());
    items.forEach((item, index) => {
      const element = itemElement(item);
      element.style.animationDelay = `${index * 70}ms`;  // they materialise one after another
      layer.append(element);
    });
    drawLinks();
    paintMarks();
    root.querySelector("#wp-empty").hidden = items.length > 0;
  }
  function drawLinks() {
    links.replaceChildren(...items.filter((item) => item.near).map((item) => {
      const target = items.find((other) => other.id === item.near);
      if (!target) return null;
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("x1", target.x + target.w / 2); line.setAttribute("y1", target.y + target.h / 2);
      line.setAttribute("x2", item.x + item.w / 2); line.setAttribute("y2", item.y + item.h / 2);
      return line;
    }).filter(Boolean));
  }
  function setView() { layer.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.zoom})`; }

  function itemElement(item) {
    const element = h("article", { class: `wp-item ${item.kind}${selected.has(item.id) ? " selected" : ""}`, "data-id": item.id,
      style: `left:${item.x}px;top:${item.y}px;width:${item.w}px;height:${item.h}px` },
      h("header", { class: "wp-head" }, h("span", { class: "wp-kind" }, LABEL[item.kind]), h("b", {}, item.name || ""),
        h("button", { type: "button", class: "wp-x", title: "Remove", onclick: (event) => { event.stopPropagation(); remove(item.id); } }, "✕")),
      body(item),
      h("span", { class: "wp-resize", "aria-hidden": "true" }));
    element.addEventListener("pointerdown", (event) => pick(event, item), true);
    drag(element.querySelector(".wp-head"), item, element, false);
    drag(element.querySelector(".wp-resize"), item, element, true);
    return element;
  }

  function body(item) {
    if (item.kind === "note" || item.kind === "nova") {
      const text = h("div", { class: "wp-text", contenteditable: "plaintext-only", spellcheck: "true", "data-placeholder": "Write here…" });
      text.textContent = item.text;
      text.addEventListener("input", () => { item.text = text.innerText; changed(); paintMarks(); });
      return text;
    }
    if (item.kind === "picture") return h("div", { class: "wp-picture" }, h("img", { src: item.image, alt: item.name || "Picture", draggable: "false" }));
    if (item.kind === "file") {
      const text = h("pre", { class: "wp-text wp-file" });
      text.textContent = item.text || "Nova can't read this kind of file yet; it stays on the board.";
      return text;
    }
    return sketch(item);
  }

  function sketch(item) {
    const canvas = h("canvas", { class: "wp-canvas" });
    let ink = INK[0], eraser = false;
    const tools = h("div", { class: "wp-ink" },
      ...INK.map((color, index) => h("button", { type: "button", class: index ? "" : "on", style: `background:${color}`, title: "Pen",
        onclick: (event) => { ink = color; eraser = false; mark(event.target); } })),
      h("button", { type: "button", class: "wp-eraser", title: "Eraser", onclick: (event) => { eraser = true; mark(event.target); } }, "⌫"),
      h("button", { type: "button", title: "Clear the sketch", onclick: () => { context().clearRect(0, 0, canvas.width, canvas.height); save(); } }, "Clear"));
    const mark = (button) => tools.querySelectorAll("button").forEach((other) => other.classList.toggle("on", other === button));
    const context = () => canvas.getContext("2d");
    const save = () => { item.image = canvas.toDataURL("image/png"); changed(); };
    requestAnimationFrame(() => {  // sized once it's on the page: its pixels match the screen
      // Layout size, not the on-screen box: the hologram is still unfolding (scaled) when this runs.
      canvas.width = Math.max(1, Math.round(canvas.offsetWidth * devicePixelRatio));
      canvas.height = Math.max(1, Math.round(canvas.offsetHeight * devicePixelRatio));
      if (item.image) {
        const picture = new Image();
        picture.onload = () => context().drawImage(picture, 0, 0, canvas.width, canvas.height);
        picture.src = item.image;
      }
    });
    let last = null;
    const at = (event) => {
      const box = canvas.getBoundingClientRect();
      return [(event.clientX - box.left) * canvas.width / box.width, (event.clientY - box.top) * canvas.height / box.height];
    };
    canvas.addEventListener("pointerdown", (event) => { event.stopPropagation(); canvas.setPointerCapture(event.pointerId); last = at(event); });
    canvas.addEventListener("pointermove", (event) => {
      if (!last) return;
      const point = at(event), pen = context();
      pen.globalCompositeOperation = eraser ? "destination-out" : "source-over";
      pen.strokeStyle = ink;
      pen.lineWidth = (eraser ? 18 : 3) * devicePixelRatio * (event.pressure > 0 && event.pointerType === "pen" ? event.pressure * 1.6 : 1);
      pen.lineCap = pen.lineJoin = "round";
      pen.beginPath(); pen.moveTo(...last); pen.lineTo(...point); pen.stroke();
      last = point;
    });
    const end = () => { if (last) { last = null; save(); } };
    canvas.addEventListener("pointerup", end);
    canvas.addEventListener("pointercancel", end);
    return h("div", { class: "wp-sketch" }, canvas, tools);
  }

  function pick(event, item) {
    if (event.target.closest(".wp-x, .wp-resize, .wp-ink")) return;
    if (event.shiftKey || event.ctrlKey) { selected.has(item.id) ? selected.delete(item.id) : selected.add(item.id); }
    else if (!selected.has(item.id)) { selected = new Set([item.id]); }
    layer.querySelectorAll(".wp-item").forEach((element) => element.classList.toggle("selected", selected.has(element.dataset.id)));
    clearTimeout(syncTimer); syncTimer = setTimeout(sync, 150);  // "explain this" means what's selected now
  }

  function drag(handle, item, element, resize) {
    handle.addEventListener("pointerdown", (event) => {
      if (event.target.closest("button")) return;
      event.preventDefault();
      event.stopPropagation();
      handle.setPointerCapture(event.pointerId);
      const start = { x: event.clientX, y: event.clientY, item: { ...item } };
      const move = (moved) => {
        const dx = (moved.clientX - start.x) / view.zoom, dy = (moved.clientY - start.y) / view.zoom;
        if (resize) { item.w = Math.max(120, start.item.w + dx); item.h = Math.max(90, start.item.h + dy); }
        else { item.x = start.item.x + dx; item.y = start.item.y + dy; }
        Object.assign(element.style, { left: `${item.x}px`, top: `${item.y}px`, width: `${item.w}px`, height: `${item.h}px` });
        drawLinks();
      };
      const up = () => { handle.removeEventListener("pointermove", move); handle.removeEventListener("pointerup", up); changed(); if (resize && item.kind === "sketch") element.replaceWith(itemElement(item)); };
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", up);
    });
  }

  // Pan with a drag on empty board, zoom with the wheel (towards the pointer).
  board.addEventListener("pointerdown", (event) => {
    if (event.target !== board && event.target !== layer && event.target !== links) return;
    selected.clear();
    layer.querySelectorAll(".wp-item.selected").forEach((element) => element.classList.remove("selected"));
    const start = { x: event.clientX - view.x, y: event.clientY - view.y };
    board.setPointerCapture(event.pointerId);
    const move = (moved) => { view.x = moved.clientX - start.x; view.y = moved.clientY - start.y; setView(); };
    const up = () => { board.removeEventListener("pointermove", move); board.removeEventListener("pointerup", up); sync(); };
    board.addEventListener("pointermove", move);
    board.addEventListener("pointerup", up);
  });
  board.addEventListener("wheel", (event) => {
    event.preventDefault();
    const box = board.getBoundingClientRect(), zoom = Math.min(2.5, Math.max(0.3, view.zoom * (event.deltaY < 0 ? 1.1 : 0.9)));
    const px = event.clientX - box.left, py = event.clientY - box.top;
    view.x = px - (px - view.x) * zoom / view.zoom; view.y = py - (py - view.y) * zoom / view.zoom; view.zoom = zoom;
    setView();
  }, { passive: false });

  // ---------- Nova's highlights: the CSS Highlight API marks words without changing what was typed ----------
  function textRange(container, phrase) {
    const nodes = [], walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
    let all = "";
    while (walker.nextNode()) { nodes.push([walker.currentNode, all.length]); all += walker.currentNode.data; }
    const pattern = new RegExp(phrase.trim().split(/\s+/).map((word) => word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("\\s+"), "i");
    const found = pattern.exec(all);
    if (!found) return null;
    const locate = (offset) => { const [node, from] = nodes.findLast(([, start]) => start <= offset) || nodes[0]; return [node, offset - from]; };
    const range = document.createRange();
    range.setStart(...locate(found.index));
    range.setEnd(...locate(found.index + found[0].length));
    return range;
  }
  function paintMarks() {
    if (!highlights) return;
    const ranges = [];
    for (const item of items) {
      const text = layer.querySelector(`[data-id="${item.id}"] .wp-text`);
      for (const mark of (text && item.marks) || []) { const range = textRange(text, mark.text); if (range) ranges.push(range); }
    }
    highlights.set("nova-mark", new Highlight(...ranges));
  }

  function point(item, note) {
    const element = layer.querySelector(`[data-id="${item.id}"]`);
    if (!element) return;
    const box = board.getBoundingClientRect();  // bring it into view
    if (item.x * view.zoom + view.x < 0 || item.x * view.zoom + view.x > box.width - 80 || item.y * view.zoom + view.y < 0 || item.y * view.zoom + view.y > box.height - 80) {
      view.x = box.width / 2 - (item.x + item.w / 2) * view.zoom; view.y = box.height / 2 - (item.y + item.h / 2) * view.zoom; setView();
    }
    element.classList.remove("pulse"); void element.offsetWidth; element.classList.add("pulse");
    layer.querySelector(`.wp-say[data-for="${item.id}"]`)?.remove();
    if (note) {
      const label = h("div", { class: "wp-say", "data-for": item.id, style: `left:${item.x}px;top:${item.y - 36}px` }, note);
      layer.append(label);
      setTimeout(() => label.remove(), 4000);
    }
    setTimeout(() => element.classList.remove("pulse"), 4000);
  }

  function command(event) {
    if (event.command === "open") { if (!view$.isOpen()) view$.open(); return; }
    if (event.command === "close") { if (view$.isOpen()) requestClose(); return; }
    if (!view$.isOpen()) return;
    const item = items.find((candidate) => candidate.id === event.item || candidate.id === event.near);
    if (event.command === "add_note") point(add("nova", { text: event.text }, item || null), "");
    else if (event.command === "highlight" && item) {
      item.marks = [...(item.marks || []).filter((mark) => mark.text !== event.text), { text: event.text, note: event.note }];
      paintMarks();
      if (event.note) add("nova", { text: `“${event.text}”: ${event.note}` }, item);
      point(item, "");
    } else if (event.command === "point" && item) point(item, event.note);
  }

  // ---------- adding pictures and files ----------
  async function shrink(file) {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, MAX_PICTURE / Math.max(bitmap.width, bitmap.height));
    const canvas = h("canvas", { width: Math.round(bitmap.width * scale), height: Math.round(bitmap.height * scale) });
    canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    return { image: canvas.toDataURL("image/jpeg", 0.86), ratio: bitmap.height / bitmap.width };
  }
  async function addFile(file) {
    if (file.type.startsWith("image/")) {
      const { image, ratio } = await shrink(file);
      add("picture", { image, name: file.name || "Pasted picture", h: Math.round(SIZE.picture[0] * ratio) + 30 });
      return;
    }
    if (file.size > MAX_FILE_BYTES) { toast(`${file.name} is too big for the board (15 MB at most).`, "warn"); return; }
    let text = "";
    if (TEXT_FILES.test(file.name)) text = (await file.text()).slice(0, 60_000);
    else if (READ_ON_PC.test(file.name)) {
      const bytes = new Uint8Array(await file.arrayBuffer());
      let binary = "";
      for (let index = 0; index < bytes.length; index += 0x8000) binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000));
      const answer = await act("workplace_file", { name: file.name, data: btoa(binary) });
      text = answer.ok ? answer.text : "";
    }
    add("file", { name: file.name, text });
  }
  picker.addEventListener("change", async () => { for (const file of picker.files) await addFile(file); picker.value = ""; });
  board.addEventListener("dragover", (event) => { event.preventDefault(); board.classList.add("dropping"); });
  board.addEventListener("dragleave", () => board.classList.remove("dropping"));
  board.addEventListener("drop", async (event) => {
    event.preventDefault();
    board.classList.remove("dropping");
    for (const file of event.dataTransfer.files) await addFile(file);
  });
  document.addEventListener("paste", async (event) => {
    if (!view$.isOpen() || document.activeElement?.isContentEditable || /^(INPUT|TEXTAREA)$/.test(document.activeElement?.tagName || "")) return;
    const files = [...event.clipboardData.files];
    if (files.length) { event.preventDefault(); for (const file of files) await addFile(file); }
    else if (event.clipboardData.getData("text")) { event.preventDefault(); add("note", { text: event.clipboardData.getData("text").slice(0, 20_000) }); }
  });

  // ---------- saving, opening, closing ----------
  async function save() {
    const answer = await act("workplace_save", { name: nameBox.value, items: items.map(({ marks, ...item }) => item) });
    if (!answer.ok) return false;
    nameBox.value = answer.name;
    dirty = false;
    listSaved(answer.saved);
    toast(`Saved “${answer.name}”.`, "ok");
    return true;
  }
  function listSaved(saved) {
    root.querySelector("#wp-saved").replaceChildren(...(saved.length ? saved.map((entry) => h("li", {},
      h("button", { type: "button", onclick: () => load(entry.name) }, h("b", {}, entry.name), h("small", {}, entry.saved)),
      h("button", { type: "button", class: "wp-x", title: "Delete", onclick: async () => listSaved((await act("workplace_delete", { name: entry.name })).saved || []) }, "✕")))
      : [h("li", { class: "muted small" }, "Nothing saved yet.")]));
  }
  async function load(name) {
    if (dirty && items.length && !(await ask(`Open “${name}”? This board isn't saved.`, ["Save first", "save"], ["Don't save", "drop"]))) return;
    const answer = await act("workplace_load", { name });
    if (!answer.ok) return;
    items = answer.items.map((item) => ({ marks: [], ...item }));
    nameBox.value = answer.name;
    selected.clear();
    view = { x: 0, y: 0, zoom: 1 }; setView();
    dirty = false;
    root.querySelector("#wp-open").open = false;
    if (projecting) draw(); else project(true);
    sync();
  }
  function ask(question, ...choices) {  // the board's own question: Save / Don't save / Cancel
    const dialog = root.querySelector("#wp-dialog");
    dialog.querySelector("p").textContent = question;
    return new Promise((resolve) => {
      const finish = async (choice) => {
        dialog.hidden = true;
        if (choice === "save") resolve(await save());
        else resolve(choice === "drop");
      };
      dialog.querySelector(".wp-choices").replaceChildren(
        ...choices.map(([label, choice], index) => h("button", { type: "button", class: `box small${index ? "" : " on"}`, onclick: () => finish(choice) }, label)),
        h("button", { type: "button", class: "box small", onclick: () => finish("cancel") }, "Cancel"));
      dialog.hidden = false;
      dialog.querySelector("button").focus();
    });
  }
  async function requestClose() {
    if (dirty && items.length && !(await ask("Save this workplace before closing?", ["Save", "save"], ["Don't save", "drop"]))) return;
    items = []; selected.clear(); dirty = false; nameBox.value = ""; reply.hidden = true;
    project(false);
    view$.close();
    act("workplace_sync", { open: false });
  }

  root.querySelectorAll("[data-add]").forEach((button) => button.addEventListener("click", () => {
    const kind = button.dataset.add;
    if (kind === "picture" || kind === "file") { picker.accept = kind === "picture" ? "image/*" : ""; picker.click(); return; }
    const item = add(kind);
    requestAnimationFrame(() => layer.querySelector(`[data-id="${item.id}"] .wp-text`)?.focus());
  }));
  root.querySelector("#wp-save").onclick = save;
  root.querySelector("#wp-close").onclick = requestClose;
  root.querySelector("#wp-clear-marks").onclick = () => { items.forEach((item) => { item.marks = []; }); items = items.filter((item) => item.kind !== "nova"); changed(); draw(); };
  root.querySelector("#wp-open").addEventListener("toggle", async (event) => { if (event.target.open) listSaved((await act("workplace_list")).saved || []); });
  nameBox.addEventListener("input", changed);
  root.querySelector("#wp-ask").addEventListener("submit", (event) => {
    event.preventDefault();
    const box = root.querySelector("#wp-question"), text = box.value.trim();
    if (!text) return;
    clearTimeout(syncTimer);
    sync();  // the board as it is now goes with the question
    act("send", { text });
    box.value = "";
    showReply("…");
  });
  function showReply(text) { reply.hidden = false; reply.textContent = text; }

  return {
    open: () => view$.open(),
    close: requestClose,
    isOpen: view$.isOpen,
    command,
    showReply,
    setMood(mode, level = 0) { orbCore?.setMode(mode); projector.setMood(mode, level); },
    handleKey(event) {
      const editing = document.activeElement?.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "");
      if (event.key === "Escape") { if (!root.querySelector("#wp-dialog").hidden) return false; if (editing) { document.activeElement.blur(); return true; } requestClose(); return true; }
      if (editing) return false;
      if ((event.key === "Delete" || event.key === "Backspace") && selected.size) { [...selected].forEach(remove); return true; }
      if (event.key.toLowerCase() === "s" && (event.ctrlKey || event.metaKey)) { save(); return true; }
      return false;
    },
  };
}
