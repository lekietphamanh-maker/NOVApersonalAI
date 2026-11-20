// Nova's brainstorm map: the topic in a glowing core, ideas around it on curved links with pulses travelling
// out, sub-ideas branching further, faint circuit lines behind. You edit it by hand: drag nodes, drop one on
// another to make it a sub-idea, double-click to add or rename, keys and undo. Drawn only while on screen.

const TAU = Math.PI * 2;
const COOL = [104, 186, 255];
export const LIMITS = { roots: 30, children: 12, depth: 4 };
/** Colours you can give an idea (its sub-ideas take it too, unless they have their own). */
export const PALETTE = { gold: [255, 176, 64], orange: [255, 122, 40], red: [255, 70, 85], pink: [255, 105, 190],
  violet: [168, 128, 255], blue: [104, 186, 255], cyan: [60, 228, 255], green: [80, 235, 150] };
export const ICONS = ["💡", "⭐", "✅", "❓", "⚠️", "🔥", "🎯", "📌", "💰", "🧪"];

// ---------- the tree (pure functions, tested in Node) ----------

/** Outline → tree. One idea per line; indent (2 spaces a level) or "A > B > C" for sub-ideas. */
export function parseOutline(outline) {
  const roots = [];
  let stack = [];
  String(outline).split("\n").forEach((raw, line) => {
    if (!raw.trim()) return;
    const indent = raw.match(/^[\t ]*/)[0].replace(/\t/g, "  ").length;
    const text = raw.replace(/^\s*(?:[-*•]|\d+[.)])\s*/, "").trim();
    const parts = text.split(">").map((part) => part.trim()).filter(Boolean);
    if (!parts.length) return;
    if (parts.length > 1) {
      let siblings = roots;
      stack = [];
      parts.forEach((label, depth) => {
        let node = siblings.find((candidate) => candidate.label.toLowerCase() === label.toLowerCase());
        if (!node) { node = { label, line, children: [] }; siblings.push(node); }
        if (depth === parts.length - 1) node.line = line;
        stack.push(node);
        siblings = node.children;
      });
      return;
    }
    const level = Math.min(Math.floor(indent / 2), stack.length);
    const node = { label: text, line, children: [] };
    (level === 0 ? roots : stack[level - 1].children).push(node);
    stack = [...stack.slice(0, level), node];
  });
  return limit(roots, 0);
}

function limit(list, depth) {
  const kept = list.slice(0, depth === 0 ? LIMITS.roots : LIMITS.children);
  kept.forEach((node) => { node.children = depth + 1 >= LIMITS.depth ? [] : limit(node.children, depth + 1); });
  return kept;
}

/** Tree → outline (two spaces per level). Also records each node's line, for the editor. */
export function serialize(roots) {
  const lines = [];
  const walk = (node, depth) => {
    node.line = lines.length;
    lines.push("  ".repeat(depth) + node.label);
    node.children.forEach((child) => walk(child, depth + 1));
  };
  roots.forEach((root) => walk(root, 0));
  return lines.join("\n");
}

/** Each node's path ("idea > sub-idea"), unique even for repeated names; used to save positions. */
export function pathsOf(roots) {
  const paths = new Map(), used = new Set();
  const walk = (node, prefix) => {
    let path = (prefix ? prefix + " > " : "") + node.label.toLowerCase();
    for (let n = 2; used.has(path); n++) path = `${path.replace(/ #\d+$/, "")} #${n}`;
    used.add(path);
    paths.set(node, path);
    node.children.forEach((child) => walk(child, path));
  };
  roots.forEach((root) => walk(root, ""));
  return paths;
}

export function parentOf(roots, target) {
  const find = (list, parent) => {
    for (const node of list) {
      if (node === target) return { parent, siblings: list };
      const found = find(node.children, node);
      if (found) return found;
    }
    return null;
  };
  return find(roots, null);
}

export const contains = (node, other) => node === other || node.children.some((child) => contains(child, other));

export function removeNode(roots, node) {
  const place = parentOf(roots, node);
  if (place) place.siblings.splice(place.siblings.indexOf(node), 1);
}

/** Move a node (with its sub-ideas) under another node, or to the top level when parent is null. */
export function moveNode(roots, node, parent) {
  if (parent && contains(node, parent)) return false; // not into itself
  removeNode(roots, node);
  (parent ? parent.children : roots).push(node);
  return true;
}

/** Text typed or pasted into the map: one idea per line (or separated by ";"); "A > B" puts B under A. */
export function typedIdeas(text) {
  return String(text).split(/\n|;/).map((line) => line.replace(/^\s*(?:[-*•]|\d+[.)])\s*/, "").trim()).filter(Boolean)
    .map((line) => line.split(">").map((part) => part.trim().slice(0, 80)).filter(Boolean)).filter((parts) => parts.length);
}

// ---------- drawing and editing ----------

function seeded(seed) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let value = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    value = (value + Math.imul(value ^ (value >>> 7), 61 | value)) ^ value;
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
}

export function createMindMap(canvas, { onSelect = () => {}, onChange = () => {}, onExpand = () => {} } = {}) {
  const context = canvas.getContext("2d");
  const host = canvas.parentElement;
  const random = seeded(5);
  const particles = Array.from({ length: 360 }, () => ({ r: Math.sqrt(random()), a: random() * TAU, speed: 0.2 + random() * 0.6, size: 0.6 + random() * 1.2 }));
  const circuits = Array.from({ length: 22 }, () => {
    const fromLeft = random() < 0.5, y = random(), steps = [];
    let x = 0, yy = y;
    while (x < 0.42) { const run = 0.04 + random() * 0.12; steps.push([x, yy], [x + run, yy]); x += run; yy += (random() - 0.5) * 0.05; }
    return { fromLeft, steps, alpha: 0.05 + random() * 0.1 };
  });

  let title = "Idea", roots = [], accent = [255, 176, 64], visible = false, last = performance.now();
  let items = [], frameBox = { cx: 0, cy: 0, rx: 1, ry: 1, orbRadius: 50, width: 0, height: 0 };
  let selected = null, hovered = null, dropTarget = null, pressed = null, mouse = null;
  let zoom = 1, panX = 0, panY = 0, expanding = null;
  let links = [], linking = null; // links: [{ a: node, b: node }]; linking: the idea a new link starts from
  const undoStack = [], redoStack = [];

  // An inline text box for naming nodes, and a small action bar next to the selected node.
  const input = Object.assign(document.createElement("input"), { className: "map-input", hidden: true, maxLength: 80 });
  const actions = document.createElement("div");
  actions.className = "map-actions";
  actions.hidden = true;
  const actionButton = (label, title_, run) => {
    const button = Object.assign(document.createElement("button"), { className: "box small", textContent: label, title: title_ });
    button.addEventListener("pointerdown", (event) => event.stopPropagation());
    button.addEventListener("click", (event) => { event.stopPropagation(); run(); });
    return button;
  };
  actions.append(actionButton("✦ Ask Nova", "Nova adds sub-ideas about this", () => selected && onExpand(pathTo(selected.node))),
    actionButton("+ Sub-idea", "Tab", () => addNode(selected?.node || null)),
    actionButton("🔗 Link", "L: then click another idea (again to remove the link)", () => startLink()),
    actionButton("Rename", "F2 or double-click", () => selected && beginRename(selected.node)),
    actionButton("Delete", "Del", () => selected && deleteNode(selected.node)));
  host.append(input, actions);
  let editing = null; // { node, isNew } or { title: true }

  const rgba = ([r, g, b], alpha) => `rgba(${r}, ${g}, ${b}, ${Math.max(0, Math.min(1, alpha))})`;

  // ---- state in and out ----
  function snapshot() {
    const paths = pathsOf(roots), positions = {}, details = {}, styles = {};
    paths.forEach((path, node) => {
      if (node.pos) positions[path] = node.pos.map((value) => Math.round(value * 1000) / 1000);
      if (node.note && node.note.trim()) details[path] = node.note;
      if (node.color || node.icon) styles[path] = { ...(node.color && { color: node.color }), ...(node.icon && { icon: node.icon }) };
    });
    links = links.filter((link) => paths.has(link.a) && paths.has(link.b)); // ideas deleted since
    return { title, outline: serialize(roots), positions, details, styles,
      links: links.map((link) => (link.label ? [paths.get(link.a), paths.get(link.b), link.label] : [paths.get(link.a), paths.get(link.b)])) };
  }

  function load({ title: newTitle, outline, positions = {}, details = {}, styles = {}, links: savedLinks = [] }, keepPositions = false) {
    const before = keepPositions ? snapshot() : { positions: {}, details: {}, styles: {}, links: [] };
    const previous = before.positions;
    title = String(newTitle || "Idea");
    roots = parseOutline(outline || "");
    const byPath = new Map();
    pathsOf(roots).forEach((path, node) => {
      byPath.set(path, node);
      const pos = positions[path] || previous[path];
      if (Array.isArray(pos) && pos.length === 2) node.pos = pos.map(Number);
      const note = details[path] ?? before.details[path];
      if (typeof note === "string") node.note = note;
      const style = styles[path] || before.styles[path] || {};
      if (PALETTE[style.color]) node.color = style.color;
      if (typeof style.icon === "string" && style.icon) node.icon = style.icon;
    });
    links = [...savedLinks, ...before.links].map(([a, b, label]) => ({ a: byPath.get(a), b: byPath.get(b), label: typeof label === "string" ? label : "" }))
      .filter((link, index, all) => link.a && link.b && link.a !== link.b
        && all.findIndex((other) => samePair(other, link)) === index);
    linking = null;
    serialize(roots); // number the lines as the editor shows them
    if (selected && !items.some((item) => item.node === selected.node)) selected = null;
  }

  const samePair = (one, two) => (one.a === two.a && one.b === two.b) || (one.a === two.b && one.b === two.a);

  function startLink() {
    if (selected) linking = selected.node;
  }

  /** Link two ideas, or remove the link when they already have one. */
  function toggleLink(a, b) {
    if (a === b) return;
    remember();
    const existing = links.findIndex((link) => samePair(link, { a, b }));
    let added = null;
    if (existing >= 0) links.splice(existing, 1);
    else links.push(added = { a, b, label: "" });
    commit();
    if (added) beginLinkLabel(added); // name it, or Enter / Esc to leave it unnamed
    if (selected) onSelect(selected.node.line, infoOf(selected.node)); // the note card shows the new link count
  }

  function commit() {
    redoStack.length = 0;
    onChange(snapshot());
  }

  function remember() {
    undoStack.push(JSON.stringify(snapshot()));
    if (undoStack.length > 60) undoStack.shift();
  }

  // ---- layout: auto positions unless the user placed a node (pos is relative to its parent, in rx/ry units) ----
  function layout(width, height) {
    items = [];
    const cx = width / 2, cy = height / 2;
    const rx = Math.max(60, Math.min(width * 0.27, 440, (width / 2 - 160) / 1.55));
    const ry = Math.max(50, Math.min(height * 0.3, 250, (height / 2 - 50) / 1.55));
    const orbRadius = Math.max(42, Math.min(86, Math.min(width, height) * 0.11));
    frameBox = { cx, cy, rx, ry, orbRadius, width, height };
    const place = (node, parentItem, index, siblings, color, depth) => {
      let x, y, angle;
      color = PALETTE[node.color] || color;
      if (!parentItem) {
        angle = -Math.PI / 2 + ((index + 0.5) / siblings) * TAU;
        const ring = siblings > 12 && index % 2 ? 1.22 : 1;
        [x, y] = node.pos ? [cx + node.pos[0] * rx, cy + node.pos[1] * ry] : [cx + Math.cos(angle) * rx * ring, cy + Math.sin(angle) * ry * ring];
        if (node.pos) angle = Math.atan2(y - cy, x - cx);
      } else {
        const outward = Math.atan2(parentItem.y - cy, parentItem.x - cx);
        // Fan out to the sides: straight outward is where the parent's own label runs.
        const spread = Math.max(1.0, Math.min(1.7, 0.42 * siblings));
        let offset = siblings === 1 ? 0.62 : (index / (siblings - 1) - 0.5) * spread;
        if (Math.abs(offset) < 0.45) offset = (offset < 0 ? -1 : 1) * 0.45;
        angle = outward + offset;
        const distance = (depth === 1 ? 0.48 : 0.36) + (index % 2) * 0.08;
        [x, y] = node.pos ? [parentItem.x + node.pos[0] * rx, parentItem.y + node.pos[1] * ry]
          : [parentItem.x + Math.cos(angle) * rx * distance, parentItem.y + Math.sin(angle) * ry * distance];
        if (node.pos) angle = Math.atan2(y - parentItem.y, x - parentItem.x);
      }
      const item = { node, x, y, angle, color, depth, parent: parentItem, size: depth === 0 ? 10 : depth === 1 ? 6.5 : 5,
        seed: items.length * 1.37, auto: !node.pos };
      items.push(item);
      node.children.forEach((child, childIndex) => place(child, item, childIndex, node.children.length, color, depth + 1));
    };
    roots.forEach((root, index) => place(root, null, index, roots.length, index % 3 === 1 ? accent : COOL, 0));
    // Nudge auto-placed sub-ideas apart when they, or their labels, land on each other. Labels run sideways,
    // so the push is vertical; ideas you placed yourself never move.
    const box = (item) => {
      const label = labelPlace(item);
      const width = (Math.min(item.node.label.length, 34) + (item.node.icon ? 3 : 0)) * (item.depth ? 6.4 : 8.2) + 6;
      const left = label.align === "right" ? label.x - width : label.align === "center" ? label.x - width / 2 : label.x;
      return { left: Math.min(left, item.x - item.size), right: Math.max(left + width, item.x + item.size) };
    };
    for (let pass = 0; pass < 6; pass++) {
      const boxes = items.map(box);
      for (let i = 0; i < items.length; i++) {
        for (let j = i + 1; j < items.length; j++) {
          const a = items[i], b = items[j];
          const movable = (a.auto && a.parent) || (b.auto && b.parent);
          const dy = b.y - a.y, gap = a.depth && b.depth ? 18 : 24;
          if (!movable || Math.abs(dy) >= gap || boxes[i].right < boxes[j].left || boxes[j].right < boxes[i].left) continue;
          const push = (gap - Math.abs(dy)) * (dy < 0 ? -1 : 1);
          if (a.auto && a.parent && b.auto && b.parent) { a.y -= push / 2; b.y += push / 2; }
          else if (a.auto && a.parent) a.y -= push;
          else b.y += push;
        }
      }
    }
  }

  // ---- view (zoom and pan) ----
  const toWorld = (sx, sy) => [(sx - panX - frameBox.cx * (1 - zoom)) / zoom, (sy - panY - frameBox.cy * (1 - zoom)) / zoom];
  const toScreen = (x, y) => [x * zoom + frameBox.cx * (1 - zoom) + panX, y * zoom + frameBox.cy * (1 - zoom) + panY];

  function hit(x, y, except = null) {
    let best = null, bestDistance = Infinity;
    for (const item of items) {
      if (except && contains(except, item.node)) continue;
      const distance = Math.hypot(x - item.x, y - item.y);
      if (distance < item.size + 12 && distance < bestDistance) { best = item; bestDistance = distance; }
    }
    if (best) return best;
    return Math.hypot(x - frameBox.cx, y - frameBox.cy) < frameBox.orbRadius ? "core" : null;
  }

  function resize() {
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const { width, height } = canvas.getBoundingClientRect();
    if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
    }
    return { width, height, ratio };
  }

  function curve(x1, y1, x2, y2, bend) {
    const mx = (x1 + x2) / 2, my = (y1 + y2) / 2, dx = x2 - x1, dy = y2 - y1;
    const cx = mx - dy * bend, cy = my + dx * bend;
    context.moveTo(x1, y1);
    context.quadraticCurveTo(cx, cy, x2, y2);
    return (p) => [(1 - p) ** 2 * x1 + 2 * (1 - p) * p * cx + p * p * x2, (1 - p) ** 2 * y1 + 2 * (1 - p) * p * cy + p * p * y2];
  }

  // ---- drawing ----
  function frame(now) {
    if (!visible) return;
    const seconds = Math.min(0.05, (now - last) / 1000);
    last = now;
    const t = now / 1000;
    const { width, height, ratio } = resize();
    if (width < 2 || height < 2) { requestAnimationFrame(frame); return; }
    layout(width, height);
    // The layout made new items: point selection, hover and drop target at the new ones.
    const fresh = (item) => (item && item !== "core" ? items.find((candidate) => candidate.node === item.node) || null : item);
    selected = fresh(selected);
    hovered = fresh(hovered);
    dropTarget = fresh(dropTarget);
    const { cx, cy, orbRadius } = frameBox;
    const dragging = pressed && pressed.dragging ? pressed.item : null;
    for (const item of items) { // a gentle float, still while you hold something
      if (dragging || editing) continue;
      item.x += Math.sin(t * 0.8 + item.seed * 3) * 2.5;
      item.y += Math.cos(t * 0.7 + item.seed * 2) * 2.5;
    }

    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, width, height);
    context.lineWidth = 1;
    for (const line of circuits) { // circuit lines behind, fixed to the screen
      context.beginPath();
      line.steps.forEach(([x, y], index) => {
        const px = (line.fromLeft ? x : 1 - x) * width, py = y * height;
        index ? context.lineTo(px, py) : context.moveTo(px, py);
      });
      context.strokeStyle = rgba(COOL, line.alpha);
      context.stroke();
    }

    context.setTransform(ratio * zoom, 0, 0, ratio * zoom, ratio * (cx * (1 - zoom) + panX), ratio * (cy * (1 - zoom) + panY));
    for (const item of items) { // each main idea reaches toward the edge
      if (item.parent) continue;
      const outward = item.x < cx ? -1 : 1;
      context.beginPath();
      context.moveTo(item.x, item.y);
      context.lineTo(item.x + outward * 40, item.y);
      context.lineTo(item.x + outward * 56, item.y + 10);
      context.lineTo(item.x + outward * 260, item.y + 10);
      context.strokeStyle = rgba(item.color, 0.14);
      context.stroke();
    }

    context.globalCompositeOperation = "lighter";
    items.forEach((item, index) => {
      const fromX = item.parent ? item.parent.x : cx + Math.cos(Math.atan2(item.y - cy, item.x - cx)) * orbRadius;
      const fromY = item.parent ? item.parent.y : cy + Math.sin(Math.atan2(item.y - cy, item.x - cx)) * orbRadius;
      context.beginPath();
      const at = curve(fromX, fromY, item.x, item.y, item.parent ? 0.08 : 0.12 * (index % 2 ? 1 : -1));
      const active = hovered === item || hovered === item.parent || selected === item;
      context.lineWidth = item.parent ? 1 : 1.4;
      context.strokeStyle = rgba(item.color, active ? 0.75 : item.parent ? 0.28 : 0.4);
      context.stroke();
      const progress = (t * 0.22 + index * 0.137) % 1;
      const [px, py] = at(progress);
      const pulse = context.createRadialGradient(px, py, 0, px, py, 7);
      pulse.addColorStop(0, rgba(item.color, 0.9 * Math.sin(progress * Math.PI)));
      pulse.addColorStop(1, rgba(item.color, 0));
      context.fillStyle = pulse;
      context.fillRect(px - 7, py - 7, 14, 14);
    });

    context.globalCompositeOperation = "source-over";
    const itemOf = new Map(items.map((item) => [item.node, item]));
    context.setLineDash([6, 5]);
    for (const link of links) { // cross-links: dashed arcs with a diamond in the middle
      const a = itemOf.get(link.a), b = itemOf.get(link.b);
      if (!a || !b) continue;
      const lit = selected && (selected.node === link.a || selected.node === link.b);
      context.beginPath();
      const at = curve(a.x, a.y, b.x, b.y, 0.22);
      context.lineWidth = lit ? 1.8 : 1.3;
      context.lineDashOffset = -t * 12;
      context.strokeStyle = rgba(accent, lit ? 0.9 : 0.5);
      context.stroke();
      const [mx, my] = at(0.5);
      link.mid = [mx, my];
      if (link.label && !(editing && editing.link === link)) {
        context.save();
        context.setLineDash([]);
        context.font = `500 11px "Segoe UI Variable Text", "Segoe UI", sans-serif`;
        context.textAlign = "center";
        context.textBaseline = "bottom";
        context.shadowColor = "rgba(0, 0, 0, 0.9)";
        context.shadowBlur = 5;
        context.fillStyle = rgba(accent, lit ? 1 : 0.85);
        context.fillText(link.label, mx, my - 7);
        context.restore();
      }
      context.save();
      context.setLineDash([]);
      context.translate(mx, my);
      context.rotate(Math.PI / 4);
      context.fillStyle = rgba(accent, lit ? 1 : 0.75);
      context.fillRect(-3, -3, 6, 6);
      context.restore();
    }
    const linkFrom = linking && itemOf.get(linking);
    if (linkFrom && mouse) { // the link you are drawing follows the mouse
      context.beginPath();
      context.moveTo(linkFrom.x, linkFrom.y);
      context.lineTo(mouse.x, mouse.y);
      context.lineWidth = 1.5;
      context.strokeStyle = rgba(accent, 0.9);
      context.stroke();
    }
    context.setLineDash([]);
    context.lineDashOffset = 0;
    context.globalCompositeOperation = "lighter";

    const halo = context.createRadialGradient(cx, cy, orbRadius * 0.6, cx, cy, orbRadius * 2.4);
    halo.addColorStop(0, rgba(COOL, dropTarget === "core" ? 0.4 : 0.22));
    halo.addColorStop(1, rgba(COOL, 0));
    context.fillStyle = halo;
    context.fillRect(cx - orbRadius * 2.4, cy - orbRadius * 2.4, orbRadius * 4.8, orbRadius * 4.8);
    for (const particle of particles) {
      particle.a += seconds * particle.speed * (1.2 - particle.r);
      const wobble = 1 + Math.sin(t * 2 + particle.a * 3) * 0.05;
      context.fillStyle = rgba(COOL, 0.35 + 0.5 * (1 - particle.r));
      context.fillRect(cx + Math.cos(particle.a) * particle.r * orbRadius * 0.86 * wobble,
        cy + Math.sin(particle.a) * particle.r * orbRadius * 0.86 * wobble, particle.size, particle.size);
    }
    context.globalCompositeOperation = "source-over";
    context.beginPath();
    context.arc(cx, cy, orbRadius, 0, TAU);
    context.lineWidth = 5;
    context.strokeStyle = rgba(accent, 0.95);
    context.shadowColor = rgba(accent, 1);
    context.shadowBlur = 28;
    context.stroke();
    context.lineWidth = 1.5;
    context.beginPath();
    context.arc(cx, cy, orbRadius + 7, t * 0.4, t * 0.4 + 4.6);
    context.strokeStyle = rgba(accent, 0.5);
    context.stroke();
    context.shadowBlur = 0;
    if (expanding === "") { // Nova is adding main ideas around the topic
      context.beginPath();
      context.arc(cx, cy, orbRadius + 14, t * 3, t * 3 + 4.2);
      context.lineWidth = 2.5;
      context.strokeStyle = rgba(accent, 0.9);
      context.stroke();
    }
    if (!(editing && editing.title)) {
      context.textAlign = "center";
      context.textBaseline = "top";
      context.font = `700 ${Math.round(Math.max(16, orbRadius * 0.26))}px Rajdhani, "Segoe UI", sans-serif`;
      context.letterSpacing = "3px";
      context.shadowColor = rgba(accent, 0.8);
      context.shadowBlur = 12;
      context.fillStyle = "rgba(255, 244, 226, 0.95)";
      context.fillText(title.toUpperCase().slice(0, 40), cx, cy + orbRadius + 18);
      context.shadowBlur = 0;
      context.letterSpacing = "0px";
    }

    for (const item of items) {
      const lit = hovered === item || selected === item;
      const glow = context.createRadialGradient(item.x, item.y, 0, item.x, item.y, item.size * 3);
      glow.addColorStop(0, rgba(item.color, lit ? 0.6 : 0.32));
      glow.addColorStop(1, rgba(item.color, 0));
      context.fillStyle = glow;
      context.fillRect(item.x - item.size * 3, item.y - item.size * 3, item.size * 6, item.size * 6);
      context.beginPath();
      context.arc(item.x, item.y, item.size * (lit ? 1.25 : 1), 0, TAU);
      context.fillStyle = "rgba(8, 14, 24, 0.92)";
      context.fill();
      context.setLineDash(item.depth ? [2, 3] : []);
      context.lineWidth = item.depth ? 1.6 : 2.4;
      context.strokeStyle = rgba(item.color, 0.95);
      context.stroke();
      context.setLineDash([]);
      context.beginPath();
      context.arc(item.x, item.y, item.size * 0.35, 0, TAU);
      context.fillStyle = rgba(item.color, 0.9);
      context.fill();
      if (selected === item) {
        context.beginPath();
        context.arc(item.x, item.y, item.size + 7 + Math.sin(t * 4) * 1.5, 0, TAU);
        context.lineWidth = 1.2;
        context.strokeStyle = "rgba(255, 255, 255, 0.75)";
        context.stroke();
      }
      if (expanding !== null && expanding === pathTo(item.node).join(" > ").toLowerCase()) {
        context.beginPath();
        context.arc(item.x, item.y, item.size + 10, t * 4, t * 4 + 4);
        context.lineWidth = 2;
        context.strokeStyle = rgba(accent, 0.95);
        context.stroke();
      }
      if (item.node.note) { // a small mark: this idea has notes
        context.fillStyle = rgba(accent, 0.95);
        context.fillRect(item.x + item.size * 0.7, item.y - item.size - 3, 4, 4);
      }
      if (dropTarget === item) {
        context.beginPath();
        context.arc(item.x, item.y, item.size + 14, 0, TAU);
        context.setLineDash([4, 4]);
        context.strokeStyle = rgba(accent, 0.95);
        context.lineWidth = 1.5;
        context.stroke();
        context.setLineDash([]);
      }
      if (editing && editing.node === item.node) continue; // the text box shows the name
      const label = labelPlace(item);
      context.font = label.font;
      context.textAlign = label.align;
      context.textBaseline = label.baseline;
      context.shadowColor = "rgba(0, 0, 0, 0.8)";
      context.shadowBlur = 6;
      context.fillStyle = lit ? "#ffffff" : item.depth ? "rgba(214, 226, 240, 0.75)" : "rgba(236, 242, 250, 0.95)";
      const name = item.node.label.length > 34 ? item.node.label.slice(0, 33) + "…" : item.node.label;
      const text = item.node.icon ? `${item.node.icon} ${name}` : name;
      context.fillText(text, label.x, label.y);
      context.shadowBlur = 0;
    }
    if (dragging && dropTarget) {
      const target = dropTarget === "core" ? { x: cx, y: cy - orbRadius - 16 } : { x: dropTarget.x, y: dropTarget.y - dropTarget.size - 22 };
      context.font = `600 11px "JetBrains Mono", Consolas, monospace`;
      context.textAlign = "center";
      context.textBaseline = "bottom";
      context.fillStyle = rgba(accent, 1);
      context.fillText(dropTarget === "core" ? "DROP: MAIN IDEA" : "DROP: SUB-IDEA", target.x, target.y);
    }
    if (linking) {
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.font = `600 11px "JetBrains Mono", Consolas, monospace`;
      context.textAlign = "center";
      context.textBaseline = "top";
      context.fillStyle = rgba(accent, 1);
      context.fillText("CLICK ANOTHER IDEA TO LINK IT · CLICK IT AGAIN LATER TO UNLINK · ESC CANCELS", width / 2, 104);
      context.setTransform(ratio * zoom, 0, 0, ratio * zoom, ratio * (cx * (1 - zoom) + panX), ratio * (cy * (1 - zoom) + panY));
    }
    if (!roots.length) {
      context.font = `400 14px "Segoe UI", sans-serif`;
      context.textAlign = "center";
      context.textBaseline = "top";
      context.fillStyle = "rgba(200, 210, 225, 0.65)";
      context.fillText("Double-click anywhere to add an idea, or say “Hey Nova, brainstorm …”", cx, cy + orbRadius + 54);
    }
    placeOverlays();
    requestAnimationFrame(frame);
  }

  function labelPlace(item) {
    const side = Math.cos(item.angle), vertical = Math.abs(side) < 0.25 && !item.parent;
    const offset = item.size + 9;
    return {
      font: item.depth === 0 ? `600 15px "Segoe UI Variable Text", "Segoe UI", sans-serif`
        : item.depth === 1 ? `500 12px "Segoe UI Variable Text", "Segoe UI", sans-serif` : `400 11px "Segoe UI Variable Text", "Segoe UI", sans-serif`,
      align: vertical ? "center" : side < 0 ? "right" : "left",
      baseline: vertical ? (Math.sin(item.angle) < 0 ? "bottom" : "top") : "middle",
      x: vertical ? item.x : item.x + (side < 0 ? -offset : offset),
      y: vertical ? item.y + (Math.sin(item.angle) < 0 ? -offset : offset) : item.y,
    };
  }

  function placeOverlays() {
    const box = canvas.getBoundingClientRect(), hostBox = host.getBoundingClientRect();
    const sel = selected && items.find((item) => item.node === selected.node);
    selected = sel || null;
    actions.hidden = !selected || Boolean(editing) || Boolean(linking) || Boolean(pressed && pressed.dragging);
    if (!actions.hidden) {
      const [sx, sy] = toScreen(selected.x, selected.y);
      actions.style.left = `${box.left - hostBox.left + sx - actions.offsetWidth / 2}px`;
      actions.style.top = `${box.top - hostBox.top + sy + selected.size * zoom + 14}px`;
    }
    if (editing) {
      let sx, sy;
      if (editing.title) [sx, sy] = toScreen(frameBox.cx, frameBox.cy + frameBox.orbRadius + 30);
      else if (editing.link) {
        if (!editing.link.mid) return;
        [sx, sy] = toScreen(editing.link.mid[0], editing.link.mid[1] - 18);
      } else {
        const item = items.find((candidate) => candidate.node === editing.node);
        if (!item) return;
        [sx, sy] = toScreen(item.x, item.y);
        sy -= item.size * zoom + 22;
      }
      input.style.left = `${box.left - hostBox.left + sx - input.offsetWidth / 2}px`;
      input.style.top = `${box.top - hostBox.top + sy - 14}px`;
    }
  }

  // ---- editing ----
  function addNode(parent, at = null) {
    remember();
    const node = { label: "", children: [] };
    if (parent && depthOf(parent) + 1 >= LIMITS.depth) parent = parentOf(roots, parent)?.parent || null;
    (parent ? parent.children : roots).push(node);
    if (at) { // placed where the user double-clicked
      const parentItem = parent && items.find((item) => item.node === parent);
      node.pos = parentItem ? [(at[0] - parentItem.x) / frameBox.rx, (at[1] - parentItem.y) / frameBox.ry]
        : [(at[0] - frameBox.cx) / frameBox.rx, (at[1] - frameBox.cy) / frameBox.ry];
    }
    layout(frameBox.width, frameBox.height);
    selected = items.find((item) => item.node === node) || null;
    beginRename(node, true);
  }

  function depthOf(node) {
    let depth = 0, place = parentOf(roots, node);
    while (place && place.parent) { depth++; place = parentOf(roots, place.parent); }
    return depth;
  }

  function beginRename(node, isNew = false) {
    editing = { node, isNew };
    input.value = node.label;
    input.placeholder = isNew ? "Name the idea…" : "";
    input.hidden = false;
    input.focus();
    input.select();
    setTimeout(() => { if (editing) input.focus(); }, 0); // in case the click that started it takes focus back
  }

  function beginLinkLabel(link) {
    editing = { link };
    input.value = link.label || "";
    input.placeholder = "Name this link (optional)…";
    input.hidden = false;
    input.focus();
    input.select();
    setTimeout(() => { if (editing) input.focus(); }, 0);
  }

  /** The link whose middle (the diamond) is at x, y. */
  function hitLink(x, y) {
    return links.find((link) => link.mid && Math.hypot(x - link.mid[0], y - link.mid[1]) < 12) || null;
  }

  function beginTitleRename() {
    editing = { title: true };
    input.value = title;
    input.placeholder = "Topic…";
    input.hidden = false;
    input.focus();
    input.select();
    setTimeout(() => { if (editing) input.focus(); }, 0); // in case the click that started it takes focus back
  }

  function finishEditing(save) {
    if (!editing) return;
    const done = editing;
    editing = null;
    input.hidden = true;
    const text = input.value.replace(/[>\n]/g, " ").replace(/\s+/g, " ").trim().slice(0, 80);
    if (done.title) {
      if (save && text && text !== title) { remember(); title = text; commit(); }
      return;
    }
    if (done.link) {
      const label = text.slice(0, 40);
      if (save && label !== done.link.label && links.includes(done.link)) { remember(); done.link.label = label; commit(); }
      return;
    }
    if (save && text) {
      if (!done.isNew && text === done.node.label) return;
      if (!done.isNew) remember();
      done.node.label = text;
      commit();
    } else if (done.isNew) { // an unnamed new idea is dropped again
      removeNode(roots, done.node);
      undoStack.pop();
      selected = null;
    }
  }

  function deleteNode(node) {
    remember();
    removeNode(roots, node);
    selected = null;
    onSelect(undefined, null);
    commit();
  }

  function undo(step = true) {
    const [from, to] = step ? [undoStack, redoStack] : [redoStack, undoStack];
    if (!from.length) return;
    to.push(JSON.stringify(snapshot()));
    load(JSON.parse(from.pop()));
    selected = null;
    onChange(snapshot());
  }

  // While naming: Enter keeps the name, Shift+Enter keeps it and starts the next idea, Tab starts a sub-idea,
  // Esc cancels. These keys stop here, so the map's own shortcuts don't fire as well.
  input.addEventListener("keydown", (event) => {
    if (!["Enter", "Tab", "Escape"].includes(event.key)) return;
    event.preventDefault();
    event.stopPropagation();
    const node = editing && editing.node;
    if (event.key === "Escape") { finishEditing(false); return; }
    finishEditing(true);
    if (!node || !roots.includes(node) && !parentOf(roots, node)) return; // the name was empty: nothing to continue from
    if (event.key === "Tab") addNode(node);
    else if (event.shiftKey) addNode(parentOf(roots, node)?.parent || null);
  });
  // Tab/Enter start the next name right away; only finish when focus really went somewhere else.
  input.addEventListener("blur", () => setTimeout(() => { if (editing && document.activeElement !== input) finishEditing(true); }, 150));

  const infoOf = (node) => ({ label: node.label, note: node.note || "", path: pathTo(node), color: node.color || "",
    icon: node.icon || "", links: links.filter((link) => link.a === node || link.b === node).length });

  function pathTo(node) {
    const names = [];
    for (let current = node; current; current = parentOf(roots, current)?.parent) names.unshift(current.label);
    return names;
  }

  /** Ideas typed into the map's text box go under the selected idea (or around the topic). */
  function addTyped(text) {
    const entries = typedIdeas(text);
    if (!entries.length) return 0;
    remember();
    let added = 0;
    const base = selected ? selected.node : null;
    for (const parts of entries) {
      let parent = parts.length > 1 ? null : base, siblings = parent ? parent.children : roots;
      parts.forEach((label, index) => {
        let node = siblings.find((candidate) => candidate.label.toLowerCase() === label.toLowerCase());
        if (!node && (index === parts.length - 1 || parts.length > 1)) {
          if (siblings.length >= (parent ? LIMITS.children : LIMITS.roots) || (parent && depthOf(parent) + 1 >= LIMITS.depth)) return;
          node = { label, children: [] };
          siblings.push(node);
          added++;
        }
        if (node) { parent = node; siblings = node.children; }
      });
    }
    commit();
    return added;
  }

  function exportImage() {
    const link = document.createElement("a");
    link.download = `Nova map - ${title.replace(/[\\/:*?"<>|]/g, " ")}.png`;
    link.href = canvas.toDataURL("image/png");
    link.click();
  }

  // ---- pointer ----
  const pointer = (event) => {
    const box = canvas.getBoundingClientRect();
    return [event.clientX - box.left, event.clientY - box.top];
  };

  canvas.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    if (editing) finishEditing(true);
    const [sx, sy] = pointer(event), [x, y] = toWorld(sx, sy);
    const target = hit(x, y);
    if (linking) {
      const from = linking;
      linking = null;
      if (target && target !== "core" && target.node !== from) toggleLink(from, target.node);
      return;
    }
    canvas.setPointerCapture(event.pointerId);
    if (target && target !== "core") {
      selected = target;
      pressed = { item: target, startX: sx, startY: sy, grabX: x - target.x, grabY: y - target.y, dragging: false };
      onSelect(target.node.line, infoOf(target.node));
    } else {
      if (selected) onSelect(undefined, null);
      selected = null;
      pressed = { pan: true, startX: sx, startY: sy, panX, panY };
    }
  });

  canvas.addEventListener("pointermove", (event) => {
    const [sx, sy] = pointer(event), [x, y] = toWorld(sx, sy);
    mouse = { x, y };
    if (!pressed) {
      const target = hit(x, y);
      hovered = target && target !== "core" ? target : null;
      canvas.style.cursor = linking ? "crosshair" : target === "core" ? "text" : hovered ? "grab" : "default";
      return;
    }
    if (pressed.pan) {
      panX = pressed.panX + sx - pressed.startX;
      panY = pressed.panY + sy - pressed.startY;
      canvas.style.cursor = "grabbing";
      return;
    }
    if (!pressed.dragging && Math.hypot(sx - pressed.startX, sy - pressed.startY) < 5) return;
    if (!pressed.dragging) { pressed.dragging = true; remember(); }
    canvas.style.cursor = "grabbing";
    const node = pressed.item.node;
    const parentItem = pressed.item.parent && items.find((item) => item.node === pressed.item.parent.node);
    const nx = x - pressed.grabX, ny = y - pressed.grabY;
    node.pos = parentItem ? [(nx - parentItem.x) / frameBox.rx, (ny - parentItem.y) / frameBox.ry]
      : [(nx - frameBox.cx) / frameBox.rx, (ny - frameBox.cy) / frameBox.ry];
    const target = hit(x, y, node);
    dropTarget = target === "core" ? (pressed.item.parent ? "core" : null)
      : target && target.node !== (parentOf(roots, node)?.parent) ? target : null;
  });

  canvas.addEventListener("pointerup", (event) => {
    if (!pressed) return;
    const done = pressed;
    pressed = null;
    canvas.style.cursor = "default";
    if (!done.dragging) return;
    const node = done.item.node;
    if (dropTarget === "core") { // becomes a main idea where it was dropped
      const [x, y] = toWorld(...pointer(event));
      moveNode(roots, node, null);
      node.pos = [(x - frameBox.cx) / frameBox.rx, (y - frameBox.cy) / frameBox.ry];
      if (Math.hypot(node.pos[0], node.pos[1]) < 0.6) node.pos = null; // dropped on the core itself: let it find a place
    } else if (dropTarget) {
      moveNode(roots, node, dropTarget.node);
      node.pos = null; // finds a place next to its new parent
    }
    dropTarget = null;
    commit();
  });

  canvas.addEventListener("dblclick", (event) => {
    const [x, y] = toWorld(...pointer(event));
    const target = hit(x, y);
    const link = !target || target === "core" ? hitLink(x, y) : null;
    if (link) beginLinkLabel(link);
    else if (target === "core") beginTitleRename();
    else if (target) beginRename(target.node);
    else if (roots.length < LIMITS.roots) addNode(null, [x, y]);
  });

  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    const [sx, sy] = pointer(event), [x, y] = toWorld(sx, sy);
    zoom = Math.max(0.4, Math.min(2.5, zoom * Math.exp(-event.deltaY * 0.0015)));
    // keep the point under the mouse where it is
    panX = sx - x * zoom - frameBox.cx * (1 - zoom);
    panY = sy - y * zoom - frameBox.cy * (1 - zoom);
  }, { passive: false });

  canvas.addEventListener("pointerleave", () => { if (!pressed) hovered = null; });

  return {
    /** Data from Nova (voice, Nova's brainstorm, a saved map): replaces what is shown. */
    setData(data) { load(data); },
    /** Text typed in the editor: keeps the positions of ideas whose path did not change. */
    setText(newTitle, outline) { load({ title: newTitle, outline }, true); onChange(snapshot()); },
    data: snapshot,
    setAccent(rgb) { accent = String(rgb).split(",").map((part) => Number(part.trim()) || 0); },
    show(on) {
      const starting = on && !visible;
      visible = on;
      canvas.hidden = !on;
      if (!on) { finishEditing(true); actions.hidden = true; }
      if (starting) { last = performance.now(); requestAnimationFrame(frame); }
    },
    addIdea() { addNode(selected ? (parentOf(roots, selected.node)?.parent || null) : null); },
    tidy() { remember(); const clear = (list) => list.forEach((node) => { node.pos = null; clear(node.children); }); clear(roots); zoom = 1; panX = panY = 0; commit(); },
    undo() { undo(true); },
    redo() { undo(false); },
    get selected() { return selected ? selected.node : null; },
    selectedPath() { return selected ? pathTo(selected.node) : []; },
    selectedLabel() { return selected ? selected.node.label : title; },
    addTyped,
    exportImage,
    setNote(text) { if (selected) { selected.node.note = String(text).slice(0, 4000); commit(); } },
    /** Colour and/or icon for the selected idea; "" clears one. Returns the idea's info for the note card. */
    setStyle({ color, icon } = {}) {
      if (!selected) return null;
      remember();
      const node = selected.node;
      if (color !== undefined) node.color = PALETTE[color] ? color : "";
      if (icon !== undefined) node.icon = Array.from(String(icon).trim()).slice(0, 8).join("");
      commit();
      return infoOf(node);
    },
    startLink,
    get linking() { return Boolean(linking); },
    setExpanding(path) { expanding = path ?? null; },
    /** For tests: where each idea is drawn, in pixels from the canvas' top-left. */
    screenPositions() { return items.map((item) => ({ label: item.node.label, at: toScreen(item.x, item.y) })); },
    deselect() { selected = null; },
    /** Map keys while it is open; returns true when the key was used. */
    handleKey(event) {
      if (editing) return false;
      const ctrl = event.ctrlKey || event.metaKey;
      if (ctrl && event.key.toLowerCase() === "z") { undo(!event.shiftKey); return true; }
      if (ctrl && event.key.toLowerCase() === "y") { undo(false); return true; }
      if (event.key === "Tab") { addNode(selected ? selected.node : null); return true; }
      if (event.key === "Enter" && selected) { addNode(parentOf(roots, selected.node)?.parent || null); return true; }
      if (event.key === "F2" && selected) { beginRename(selected.node); return true; }
      if (event.key === "Escape" && linking) { linking = null; return true; }
      if (event.key.toLowerCase() === "l" && !ctrl && selected) { startLink(); return true; }
      if ((event.key === "Delete" || event.key === "Backspace") && selected) { deleteNode(selected.node); return true; }
      if (event.key === "Escape" && selected) { selected = null; onSelect(undefined, null); return true; }
      return false;
    },
  };
}
