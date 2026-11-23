// Shannon's shield: your app as a hexagon shield with a glowing heart, Shannon's attacks swirling around it. Each hole
// it proved is a weak spot on the shell in brackets: red and pulsing for critical and high (look at these first), amber
// for medium, yellow for low. Mark one fixed and it calms to green. Drag to turn, scroll or pinch to zoom, click a
// spot; arrows, + and -, and webcam gestures work too. Stages, the log and past checks run along the bottom.

import { h, when, screen, renderStrip, openReportPanel, pollSelfUpdate, UPDATE_STAGE_LABELS } from "./lab.js";
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
  let simKind = "web", simHits = [], simTimers = [];
  const SIM_KINDS = ["app", "file", "web"];
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

  // ---------- Simulate attack: target picker below the shield, red blocks on it, AiSOC's verdict ----------
  // Built here, not in index.html: the picker sits between the shield and the past checks, and only this file
  // may change for the Shannon screen's layout.

  const simStatus = h("p", { class: "muted small" });
  const simError = h("p", { class: "muted small", style: "color:var(--warn)" });
  const simResult = h("div", {});
  const simInput = h("input", { class: "field", style: "flex:1;min-width:180px", placeholder: "Local address (localhost:3000)",
    maxlength: "300", "aria-label": "Simulation target" });
  const simBrowse = h("button", { class: "box small", type: "button", onclick: pickSimTarget }, "Browse…");
  const simButton = h("button", { class: "box small on", type: "button", onclick: simulate }, "Simulate attack");
  const simModes = SIM_KINDS.map((kind) => h("button", {
    class: `box small${kind === simKind ? " on" : ""}`, type: "button", onclick: () => setSimKind(kind),
  }, kind === "app" ? "App" : kind === "file" ? "File" : "Web (local)"));
  const simBox = h("div", { style: "padding:12px 22px;border-top:1px solid var(--line)" },
    h("h4", { style: "margin:0 0 4px;color:#fff;font:600 13px/1.3 var(--mono)" }, "Simulate attack"),
    h("p", { class: "muted small", style: "margin:0 0 8px" },
      "A scripted attack on your own app, file or local address, triaged by AiSOC. Nothing really runs: the same local-only checks as a real Shannon run apply, and anything else is refused."),
    h("div", { class: "row wrap", style: "margin-top:0" }, ...simModes),
    h("div", { class: "row wrap" }, simInput, simBrowse, simButton),
    simStatus, simError, simResult);
  root.insertBefore(simBox, root.querySelector(".lab-bottom"));
  simBrowse.hidden = true;  // the default mode is Web (local), a typed address — no file window until App/File is picked

  // ---------- Attack Nova herself: one click, no target to pick ----------
  // The same Simulate attack machinery (AiSOC triage, shield blocks, verdict, report, Update now), but the
  // target is Nova herself — her own code and her own running screen. Update now fixes Nova's own code.

  const selfStatus = h("p", { class: "muted small" });
  const selfError = h("p", { class: "muted small", style: "color:var(--warn)" });
  const selfResult = h("div", {});
  const selfButton = h("button", { class: "box small on", type: "button", onclick: attackSelf }, "Attack Nova herself");
  const selfBox = h("div", { style: "padding:12px 22px;border-top:1px solid var(--line)" },
    h("h4", { style: "margin:0 0 4px;color:#fff;font:600 13px/1.3 var(--mono)" }, "Attack Nova herself"),
    h("p", { class: "muted small", style: "margin:0 0 8px" },
      "One click: Shannon attacks Nova herself — her own code and her own running screen — and Update now fixes what it finds. No real exploit runs, nothing leaves this PC, and nothing is installed from anywhere."),
    h("p", { class: "muted small", style: "margin:0 0 8px" },
      "Fixes go into Nova's own code, and Nova needs a restart to pick them up."),
    h("div", { class: "row wrap" }, selfButton),
    selfStatus, selfError, selfResult);
  root.insertBefore(selfBox, root.querySelector(".lab-bottom"));

  function clearSelf() {
    clearSimTimers();
    selfStatus.textContent = "";
    selfError.textContent = "";
    selfResult.replaceChildren();
  }

  async function attackSelf() {
    clearSelf();
    simHits = [];
    selfStatus.textContent = "Attacking Nova herself…";
    selfButton.disabled = true;
    const result = await act("shannon_simulate", { kind: "self" });
    selfButton.disabled = false;
    if (!result.ok) {
      selfStatus.textContent = "";
      selfError.textContent = result.error || "The self-attack didn't run.";
      return;
    }
    job = result.job;  // the self-attack's proven holes become the shield's spots, like any other check
    log = [];
    selected = -1;
    drawStrip();
    render();
    const steps = result.steps || [];
    steps.forEach((step, index) => {  // a red block lands on the shield as each attack step lands
      simTimers.push(setTimeout(() => {
        if (step.landed) {  // its place is fixed at landing time, not recomputed every frame
          const [lat, lon] = place(simHits.length, 12);
          simHits.push({ index: simHits.length, lat, lon });
        }
        selfStatus.textContent = `${step.technique}: ${step.landed ? "landed" : "blocked"} — AiSOC: ${step.verdict}`;
      }, index * 500));
    });
    simTimers.push(setTimeout(() => showSimResult(result,
      { status: selfStatus, error: selfError, result: selfResult, clear: clearSelf }), steps.length * 500 + 150));
  }

  function clearSimTimers() {
    for (const timer of simTimers) clearTimeout(timer);
    simTimers = [];
  }

  function clearSim() {
    clearSimTimers();
    simHits = [];
    simStatus.textContent = "";
    simError.textContent = "";
    simResult.replaceChildren();
  }

  function setSimKind(kind) {
    simKind = kind;
    simModes.forEach((button, index) => button.classList.toggle("on", SIM_KINDS[index] === kind));
    simInput.placeholder = kind === "app" ? "Project folder (under Nova Projects)"
      : kind === "file" ? "File path (in your user folder)" : "Local address (localhost:3000)";
    simBrowse.hidden = kind === "web";  // a web address is typed, not picked from a file window
    if (kind === "app") simInput.setAttribute("list", "shannon-projects");
    else simInput.removeAttribute("list");
    simInput.value = "";
    simError.textContent = "";
  }

  async function pickSimTarget() {  // the file window: click the project folder or file, its path lands in the box
    const result = await act("shannon_pick", { kind: simKind });
    if (result.picked && result.path) simInput.value = result.path;
  }

  async function simulate() {
    clearSim();
    simStatus.textContent = "Simulating…";
    simButton.disabled = true;
    const result = await act("shannon_simulate", { kind: simKind, target: simInput.value.trim() });
    simButton.disabled = false;
    if (!result.ok) {
      simStatus.textContent = "";
      simError.textContent = result.error || "The simulation didn't run.";
      return;
    }
    job = result.job;  // the simulation's incidents become the shield's spots, like a real check's findings
    log = [];
    selected = -1;
    drawStrip();
    render();
    const steps = result.steps || [];
    steps.forEach((step, index) => {  // a red block lands on the shield as each attack step lands
      simTimers.push(setTimeout(() => {
        if (step.landed) {  // its place is fixed at landing time, not recomputed every frame
          const [lat, lon] = place(simHits.length, 12);
          simHits.push({ index: simHits.length, lat, lon });
        }
        simStatus.textContent = `${step.technique}: ${step.landed ? "landed" : "blocked"} — AiSOC: ${step.verdict}`;
      }, index * 500));
    });
    simTimers.push(setTimeout(() => showSimResult(result), steps.length * 500 + 150));
  }

  function showSimResult(result, els = { status: simStatus, error: simError, result: simResult, clear: clearSim }) {
    const verdict = result.verdict || {};
    const color = verdict.verdict === "needs review" ? "rgb(255, 45, 85)"
      : verdict.verdict === "mitigated" ? "rgb(255, 181, 71)" : "rgb(92, 242, 176)";
    els.status.textContent = "";
    const open = (result.job?.findings || []).filter((finding) => !finding.fixed).length;
    const updateButton = open ? h("button", { class: "box small on", type: "button" },
      `Update now (${open} fix${open === 1 ? "" : "es"})`) : null;
    if (updateButton) {
      updateButton.onclick = () => startUpdate(updateButton, els.status, els.error, result.job?.id);
    }
    els.result.replaceChildren(
      h("span", { class: "lab-tag", style: `color:${color};border-color:${color}` }, `AiSOC: ${verdict.verdict || "resolved"}`),
      verdict.rationale ? h("p", { class: "muted small" }, verdict.rationale) : null,
      h("p", { class: "muted small" }, `Report: ${result.report || ""}`),
      result.kind === "self" && updateButton ? h("p", { class: "muted small" },
        "These fixes go into Nova's own code. Nova needs a restart to pick them up.") : null,
      h("div", { class: "row wrap" },
        h("button", { class: "box small on", type: "button", onclick: () => openSimReport(result) }, "Open report"),
        updateButton,
        h("button", { class: "box small", type: "button", onclick: () => { els.clear(); render(); } }, "Clear")));
  }

  // ---------- the full report on screen, and "Update now" below it ----------
  async function openReport(jobId, title, action) {
    const result = await act(action, { id: jobId });
    const current = job?.id === jobId ? job : null;
    const open = (current?.findings || []).filter((finding) => !finding.fixed).length;
    const progress = h("p", { class: "report-progress", hidden: true });
    const note = h("p", { class: "report-note" });
    const updateButton = open ? h("button", { class: "box small on", type: "button" },
      `Update now (${open} fix${open === 1 ? "" : "es"})`) : null;
    if (updateButton) updateButton.onclick = () => startUpdate(updateButton, progress, note, jobId);
    openReportPanel(root, {
      title,
      text: result.ok ? result.text : (result.error || "The report isn't there any more."),
      footer: result.ok ? [updateButton, progress, note].filter(Boolean) : [],
    });
  }

  function openFullReport() {
    openReport(job.id, job.title || "Full report", "shannon_report_text");
  }

  function openSimReport(result) {
    openReport(result.job?.id, result.job?.title || "Simulated attack — full report", "shannon_simulate_report_text");
  }

  async function startUpdate(button, progressEl, noteEl, jobId) {
    button.disabled = true;
    progressEl.textContent = "Starting the update…";
    const started = await act("shannon_update_now", { id: jobId });
    if (!started?.ok) {
      progressEl.textContent = started?.error || "The update didn't start.";
      button.disabled = false;
      return;
    }
    if (!started.token_set) {
      noteEl.textContent = "No GitHub token yet — the fixes and tests run anyway, but the push waits. "
        + "Add one in Settings → Self-update · GitHub (github.com/settings/tokens → classic token → repo scope).";
    }
    pollSelfUpdate(act, (state) => {
      const running = state.steps.find((step) => step.status === "running");
      const label = UPDATE_STAGE_LABELS[state.stage] || state.stage;
      if (state.stage === "done") {
        progressEl.textContent = state.summary || "Done.";
        noteEl.textContent = "";
      } else if (state.stage === "failed") {
        progressEl.textContent = state.error || "The update stopped.";
        button.disabled = false;
      } else {
        progressEl.textContent = `${label}…${running?.detail ? ` ${running.detail}` : ""}`
          + (state.fix_round ? ` (fix round ${state.fix_round})` : "");
      }
    });
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
    clearSim();
    clearSelf();
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

  function drawHits(g, now) {  // one red block on the shield per landed attack step; cleared on a new run
    for (const hit of simHits) {
      const [x, y, depth] = project(hit.lat, hit.lon, g);
      if (depth < -0.05) continue;
      const pulse = calm ? 0.4 : (Math.sin(now / 260) + 1) / 2, size = 9 * g.scale;
      context.globalAlpha = 0.35 + 0.65 * Math.max(0, depth);
      context.shadowColor = "rgb(255, 45, 85)";
      context.shadowBlur = (10 + 18 * pulse) * g.scale;
      context.fillStyle = `rgba(255, 45, 85, ${0.55 + 0.35 * pulse})`;
      context.fillRect(x - size / 2, y - size / 2, size, size);
      context.shadowBlur = 0;
      context.globalAlpha = 1;
    }
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
    drawHits(g, now);
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
      if (next.status === "running" && job?.id !== next.id && (!job || job.status !== "running")) { job = next; log = []; selected = -1; clearSim(); clearSelf(); }
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
