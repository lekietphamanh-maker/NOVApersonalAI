// Rea's orbit view: a small glowing core (the app being analysed) with its parts orbiting it on tilted rings, the
// links between them arcing through the core, and what matters around the edges: counts top right, the selected
// part's card on the right, the stages and the live timeline of steps along the bottom, past reports below that.
// Drag to spin and tilt, scroll or pinch to zoom, click a part; arrows, + and -, and webcam gestures work too.

import { h, when, screen, renderStrip } from "./lab.js";

const KINDS = { ui: ["#3be4ff", "UI"], logic: ["#5b8cff", "λ"], data: ["#a78bff", "DB"], storage: ["#ffb040", "▤"],
  network: ["#2ee6c0", "⇄"], native: ["#ff5fd2", "◆"], external: ["#ff8a4c", "↗"] };
const STAGES = ["Read", "Map", "Explain", "Report"];
const CORE_SHARE = 0.075, ORBIT_SHARE = 0.34, PARTICLES = 520;

function kind(part) {
  return KINDS[part.kind] || KINDS.logic;
}

export function createRea(root, { act, onOpenChange }) {
  const $ = (selector) => root.querySelector(selector);
  const canvas = $("#rea-canvas"), context = canvas.getContext("2d");
  const card = $("#rea-card"), title = $("#rea-title"), metrics = $("#rea-metrics"), timeline = $("#rea-timeline");
  const stagesBox = $("#rea-stages"), strip = $("#rea-strip"), problemLine = $("#rea-problem");
  let jobs = [], job = null, selected = -1, steps = [], frame = 0;
  const orbit = { rot: 0, tilt: 0.36, zoom: 1, spin: 0.0016, target: null };
  const pointers = new Map();
  let drag = null, pinch = 0, placed = [], hover = -1;
  const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const particles = Array.from({ length: PARTICLES }, () => ({
    angle: Math.random() * Math.PI * 2, height: Math.random() * 2 - 1, speed: 0.002 + Math.random() * 0.006,
    lane: 0.25 + Math.random() * 0.75, twist: 0.6 + Math.random() * 1.4, size: 0.5 + Math.random() * 1.3 }));

  const view = screen(root, {
    onOpenChange: (open) => {
      onOpenChange?.(open);
      act("lab_view", { view: "rea", open });
      cancelAnimationFrame(frame);
      if (open) frame = requestAnimationFrame(draw);
    },
    onOpen: refresh,
  });

  async function refresh() {
    const result = await act("rea_view");
    if (!result.ok) return;
    jobs = result.jobs || [];
    drawStrip();
    if (!job && jobs[0]) pick(jobs[0].id);
    else render();
  }

  async function pick(id) {
    const result = await act("rea_open", { id });
    if (!result.ok) return;
    job = result.job;
    selected = -1;
    steps = job.steps || [];
    drawStrip();
    render();
  }

  function parts() {
    return job?.blueprint?.parts || [];
  }

  function drawStrip() {
    renderStrip(strip, jobs, job?.id, pick, (item) => (item.status === "running" ? "analysing…"
      : item.status === "failed" ? "stopped" : `${item.counts?.parts ?? 0} parts`));
  }

  // ---------- the edges: title, counts, the selected part, stages and the timeline ----------

  function render() {
    const list = parts(), findings = list.reduce((sum, part) => sum + part.findings.length, 0);
    const running = job?.status === "running";
    title.replaceChildren(
      h("span", { class: `rea-live${running ? " on" : ""}` }, running ? "● ANALYSING" : job ? "● REPORT" : "● READY"),
      h("b", {}, job ? job.title : "Rea"),
      h("small", {}, job ? `${job.target}${job.started ? ` · ${when(job.started)}` : ""}` : "Type an app, file, folder or site above, or say “reverse engineer …”."));
    metrics.replaceChildren(...[["Parts", list.length], ["Findings", findings], ["Links", job?.blueprint?.links?.length || 0],
      ["Steps", steps.length]].map(([label, value]) => h("div", {}, h("small", {}, label), h("b", {}, String(value)))));
    const stage = !job ? -1 : job.status === "done" ? 3 : job.status === "failed" ? -1 : steps.length < 5 ? 0 : steps.length < 15 ? 1 : 2;
    stagesBox.replaceChildren(...STAGES.map((name, index) => h("span", {
      class: `${index <= stage ? "lit" : ""}${running && index === stage ? " now" : ""}` }, name)));
    timeline.replaceChildren(...(steps.length ? steps.slice(-9) : [job?.status === "failed" ? job.error || "Stopped." : "Steps show here as Rea works."])
      .map((line, index, all) => h("li", { class: index === all.length - 1 ? "now" : "" }, h("i", { "aria-hidden": "true" }), line)));
    renderCard();
  }

  function renderCard() {
    const part = parts()[selected];
    if (!part) {
      const summary = (job?.summary || "").split("\n").filter(Boolean).slice(0, 4);
      card.replaceChildren(...[  // replaceChildren would write a null as the text "null"
        h("h4", {}, job ? "Overview" : "Rea"),
        ...(summary.length ? summary.map((line) => h("p", {}, line.replace(/^#+\s*/, ""))) : [h("p", { class: "muted small" },
          job?.status === "running" ? "The parts appear around the core when Rea is done." :
          "Rea works through Claude Code on your plan. Only analyse software you're allowed to.")]),
        parts().length ? h("p", { class: "muted small" }, "Click a part, swipe, or use ← → to go round.") : null,
        job?.report ? h("button", { class: "box small on", type: "button", onclick: () => act("rea_report", { id: job.id }) }, "Open full report") : null,
      ].filter(Boolean));
      return;
    }
    const name = (id) => parts().find((item) => item.id === id)?.name || id;
    const talks = (job.blueprint.links || []).filter((link) => link.from === part.id || link.to === part.id)
      .map((link) => h("li", {}, link.from === part.id ? `→ ${name(link.to)}` : `← ${name(link.from)}`, link.label ? h("small", {}, ` ${link.label}`) : null));
    card.replaceChildren(
      h("span", { class: "lab-tag", style: `color:${kind(part)[0]};border-color:${kind(part)[0]}` }, part.kind),
      h("h4", {}, part.name), h("p", {}, part.summary),
      part.findings.length ? h("h5", {}, `Found · ${part.findings.length}`) : null,
      h("ul", { class: "lab-list" }, part.findings.map((item) => h("li", {}, item))),
      talks.length ? h("h5", {}, "Talks to") : null, h("ul", { class: "lab-list" }, talks),
      h("button", { class: "box small", type: "button", onclick: () => choose(-1) }, "Back to overview"));
  }

  function choose(index) {
    const count = parts().length;
    selected = count ? ((index % count) + count) % count : -1;
    if (index < 0) selected = -1;
    if (selected >= 0) orbit.target = Math.PI / 2 - (selected / count) * Math.PI * 2;  // bring it round to the front
    renderCard();
  }

  // ---------- the scene ----------

  function fit() {
    const box = canvas.getBoundingClientRect(), scale = window.devicePixelRatio || 1;
    const width = Math.max(1, Math.round(box.width * scale)), height = Math.max(1, Math.round(box.height * scale));
    if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
    const short = Math.min(width, height);
    return { width, height, scale, cx: width / 2, cy: height * 0.47, core: short * CORE_SHARE * orbit.zoom,
             rx: short * ORBIT_SHARE * 1.25 * orbit.zoom };
  }

  function drawCore(g, now, running) {
    const energy = running ? 1.6 : 1;
    const glow = context.createRadialGradient(g.cx, g.cy, 0, g.cx, g.cy, g.core * 2.6);
    glow.addColorStop(0, `rgba(200, 230, 255, ${0.55 * energy})`);
    glow.addColorStop(0.3, "rgba(90, 150, 255, 0.24)");
    glow.addColorStop(1, "rgba(20, 40, 120, 0)");
    context.fillStyle = glow;
    context.beginPath();
    context.arc(g.cx, g.cy, g.core * 2.6, 0, Math.PI * 2);
    context.fill();
    context.globalCompositeOperation = "lighter";
    const tall = g.core * 1.9;
    for (const particle of particles) {
      if (!calm) {
        particle.height += particle.speed * energy;
        if (particle.height > 1) particle.height = -1;
        particle.angle += 0.01 * particle.twist * energy;
      }
      const y = particle.height, width = g.core * particle.lane * (0.25 + 0.75 * (1 - y * y));
      const wave = Math.sin(y * 4 + now / 900 + particle.lane * 6) * g.core * 0.18;
      const x = g.cx + Math.sin(particle.angle) * width + wave, py = g.cy - y * tall;
      const fade = (1 - Math.abs(y)) * (0.45 + 0.55 * (Math.cos(particle.angle) + 1) / 2);
      context.strokeStyle = `rgba(${170 + 60 * particle.lane | 0}, ${200 + 40 * particle.lane | 0}, 255, ${0.85 * fade})`;
      context.lineWidth = particle.size * g.scale * 0.9;
      context.beginPath();
      context.moveTo(x, py);
      context.lineTo(x - Math.cos(particle.angle) * width * 0.08, py + tall * particle.speed * 9 * energy);
      context.stroke();
    }
    context.globalCompositeOperation = "source-over";
  }

  function drawRing(g, radiusX, now, running) {
    const radiusY = radiusX * orbit.tilt;
    for (const [from, to, alpha] of [[Math.PI, Math.PI * 2, 0.12], [0, Math.PI, 0.38]]) {  // back half dim, front bright
      context.strokeStyle = `rgba(110, 170, 255, ${alpha})`;
      context.lineWidth = 1.2 * g.scale;
      context.beginPath();
      context.ellipse(g.cx, g.cy, radiusX, radiusY, 0, from, to);
      context.stroke();
    }
    if (running) {  // a sweep going round while Rea works
      const at = (now / 1200) % (Math.PI * 2);
      context.strokeStyle = "rgba(160, 220, 255, 0.85)";
      context.lineWidth = 2.4 * g.scale;
      context.beginPath();
      context.ellipse(g.cx, g.cy, radiusX, radiusY, 0, at, at + 0.5);
      context.stroke();
    }
  }

  function place(g) {
    const list = parts(), count = list.length;
    placed = list.map((part, index) => {
      const inner = count > 7 && index % 2 === 1;
      const radiusX = g.rx * (inner ? 0.72 : 1), angle = orbit.rot + (index / count) * Math.PI * 2;
      const depth = Math.sin(angle);  // 1 in front, -1 behind the core
      return { part, index, depth, angle, radiusX, scale: 0.78 + 0.3 * (depth + 1) / 2,
               x: g.cx + Math.cos(angle) * radiusX, y: g.cy + depth * radiusX * orbit.tilt };
    });
  }

  function drawLinks(g, now) {
    const byId = new Map(placed.map((item) => [item.part.id, item]));
    for (const [number, link] of (job?.blueprint?.links || []).entries()) {
      const from = byId.get(link.from), to = byId.get(link.to);
      if (!from || !to) continue;
      const lit = selected >= 0 && (from.index === selected || to.index === selected);
      const controlX = g.cx + ((from.x + to.x) / 2 - g.cx) * 0.25, controlY = g.cy + ((from.y + to.y) / 2 - g.cy) * 0.25;
      context.strokeStyle = lit ? "rgba(190, 230, 255, 0.85)" : "rgba(120, 170, 255, 0.16)";
      context.lineWidth = (lit ? 1.8 : 1) * g.scale;
      context.beginPath();
      context.moveTo(from.x, from.y);
      context.quadraticCurveTo(controlX, controlY, to.x, to.y);
      context.stroke();
      const t = ((now / 2400) + number * 0.17) % 1;  // a spark travelling along it
      const x = (1 - t) ** 2 * from.x + 2 * (1 - t) * t * controlX + t * t * to.x;
      const y = (1 - t) ** 2 * from.y + 2 * (1 - t) * t * controlY + t * t * to.y;
      context.fillStyle = lit ? "#e8f6ff" : "rgba(170, 210, 255, 0.55)";
      context.beginPath();
      context.arc(x, y, (lit ? 2.6 : 1.6) * g.scale, 0, Math.PI * 2);
      context.fill();
    }
  }

  function drawNode(g, item, now) {
    const [color, glyph] = kind(item.part), radius = 17 * g.scale * item.scale * Math.min(1.25, orbit.zoom);
    const on = item.index === selected, near = item.index === hover;
    context.globalAlpha = 0.45 + 0.55 * (item.depth + 1) / 2;
    const trail = context.createLinearGradient(item.x, item.y, g.cx + Math.cos(item.angle - 0.5) * item.radiusX,
      g.cy + Math.sin(item.angle - 0.5) * item.radiusX * orbit.tilt);  // a fading trail behind it on its orbit
    trail.addColorStop(0, color);
    trail.addColorStop(1, "rgba(0, 0, 0, 0)");
    context.strokeStyle = trail;
    context.lineWidth = 2.2 * g.scale;
    context.beginPath();
    context.ellipse(g.cx, g.cy, item.radiusX, item.radiusX * orbit.tilt, 0, item.angle - 0.5, item.angle);
    context.stroke();
    if (on) {
      const pulse = (Math.sin(now / 300) + 1) / 2;
      context.strokeStyle = color;
      context.lineWidth = 1.5 * g.scale;
      context.beginPath();
      context.arc(item.x, item.y, radius * (1.5 + 0.35 * pulse), 0, Math.PI * 2);
      context.stroke();
    }
    context.shadowColor = color;
    context.shadowBlur = (on || near ? 26 : 14) * g.scale;
    context.fillStyle = "rgba(6, 10, 24, 0.92)";
    context.strokeStyle = color;
    context.lineWidth = (on ? 2.6 : 1.8) * g.scale;
    context.beginPath();
    context.arc(item.x, item.y, radius, 0, Math.PI * 2);
    context.fill();
    context.stroke();
    context.shadowBlur = 0;
    context.fillStyle = color;
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.font = `600 ${radius * 0.72}px "JetBrains Mono", monospace`;
    context.fillText(glyph, item.x, item.y + 1);
    context.fillStyle = on || near ? "#fff" : "rgba(225, 235, 255, 0.85)";
    context.font = `600 ${10.5 * g.scale}px "JetBrains Mono", monospace`;
    const label = item.part.name.length > 20 ? `${item.part.name.slice(0, 19)}…` : item.part.name;
    context.fillText(label.toUpperCase(), item.x, item.y + radius + 13 * g.scale);
    context.fillStyle = color;
    context.font = `500 ${8.5 * g.scale}px "JetBrains Mono", monospace`;
    context.fillText(`${item.part.kind.toUpperCase()}${item.part.findings.length ? ` · ${item.part.findings.length} FOUND` : ""}`,
      item.x, item.y + radius + 25 * g.scale);
    context.globalAlpha = 1;
    item.radius = radius;
  }

  function draw(now) {
    if (!view.isOpen()) return;
    frame = requestAnimationFrame(draw);
    const g = fit(), running = job?.status === "running";
    if (orbit.target !== null) {  // ease round to the chosen part
      const gap = ((orbit.target - orbit.rot + Math.PI * 3) % (Math.PI * 2)) - Math.PI;
      orbit.rot += gap * 0.12;
      if (Math.abs(gap) < 0.002) orbit.target = null;
    } else if (!drag && !calm && selected < 0) {
      orbit.rot += orbit.spin;
    }
    context.clearRect(0, 0, g.width, g.height);
    place(g);
    drawRing(g, g.rx * 1.18, now, false);
    drawRing(g, g.rx, now, running);
    if (placed.length > 7) drawRing(g, g.rx * 0.72, now, false);
    drawLinks(g, now);
    for (const item of placed.filter((one) => one.depth < 0).sort((a, b) => a.depth - b.depth)) drawNode(g, item, now);
    drawCore(g, now, running);
    for (const item of placed.filter((one) => one.depth >= 0).sort((a, b) => a.depth - b.depth)) drawNode(g, item, now);
  }

  // ---------- moving it: drag, pinch, scroll, click, keys and gestures ----------

  function hit(event) {
    const box = canvas.getBoundingClientRect(), scale = window.devicePixelRatio || 1;
    const x = (event.clientX - box.left) * scale, y = (event.clientY - box.top) * scale;
    let best = -1, distance = Infinity;
    for (const item of placed) {
      const gap = Math.hypot(item.x - x, item.y - y);
      if (gap < (item.radius || 20) * 1.8 && gap < distance) { best = item.index; distance = gap; }
    }
    return best;
  }

  canvas.addEventListener("pointerdown", (event) => {
    canvas.setPointerCapture(event.pointerId);
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      pinch = Math.hypot(a.x - b.x, a.y - b.y);
    } else {
      drag = { x: event.clientX, y: event.clientY, moved: 0 };
    }
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!pointers.has(event.pointerId)) {
      hover = hit(event);
      canvas.style.cursor = hover >= 0 ? "pointer" : "grab";
      return;
    }
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pointers.size === 2 && pinch) {
      const [a, b] = [...pointers.values()], distance = Math.hypot(a.x - b.x, a.y - b.y);
      orbit.zoom = Math.max(0.6, Math.min(1.8, orbit.zoom * distance / pinch));
      pinch = distance;
      return;
    }
    if (!drag) return;
    const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
    drag.moved += Math.abs(dx) + Math.abs(dy);
    orbit.rot += dx * 0.006;
    orbit.tilt = Math.max(0.16, Math.min(0.62, orbit.tilt + dy * 0.0025));
    orbit.target = null;
    drag.x = event.clientX;
    drag.y = event.clientY;
  });
  const release = (event) => {
    pointers.delete(event.pointerId);
    if (pointers.size < 2) pinch = 0;
    if (drag && drag.moved < 5 && pointers.size === 0) choose(hit(event));
    if (pointers.size === 0) drag = null;
  };
  canvas.addEventListener("pointerup", release);
  canvas.addEventListener("pointercancel", release);
  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    orbit.zoom = Math.max(0.6, Math.min(1.8, orbit.zoom * (event.deltaY < 0 ? 1.08 : 1 / 1.08)));
  }, { passive: false });

  function command(name) {
    const count = parts().length;
    if (name === "next" && count) choose(selected + 1);
    else if (name === "previous" && count) choose(selected < 0 ? count - 1 : selected - 1);
    else if (name === "zoom_in") orbit.zoom = Math.min(1.8, orbit.zoom * 1.15);
    else if (name === "zoom_out") orbit.zoom = Math.max(0.6, orbit.zoom / 1.15);
    else if (name === "open" && job?.report && selected < 0) act("rea_report", { id: job.id });
    else if (name === "open" && count && selected < 0) choose(0);
    else if (name === "back") choose(-1);
    else if (name === "close") view.close();
  }

  function handleKey(event) {
    const keys = { ArrowRight: "next", ArrowLeft: "previous", "+": "zoom_in", "=": "zoom_in", "-": "zoom_out", Enter: "open", Backspace: "back" };
    if (!keys[event.key]) return false;
    command(keys[event.key]);
    return true;
  }

  $("#rea-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const result = await act("rea_start", { target: form.target.value, goal: form.goal.value });
    if (result.ok !== false) form.reset();
  });
  $("#rea-close").onclick = () => view.close();

  return {
    ...view,
    command,
    handleKey,
    job(next) { // a job started or ended
      jobs = [next, ...jobs.filter((item) => item.id !== next.id)];
      if (next.status === "running" && (!job || job.status !== "running")) { job = next; steps = []; selected = -1; }
      if (job?.id === next.id) next.status === "running" ? render() : pick(next.id);
      drawStrip();
    },
    step({ id, line }) {
      if (job?.id !== id) return;
      steps.push(line);
      render();
    },
    ready({ problem }) {
      problemLine.hidden = !problem;
      problemLine.textContent = problem ? `Can't run Rea here yet: ${problem}.` : "";
    },
  };
}
