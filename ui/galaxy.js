// Knowledge Galaxy: a 3D star map of everything Nova knows. Wiki topics are bright stars, memory facts
// are small green sparks, Archmancer skills are blue, raw sources are purple. [[links]] between topics
// are luminous threads. Click a star to read it; type to search; the camera flies to a source when Nova
// quotes it. All rendering is canvas 2D with a manual perspective projection — no Three.js dependency.

import { askPhrase, mountWhatCanIDo } from "./whatcanido.js";

const TAU = Math.PI * 2;
const COLORS = { wiki: null, fact: "91, 224, 160", skill: "140, 160, 255", source: "158, 123, 189" };
const KINDS = { wiki: "Topic", fact: "Memory", skill: "Skill", source: "Source" };
const FOV = 800;
const STAR_COUNT = 280;
const FLY_MS = 1200;
const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

// How long a star's twinkle takes to breathe, and how long after the owner last
// touched the galaxy the slow spin comes back on its own (4 s of stillness).
export const TWINKLE_PERIOD_MS = 650;
export const AMBIENT_SPIN_IDLE_MS = 4000;

// One star's brightness at a moment: a gentle sine around its base brightness, so the
// galaxy shimmers instead of sitting frozen. Pure, so the tests can pin it down.
export function twinkleAlpha(base, nowMs, phase) {
  return base * (0.72 + 0.28 * Math.sin(nowMs / TWINKLE_PERIOD_MS + phase));
}

// The slow spin resumes by itself once the owner has left the galaxy alone for a
// while — dragging, zooming or flying to a star pauses it, it never stops for good.
export function shouldAmbientSpin({ lastInteractAt, nowMs, dragging, flying, reducedMotion }) {
  return !dragging && !flying && !reducedMotion && nowMs - lastInteractAt > AMBIENT_SPIN_IDLE_MS;
}
// repulsion passes, each pushing too-close pairs apart, then back onto the sphere.
// Exported for tests; the galaxy calls it for real clouds (20+ nodes) on load.
export function relaxGalaxyNodes(nodes, radius, iterations = 10) {
  const count = nodes.length;
  if (count < 2 || radius <= 0) return nodes;
  const minDist = 0.75 * radius * Math.sqrt((4 * Math.PI) / count);
  for (let step = 0; step < iterations; step++) {
    for (let i = 0; i < count; i++) {
      for (let j = i + 1; j < count; j++) {
        const a = nodes[i], b = nodes[j];
        const dx = b.x - a.x, dy = b.y - a.y, dz = b.z - a.z;
        const d = Math.hypot(dx, dy, dz);
        if (d >= minDist || d === 0) continue;
        const push = (minDist - d) / 2 / d;
        a.x -= dx * push; a.y -= dy * push; a.z -= dz * push;
        b.x += dx * push; b.y += dy * push; b.z += dz * push;
      }
    }
    for (const node of nodes) {
      const len = Math.hypot(node.x, node.y, node.z) || 1;
      node.x = (node.x / len) * radius; node.y = (node.y / len) * radius; node.z = (node.z / len) * radius;
    }
  }
  return nodes;
}

export function createGalaxy(root, { act, onOpenChange }) {
  const canvas = root.querySelector("canvas");
  const ctx = canvas.getContext("2d");
  const info = root.querySelector(".galaxy-info");
  const infoTitle = info.querySelector("h3");
  const infoKind = info.querySelector(".kind");
  const infoBody = info.querySelector("p");
  const search = root.querySelector(".galaxy-search input");
  const labelsBtn = root.querySelector(".galaxy-labels");
  // The panel is the only in-flow child of the full-screen HUD, so it would sit at the
  // very top-left, on top of the KNOWLEDGE GALAXY title; the stylesheet pins it below
  // the title instead, and its own margin is cleared so the two can never collide.
  const whatPanel = mountWhatCanIDo(root.querySelector(".galaxy-hud"), "galaxy", { onPhrase: askPhrase });
  if (whatPanel) whatPanel.style.marginTop = "0";
  const countEl = root.querySelector(".galaxy-title small");
  let open = false, nodes = [], edges = [], accent = "255, 176, 64";
  let camYaw = 0, camPitch = 0.3, camDist = 90, targetYaw = 0, targetPitch = 0.3, targetDist = 90;
  let dragStart = null, dragYaw = 0, dragPitch = 0, autoSpin = true, lastInteractAt = 0;
  let selected = null, hovered = null, flyTarget = null, flyFrom = null, flyAt = 0;
  // Labels are on by default: Keith changed his mind from hover-only — names always show.
  let showLabels = true, bgStars = [], w = 0, h = 0, ratio = 1, frameId = 0;

  if (labelsBtn) {
    // One source of truth: the button starts in the same state as the labels.
    labelsBtn.setAttribute("aria-pressed", String(showLabels));
    labelsBtn.classList.toggle("on", showLabels);
    labelsBtn.addEventListener("click", () => {
      showLabels = !showLabels;
      labelsBtn.setAttribute("aria-pressed", String(showLabels));
      labelsBtn.classList.toggle("on", showLabels);
    });
  }

  function resize() {
    const rect = canvas.getBoundingClientRect();
    ratio = Math.min(devicePixelRatio || 1, 2);
    w = rect.width; h = rect.height;
    canvas.width = Math.round(w * ratio); canvas.height = Math.round(h * ratio);
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  }

  function seedStars() {
    bgStars = [];
    for (let i = 0; i < STAR_COUNT; i++) {
      const theta = Math.random() * TAU, phi = Math.acos(2 * Math.random() - 1);
      const r = 120 + Math.random() * 80;
      bgStars.push({ x: r * Math.sin(phi) * Math.cos(theta), y: r * Math.sin(phi) * Math.sin(theta),
        z: r * Math.cos(phi), brightness: 0.15 + Math.random() * 0.4, phase: Math.random() * TAU });
    }
  }

  // --- projection ---
  function project(px, py, pz) {
    const cy = Math.cos(camYaw), sy = Math.sin(camYaw), cp = Math.cos(camPitch), sp = Math.sin(camPitch);
    let x = px * cy - pz * sy;
    let z1 = px * sy + pz * cy;
    let y = py * cp - z1 * sp;
    let z = py * sp + z1 * cp + camDist;
    if (z < 1) return null;
    const scale = FOV / z;
    return { sx: w / 2 + x * scale, sy: h / 2 - y * scale, scale, z };
  }

  // --- drawing ---
  // A star is a small 4-point sparkle, not a big filled disc: the old circles (up to ~50px
  // across) overlapped into one unreadable blob. Radius is capped so even the most important
  // topic stays a star, not a moon.
  function starRadius(node, scale) {
    return Math.min(8, Math.max(1.5, node.size * 0.9 * scale));
  }

  function drawStar(cx, cy, r, color, alpha) {
    const inner = r * 0.32;
    ctx.beginPath();
    for (let i = 0; i < 8; i++) {
      const rad = i % 2 === 0 ? r : inner;
      const angle = (i / 8) * TAU - Math.PI / 2;
      const x = cx + Math.cos(angle) * rad, y = cy + Math.sin(angle) * rad;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.closePath();
    ctx.fillStyle = `rgba(${color}, ${alpha})`;
    ctx.fill();
    // bright core so the star reads at a glance
    ctx.fillStyle = `rgba(255, 255, 255, ${Math.min(0.9, alpha + 0.15)})`;
    ctx.beginPath(); ctx.arc(cx, cy, Math.max(0.7, r * 0.25), 0, TAU); ctx.fill();
  }

  function drawFrame() {
    if (!open) return;
    frameId = requestAnimationFrame(drawFrame);
    ctx.clearRect(0, 0, w, h);
    const nowMs = performance.now();

    // auto-spin: it pauses while the owner drags, zooms or flies somewhere, then
    // comes back on its own after a few seconds of stillness, so the galaxy never
    // sits frozen — and it stays off entirely for reduced motion.
    if (shouldAmbientSpin({ lastInteractAt, nowMs, dragging: !!dragStart, flying: !!flyTarget,
        reducedMotion: reduced() })) autoSpin = true;
    if (autoSpin && !dragStart && !flyTarget && !reduced()) {
      targetYaw += 0.0008;
    }

    // fly-to animation
    if (flyTarget) {
      const t = Math.min(1, (performance.now() - flyAt) / FLY_MS);
      const ease = 1 - Math.pow(1 - t, 3);
      camYaw = flyFrom.yaw + (flyTarget.yaw - flyFrom.yaw) * ease;
      camPitch = flyFrom.pitch + (flyTarget.pitch - flyFrom.pitch) * ease;
      camDist = flyFrom.dist + (flyTarget.dist - flyFrom.dist) * ease;
      if (t >= 1) flyTarget = null;
    } else {
      camYaw += (targetYaw - camYaw) * 0.08;
      camPitch += (targetPitch - camPitch) * 0.08;
      camDist += (targetDist - camDist) * 0.08;
    }

    // background stars: each one breathes on its own phase, so the sky shimmers
    // even when the camera is still (frozen for reduced motion).
    for (const star of bgStars) {
      const p = project(star.x, star.y, star.z);
      if (!p || p.z < 2) continue;
      const alpha = (reduced() ? star.brightness : twinkleAlpha(star.brightness, nowMs, star.phase))
        * Math.min(1, p.z / 60);
      ctx.globalAlpha = alpha;
      ctx.fillStyle = "#c8d4e0";
      ctx.beginPath(); ctx.arc(p.sx, p.sy, Math.max(0.5, 1.2 * p.scale * 0.3), 0, TAU); ctx.fill();
    }
    ctx.globalAlpha = 1;

    // edges (look the ends up once per frame, not once per edge)
    const byId = new Map(nodes.map((node) => [node.id, node]));
    for (const edge of edges) {
      const sn = byId.get(edge.source);
      const tn = byId.get(edge.target);
      if (!sn || !tn || sn._hidden || tn._hidden) continue;
      const p1 = project(sn.x, sn.y, sn.z);
      const p2 = project(tn.x, tn.y, tn.z);
      if (!p1 || !p2) continue;
      const alpha = Math.min(0.25, 6 / (p1.z + p2.z));
      ctx.strokeStyle = `rgba(${accent}, ${alpha})`;
      ctx.lineWidth = Math.max(0.3, 0.6 * Math.min(p1.scale, p2.scale));
      ctx.beginPath(); ctx.moveTo(p1.sx, p1.sy); ctx.lineTo(p2.sx, p2.sy); ctx.stroke();
    }

    // nodes sorted back-to-front
    const projected = [];
    for (const node of nodes) {
      if (node._hidden) continue;
      const p = project(node.x, node.y, node.z);
      if (!p) continue;
      projected.push({ node, ...p });
    }
    projected.sort((a, b) => b.z - a.z);

    // Labels are on by default: every star's name shows, with near-duplicates
    // skipped so neighbours don't print on top of each other. The hovered and
    // selected stars always get theirs; the Labels button turns them all off.
    const labeled = [];
    function labelClear(sx, sy) {
      return !labeled.some((at) => Math.abs(at.sx - sx) < 30 && Math.abs(at.sy - sy) < 14);
    }

    for (const { node, sx, sy, scale, z } of projected) {
      const r = starRadius(node, scale);
      const color = COLORS[node.kind] || accent;
      const isSelected = selected === node.id;
      const isHovered = hovered === node.id;

      // glow
      if (r > 2) {
        const glow = ctx.createRadialGradient(sx, sy, 0, sx, sy, r * 2.5);
        glow.addColorStop(0, `rgba(${color}, ${isSelected ? 0.45 : 0.18})`);
        glow.addColorStop(1, `rgba(${color}, 0)`);
        ctx.fillStyle = glow;
        ctx.beginPath(); ctx.arc(sx, sy, r * 2.5, 0, TAU); ctx.fill();
      }

      // star: a gentle twinkle on its own phase, like the background stars
      // (frozen for reduced motion).
      const starAlpha = isSelected ? 1 : 0.85;
      drawStar(sx, sy, r, color, reduced() ? starAlpha : starAlpha * twinkleAlpha(1, nowMs, node._twinkle ?? 0));

      // ring on selected/hovered
      if (isSelected || isHovered) {
        ctx.strokeStyle = `rgba(${color}, 0.7)`;
        ctx.lineWidth = 1.2;
        ctx.beginPath(); ctx.arc(sx, sy, r + 4, 0, TAU); ctx.stroke();
      }

      // label
      const showLabel = isSelected || isHovered || (showLabels && labelClear(sx, sy));
      if (showLabel) {
        labeled.push({ sx, sy });
        const fontSize = Math.max(8, Math.min(12, 10 * scale));
        ctx.font = `600 ${fontSize}px "Segoe UI", system-ui, sans-serif`;
        ctx.fillStyle = `rgba(255, 255, 255, ${Math.min(0.9, scale * 1.2)})`;
        ctx.textAlign = "center";
        ctx.fillText(node.label.length > 24 ? node.label.slice(0, 22) + "..." : node.label, sx, sy - r - 6);
      }
    }
  }

  // --- interaction ---
  function nodeAt(mx, my) {
    let best = null, bestDist = 20;
    for (const node of nodes) {
      if (node._hidden) continue;
      const p = project(node.x, node.y, node.z);
      if (!p) continue;
      const d = Math.hypot(p.sx - mx, p.sy - my);
      const r = Math.max(8, starRadius(node, p.scale) + 6);
      if (d < r && d < bestDist) { best = node; bestDist = d; }
    }
    return best;
  }

  canvas.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    dragStart = { x: e.clientX, y: e.clientY }; dragYaw = targetYaw; dragPitch = targetPitch;
    autoSpin = false; lastInteractAt = performance.now();
  });
  canvas.addEventListener("pointermove", (e) => {
    if (dragStart) {
      targetYaw = dragYaw + (e.clientX - dragStart.x) * 0.005;
      targetPitch = Math.max(-1.4, Math.min(1.4, dragPitch + (e.clientY - dragStart.y) * 0.005));
    } else {
      const hit = nodeAt(e.clientX - canvas.getBoundingClientRect().left, e.clientY - canvas.getBoundingClientRect().top);
      hovered = hit ? hit.id : null;
      canvas.style.cursor = hit ? "pointer" : "grab";
    }
  });
  canvas.addEventListener("pointerup", (e) => {
    if (dragStart && Math.hypot(e.clientX - dragStart.x, e.clientY - dragStart.y) < 5) {
      const rect = canvas.getBoundingClientRect();
      const hit = nodeAt(e.clientX - rect.left, e.clientY - rect.top);
      selectNode(hit);
    }
    dragStart = null;
  });
  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    targetDist = Math.max(20, Math.min(200, targetDist + e.deltaY * 0.06));
    autoSpin = false; lastInteractAt = performance.now();
  }, { passive: false });

  function selectNode(node) {
    if (!node) { selected = null; info.classList.remove("show"); return; }
    selected = node.id;
    infoTitle.textContent = node.label;
    infoKind.textContent = KINDS[node.kind] || node.kind;
    infoBody.textContent = node.excerpt || "(no content)";
    info.classList.add("show");
  }

  function flyTo(nodeId) {
    const node = nodes.find((n) => n.id === nodeId);
    if (!node) return;
    const yz = Math.sqrt(node.x * node.x + node.z * node.z);
    flyFrom = { yaw: camYaw, pitch: camPitch, dist: camDist };
    flyTarget = { yaw: Math.atan2(node.x, node.z), pitch: Math.atan2(node.y, yz) * 0.5, dist: 50 };
    // The camera stays where it flew to: without this the ease-back below would drift
    // the view away from the search hit within a second of arriving.
    targetYaw = flyTarget.yaw; targetPitch = flyTarget.pitch; targetDist = flyTarget.dist;
    flyAt = performance.now();
    autoSpin = false; lastInteractAt = performance.now();
    selectNode(node);
  }

  // search
  search.addEventListener("input", () => {
    const q = search.value.trim().toLowerCase();
    if (!q) { nodes.forEach((n) => n._hidden = false); return; }
    for (const node of nodes) node._hidden = !node.label.toLowerCase().includes(q) && !(node.excerpt || "").toLowerCase().includes(q);
    const hit = nodes.find((n) => !n._hidden);
    if (hit) flyTo(hit.id);
  });

  root.querySelector(".galaxy-close").addEventListener("click", () => close());

  // --- public API ---
  function loadData(data) {
    nodes = (data.nodes || []).map((n, index) => ({ ...n, _hidden: false, _twinkle: (index * 1.7) % TAU }));
    edges = data.edges || [];
    // A real galaxy has a hundred stars: spread the cloud a little wider with the count, and
    // push apart any pair that landed too close, so stars keep a minimum distance. Small
    // test sets keep their exact positions (the regression test relies on them).
    if (nodes.length >= 20) {
      const radius = 40 * Math.max(1, Math.min(1.6, Math.sqrt(nodes.length / 60)));
      for (const node of nodes) {
        const len = Math.hypot(node.x, node.y, node.z) || 1;
        node.x = (node.x / len) * radius; node.y = (node.y / len) * radius; node.z = (node.z / len) * radius;
      }
      relaxGalaxyNodes(nodes, radius);
    }
    countEl.textContent = `${nodes.length} nodes · ${edges.length} connections`;
  }

  function openGalaxy() {
    if (open) return;
    open = true; root.classList.add("open");
    resize(); seedStars();
    frameId = requestAnimationFrame(drawFrame);
    autoSpin = true; lastInteractAt = performance.now(); targetYaw = 0; targetPitch = 0.3; targetDist = 90;
    act("galaxy_data", {});
    onOpenChange(true);
    window.addEventListener("resize", resize);
  }

  function close() {
    if (!open) return;
    open = false; root.classList.remove("open");
    cancelAnimationFrame(frameId);
    info.classList.remove("show");
    search.value = "";
    onOpenChange(false);
    window.removeEventListener("resize", resize);
  }

  return {
    isOpen: () => open,
    open: openGalaxy,
    close,
    loadData,
    flyTo,
  };
}
