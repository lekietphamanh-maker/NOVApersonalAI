// Shannon's shield: your app as a hexagon shield with a glowing heart, Shannon's attacks swirling around it. Each hole
// it proved is a weak spot on the shell in brackets: red and pulsing for critical and high (look at these first), amber
// for medium, yellow for low. Mark one fixed and it calms to green. Drag to turn, scroll or pinch to zoom, click a
// spot; arrows, + and -, and webcam gestures work too. Stages, the log and past checks run along the bottom.

import { h, when, screen, renderStrip, openReportPanel } from "./lab.js";
import { askPhrase, mountWhatCanIDo } from "./whatcanido.js";

const STAGES = [["recon", "Recon"], ["analysis", "Analysis"], ["exploit", "Exploit"], ["validate", "Validate"], ["report", "Report"]];
const SEVERITIES = ["critical", "high", "medium", "low"];
const COLORS = { critical: [255, 45, 85], high: [255, 90, 60], medium: [255, 181, 71], low: [240, 220, 90], fixed: [92, 242, 176] };
const STREAKS = 380, SHIELD_SHARE = 0.31, RADIANS = Math.PI / 180;

export function createShannon(root, { act, onOpenChange }) {
  const $ = (selector) => root.querySelector(selector);
  const canvas = $("#shannon-canvas"), context = canvas.getContext("2d");
  const banner = $("#shannon-banner"), spotsList = $("#shannon-spots"), side = $("#shannon-side");
  const stagesBox = $("#shannon-stages"), logLine = $("#shannon-log"), strip = $("#shannon-strip");
  const problemLine = $("#shannon-problem"), form = $("#shannon-form"), stopButton = $("#shannon-stop");
  let jobs = [], job = null, log = [], running = "", selected = -1, frame = 0, spots = [];
  const view3d = { yaw: 0.4, pitch: 0.25, zoom: 1, target: null };
  const pointers = new Map();
  let drag = null, pinch = 0;
  const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const streaks = Array.from({ length: STREAKS }, () => ({
    angle: Math.random() * Math.PI * 2, radius: 1.05 + Math.random() * 0.95, lift: (Math.random() - 0.5) * 1.2,
    speed: 0.004 + Math.random() * 0.012, length: 0.04 + Math.random() * 0.12,
    color: [[255, 95, 160], [255, 140, 90], [255, 70, 110], [255, 190, 120]][Math.random() * 4 | 0] }));
  const hexes = [];
  for (let lat = -78; lat <= 78; lat += 13) {
    const step = 13 / Math.max(0.2, Math.cos(lat * RADIANS));
    for (let lon = (Math.round(lat / 13) % 2) * step / 2; lon < 360; lon += step) hexes.push([lat, lon]);
  }

  mountWhatCanIDo(root.querySelector(".lab-bottom"), "shannon", { onPhrase: askPhrase });
  const view = screen(root, {
    onOpenChange: (open) => {
      onOpenChange?.(open);
      act("lab_view", { view: "shannon", open });
      cancelAnimationFrame(frame);
      if (open) frame = requestAnimationFrame(draw);
    },
    onOpen: refresh,
  });

  // ---------- the full report on screen ----------
  async function openFullReport() {
    const shown = job; // a job event during the wait must not retitle this panel
    const result = await act("shannon_report_text", { id: shown.id });
    openReportPanel(root, { title: shown.title || "Full report", text: result.ok ? result.text : (result.error || "The report isn't there any more.") });
  }

  async function refresh() {
    const result = await act("shannon_view");
    if (!result.ok) return;
    jobs = result.jobs || [];
    running = result.running || "";
    $("#shannon-projects").replaceChildren(...(result.projects || []).map((name) => h("option", { value: name })));
    drawStrip();
    if (!job && jobs[0]) pick(jobs[0].id);
    else render();
  }

  async function pick(id) {
    const result = await act("shannon_open", { id });
    if (!result.ok) return;
    job = result.job;
    log = job.log || [];
    selected = -1;
    drawStrip();
    render();
  }

  function findings() {
    return job?.findings || [];
  }

  function state(finding) {
    return finding.fixed ? "fixed" : finding.severity;
  }

  function drawStrip() {
    stopButton.hidden = !running;
    renderStrip(strip, jobs, job?.id, pick, (item) => {
      if (item.status === "running") return "running…";
      if (item.status === "failed") return "stopped";
      const found = SEVERITIES.filter((severity) => item.counts?.[severity]).map((severity) => `${item.counts[severity]} ${severity}`);
      return found.join(", ") || "no proven holes";
    });
  }

  // ---------- around the shield: banner, list of spots, the chosen spot, stages and log ----------

  function render() {
    const list = findings(), open = list.filter((finding) => !finding.fixed).length;
    const isRunning = job?.status === "running";
    banner.className = `shannon-banner${open ? " alert" : list.length ? " clear" : ""}`;
    banner.textContent = !job ? "Pick a project and Run" : isRunning ? "Attacking…" : job.status === "failed" ? "Shannon stopped"
      : !list.length ? "No proven holes" : open ? `${open} weak spot${open === 1 ? "" : "s"}` : "All fixed";
    spotsList.replaceChildren(...list.map((finding, index) => h("li", {}, h("button", {
      type: "button", class: `${state(finding)}${index === selected ? " on" : ""}`, onclick: () => choose(index),
    }, h("i", { "aria-hidden": "true" }), h("span", {}, finding.title), h("small", {}, finding.fixed ? "fixed" : finding.severity)))));
    const reached = !job ? -1 : job.status === "done" ? STAGES.length - 1 : STAGES.findIndex(([key]) => key === job.stage);
    stagesBox.replaceChildren(...STAGES.map(([, name], index) => h("span", {
      class: `${index <= reached ? "lit" : ""}${isRunning && index === Math.max(0, reached) ? " now" : ""}` }, name)));
    logLine.textContent = log.length ? log[log.length - 1] : job?.error || "Shannon's own output shows here while it runs.";
    renderSide();
  }

  function renderSide() {
    const finding = findings()[selected];
    if (!finding) {
      side.replaceChildren(
        h("h4", {}, job ? job.title : "Shannon"),
        h("p", { class: "muted small" }, job ? `${when(job.started)} · ${job.target}` :
          "Pick one of your projects, say where it runs on this PC (like localhost:3000), and Run."),
        findings().length ? h("p", {}, "Red spots first: those are the holes someone could use right now. Click one for the proof and the fix.") : null,
        job?.report ? h("button", { class: "box small on", type: "button", onclick: () => openFullReport() }, "Open full report") : null);
      return;
    }
    const color = `rgb(${COLORS[state(finding)].join(",")})`;
    side.replaceChildren(
      h("span", { class: "lab-tag", style: `color:${color};border-color:${color}` }, finding.fixed ? "fixed" : finding.severity),
      h("h4", {}, finding.title),
      h("p", { class: "muted small" }, `${finding.kind}${finding.where ? ` · ${finding.where}` : ""}`),
      h("h5", {}, "Proof"), h("p", {}, finding.proof || "In the full report."),
      finding.fix ? h("h5", {}, "Fix") : null, finding.fix ? h("p", {}, finding.fix) : null,
      h("div", { class: "row wrap" },
        h("button", { class: `box small${finding.fixed ? "" : " on"}`, type: "button", onclick: () => markFixed(selected, !finding.fixed) },
          finding.fixed ? "Reopen" : "Mark fixed"),
        h("button", { class: "box small", type: "button", onclick: () => choose(-1) }, "Back")));
  }

  async function markFixed(index, fixed) {
    const result = await act("shannon_fix", { id: job.id, index, fixed });
    if (result.ok) { job = result.job; render(); }
  }

  function choose(index) {
    const count = findings().length;
    selected = index >= 0 && count ? ((index % count) + count) % count : -1;
    if (selected >= 0) {  // turn the shield so the spot faces you
      const [lat, lon] = place(selected);
      view3d.target = { yaw: -lon * RADIANS, pitch: Math.max(-0.9, Math.min(0.9, lat * RADIANS)) };
    }
    render();
  }

  // ---------- the scene ----------

  function place(index, count = findings().length) {  // spread evenly over the sphere (golden angle), the same place every time
    count = Math.max(1, count);
    const lat = Math.asin(1 - 2 * (index + 0.5) / count) / RADIANS * 0.85;
    return [lat, (index * 137.508) % 360];
  }

  function project(lat, lon, g) {
    const phi = lat * RADIANS, lambda = lon * RADIANS + view3d.yaw;
    const x = Math.cos(phi) * Math.sin(lambda), y = Math.sin(phi), z = Math.cos(phi) * Math.cos(lambda);
    const pitch = view3d.pitch, y2 = y * Math.cos(pitch) - z * Math.sin(pitch), z2 = y * Math.sin(pitch) + z * Math.cos(pitch);
    return [g.cx + x * g.radius, g.cy - y2 * g.radius, z2];
  }

  function hexagon(lat, lon, size, g) {
    const corners = [];
    for (let side = 0; side < 6; side++) {
      const angle = side * Math.PI / 3 + Math.PI / 6;
      corners.push(project(lat + size * Math.sin(angle), lon + size * Math.cos(angle) / Math.max(0.25, Math.cos(lat * RADIANS)), g));
    }
    return corners;
  }

  function fit() {
    const box = canvas.getBoundingClientRect(), scale = window.devicePixelRatio || 1;
    const width = Math.max(1, Math.round(box.width * scale)), height = Math.max(1, Math.round(box.height * scale));
    if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
    return { width, height, scale, cx: width * 0.5, cy: height * 0.47, radius: Math.min(width, height) * SHIELD_SHARE * view3d.zoom };
  }

  function drawStreaks(g, behind, speed) {
    context.globalCompositeOperation = "lighter";
    for (const streak of streaks) {
      if (!calm && behind) streak.angle += streak.speed * speed;
      const depth = Math.sin(streak.angle);
      if ((depth < 0) !== behind) continue;
      const radius = g.radius * streak.radius, tilt = 0.42;
      const point = (angle) => [g.cx + Math.cos(angle) * radius, g.cy + Math.sin(angle) * radius * tilt + streak.lift * g.radius * 0.5];
      const [x1, y1] = point(streak.angle - streak.length), [x2, y2] = point(streak.angle);
      const [r, gr, b] = streak.color;
      context.strokeStyle = `rgba(${r}, ${gr}, ${b}, ${(behind ? 0.3 : 0.75) * (0.5 + 0.5 * Math.abs(depth))})`;
      context.lineWidth = 1.4 * g.scale;
      context.beginPath();
      context.moveTo(x1, y1);
      context.lineTo(x2, y2);
      context.stroke();
    }
    context.globalCompositeOperation = "source-over";
  }

  function drawShield(g) {
    const inner = context.createRadialGradient(g.cx, g.cy, 0, g.cx, g.cy, g.radius);
    inner.addColorStop(0, "rgba(235, 245, 255, 0.95)");
    inner.addColorStop(0.18, "rgba(140, 190, 255, 0.55)");
    inner.addColorStop(0.7, "rgba(40, 70, 170, 0.35)");
    inner.addColorStop(1, "rgba(30, 50, 140, 0.2)");
    context.fillStyle = inner;
    context.beginPath();
    context.arc(g.cx, g.cy, g.radius, 0, Math.PI * 2);
    context.fill();
    context.lineWidth = 1 * g.scale;
    for (const [lat, lon] of hexes) {
      const corners = hexagon(lat, lon, 5.6, g);
      const depth = corners.reduce((sum, corner) => sum + corner[2], 0) / 6;
      if (depth < 0) continue;
      context.strokeStyle = `rgba(150, 190, 255, ${0.08 + 0.32 * depth})`;
      context.beginPath();
      corners.forEach(([x, y], index) => (index ? context.lineTo(x, y) : context.moveTo(x, y)));
      context.closePath();
      context.stroke();
    }
    context.shadowColor = "rgba(120, 170, 255, 0.9)";
    context.shadowBlur = 24 * g.scale;
    context.strokeStyle = "rgba(170, 205, 255, 0.85)";
    context.lineWidth = 2 * g.scale;
    context.beginPath();
    context.arc(g.cx, g.cy, g.radius, 0, Math.PI * 2);
    context.stroke();
    context.shadowBlur = 0;
  }

  function drawSpots(g, now) {
    spots = [];
    findings().forEach((finding, index) => {
      const [lat, lon] = place(index), corners = hexagon(lat, lon, 7.5, g);
      const depth = corners.reduce((sum, corner) => sum + corner[2], 0) / 6;
      if (depth < -0.05) return;
      const [r, gr, b] = COLORS[state(finding)], urgent = !finding.fixed && (finding.severity === "critical" || finding.severity === "high");
      const pulse = urgent && !calm ? (Math.sin(now / 260) + 1) / 2 : 0.4, on = index === selected;
      context.globalAlpha = 0.35 + 0.65 * Math.max(0, depth);
      context.shadowColor = `rgb(${r}, ${gr}, ${b})`;
      context.shadowBlur = (urgent ? 14 + 22 * pulse : 8) * g.scale;
      context.fillStyle = `rgba(${r}, ${gr}, ${b}, ${finding.fixed ? 0.35 : 0.45 + 0.35 * pulse})`;
      context.strokeStyle = `rgb(${r}, ${gr}, ${b})`;
      context.lineWidth = 1.6 * g.scale;
      context.beginPath();
      corners.forEach(([x, y], corner) => (corner ? context.lineTo(x, y) : context.moveTo(x, y)));
      context.closePath();
      context.fill();
      context.stroke();
      context.shadowBlur = 0;
      const xs = corners.map((corner) => corner[0]), ys = corners.map((corner) => corner[1]);  // the brackets around it
      const pad = (on ? 12 : 7) * g.scale, left = Math.min(...xs) - pad, right = Math.max(...xs) + pad;
      const top = Math.min(...ys) - pad, bottom = Math.max(...ys) + pad, arm = Math.min(right - left, bottom - top) * 0.3;
      context.lineWidth = (on ? 2.4 : 1.6) * g.scale;
      for (const [x, y, dx, dy] of [[left, top, 1, 1], [right, top, -1, 1], [left, bottom, 1, -1], [right, bottom, -1, -1]]) {
        context.beginPath();
        context.moveTo(x + dx * arm, y);
        context.lineTo(x, y);
        context.lineTo(x, y + dy * arm);
        context.stroke();
      }
      if (on) {
        context.fillStyle = "#fff";
        context.font = `600 ${11 * g.scale}px "JetBrains Mono", monospace`;
        context.textAlign = "center";
        context.fillText(finding.title.length > 34 ? `${finding.title.slice(0, 33)}…` : finding.title, (left + right) / 2, bottom + 16 * g.scale);
      }
      context.globalAlpha = 1;
      spots.push({ index, x: (left + right) / 2, y: (top + bottom) / 2, reach: Math.max(right - left, bottom - top) / 2 + 6 * g.scale, depth });
    });
  }

  function draw(now) {
    if (!view.isOpen()) return;
    frame = requestAnimationFrame(draw);
    const g = fit(), attacking = job?.status === "running";
    if (view3d.target) {
      const yawGap = ((view3d.target.yaw - view3d.yaw + Math.PI * 3) % (Math.PI * 2)) - Math.PI;
      view3d.yaw += yawGap * 0.1;
      view3d.pitch += (view3d.target.pitch - view3d.pitch) * 0.1;
      if (Math.abs(yawGap) < 0.002) view3d.target = null;
    } else if (!drag && !calm && selected < 0) {
      view3d.yaw += 0.0018;
    }
    context.clearRect(0, 0, g.width, g.height);
    const speed = attacking ? 2.6 : 1;
    drawStreaks(g, true, speed);
    drawShield(g);
    drawSpots(g, now);
    drawStreaks(g, false, speed);
  }

  // ---------- moving it ----------

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
    if (!pointers.has(event.pointerId)) return;
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pointers.size === 2 && pinch) {
      const [a, b] = [...pointers.values()], distance = Math.hypot(a.x - b.x, a.y - b.y);
      view3d.zoom = Math.max(0.6, Math.min(1.9, view3d.zoom * distance / pinch));
      pinch = distance;
      return;
    }
    if (!drag) return;
    const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
    drag.moved += Math.abs(dx) + Math.abs(dy);
    view3d.yaw += dx * 0.007;
    view3d.pitch = Math.max(-1.2, Math.min(1.2, view3d.pitch + dy * 0.007));
    view3d.target = null;
    drag.x = event.clientX;
    drag.y = event.clientY;
  });
  const release = (event) => {
    pointers.delete(event.pointerId);
    if (pointers.size < 2) pinch = 0;
    if (drag && drag.moved < 5 && pointers.size === 0) {
      const box = canvas.getBoundingClientRect(), scale = window.devicePixelRatio || 1;
      const x = (event.clientX - box.left) * scale, y = (event.clientY - box.top) * scale;
      const hit = spots.filter((spot) => spot.depth > 0 && Math.hypot(spot.x - x, spot.y - y) < spot.reach)
        .sort((a, b) => b.depth - a.depth)[0];
      choose(hit ? hit.index : -1);
    }
    if (pointers.size === 0) drag = null;
  };
  canvas.addEventListener("pointerup", release);
  canvas.addEventListener("pointercancel", release);
  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    view3d.zoom = Math.max(0.6, Math.min(1.9, view3d.zoom * (event.deltaY < 0 ? 1.08 : 1 / 1.08)));
  }, { passive: false });

  function command(name) {
    const count = findings().length;
    if (name === "next" && count) choose(selected + 1);
    else if (name === "previous" && count) choose(selected < 0 ? count - 1 : selected - 1);
    else if (name === "zoom_in") view3d.zoom = Math.min(1.9, view3d.zoom * 1.15);
    else if (name === "zoom_out") view3d.zoom = Math.max(0.6, view3d.zoom / 1.15);
    else if (name === "open" && count && selected < 0) choose(0);
    else if (name === "open" && selected >= 0) markFixed(selected, !findings()[selected].fixed);
    else if (name === "back") choose(-1);
    else if (name === "close") view.close();
  }

  function handleKey(event) {
    const keys = { ArrowRight: "next", ArrowLeft: "previous", "+": "zoom_in", "=": "zoom_in", "-": "zoom_out", Backspace: "back" };
    if (!keys[event.key]) return false;
    command(keys[event.key]);
    return true;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    problemLine.hidden = true;
    await act("shannon_start", { project: form.project.value, url: form.url.value });
  });
  $("#shannon-pick-project").onclick = async () => {  // the file window, starting in Nova Projects
    const result = await act("shannon_pick", { kind: "app" });
    if (result.picked && result.path) form.project.value = result.path;
  };
  stopButton.onclick = () => act("shannon_stop");
  $("#shannon-close").onclick = () => view.close();

  return {
    ...view,
    command,
    handleKey,
    job(next) {
      jobs = [next, ...jobs.filter((item) => item.id !== next.id)];
      running = next.status === "running" ? next.id : (running === next.id ? "" : running);
      if (next.status === "running" && job?.id !== next.id && (!job || job.status !== "running")) { job = next; log = []; selected = -1; }
      if (job?.id === next.id) { job = { ...job, ...next }; render(); }
      drawStrip();
    },
    line({ id, line }) {
      if (job?.id !== id) return;
      log.push(line);
      logLine.textContent = line;
    },
    ready({ problem }) {
      problemLine.hidden = !problem;
      problemLine.textContent = problem ? `Can't run Shannon here yet: ${problem}.` : "";
    },
  };
}
