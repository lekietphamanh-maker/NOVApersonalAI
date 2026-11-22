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

export function createGalaxy(root, { act, onOpenChange }) {
  const canvas = root.querySelector("canvas");
  const ctx = canvas.getContext("2d");
  const info = root.querySelector(".galaxy-info");
  const infoTitle = info.querySelector("h3");
  const infoKind = info.querySelector(".kind");
  const infoBody = info.querySelector("p");
  const search = root.querySelector(".galaxy-search input");
  mountWhatCanIDo(root.querySelector(".galaxy-hud"), "galaxy", { onPhrase: askPhrase });
  const countEl = root.querySelector(".galaxy-title small");
  let open = false, nodes = [], edges = [], accent = "255, 176, 64";
  let camYaw = 0, camPitch = 0.3, camDist = 90, targetYaw = 0, targetPitch = 0.3, targetDist = 90;
  let dragStart = null, dragYaw = 0, dragPitch = 0, autoSpin = true;
  let selected = null, hovered = null, flyTarget = null, flyFrom = null, flyAt = 0;
  let bgStars = [], w = 0, h = 0, ratio = 1, frameId = 0;

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
        z: r * Math.cos(phi), brightness: 0.15 + Math.random() * 0.4 });
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
  function drawFrame() {
    if (!open) return;
    frameId = requestAnimationFrame(drawFrame);
    ctx.clearRect(0, 0, w, h);

    // auto-spin
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

    // background stars
    for (const star of bgStars) {
      const p = project(star.x, star.y, star.z);
      if (!p || p.z < 2) continue;
      const alpha = star.brightness * Math.min(1, p.z / 60);
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

    for (const { node, sx, sy, scale, z } of projected) {
      const r = Math.max(1.5, node.size * 3.5 * scale);
      const color = COLORS[node.kind] || accent;
      const isSelected = selected === node.id;
      const isHovered = hovered === node.id;

      // glow
      if (r > 2) {
        const glow = ctx.createRadialGradient(sx, sy, 0, sx, sy, r * 3);
        glow.addColorStop(0, `rgba(${color}, ${isSelected ? 0.5 : 0.2})`);
        glow.addColorStop(1, `rgba(${color}, 0)`);
        ctx.fillStyle = glow;
        ctx.beginPath(); ctx.arc(sx, sy, r * 3, 0, TAU); ctx.fill();
      }

      // core
      ctx.fillStyle = `rgba(${color}, ${isSelected ? 1 : 0.85})`;
      ctx.beginPath(); ctx.arc(sx, sy, r, 0, TAU); ctx.fill();

      // ring on selected/hovered
      if (isSelected || isHovered) {
        ctx.strokeStyle = `rgba(${color}, 0.7)`;
        ctx.lineWidth = 1.2;
        ctx.beginPath(); ctx.arc(sx, sy, r + 4, 0, TAU); ctx.stroke();
      }

      // label
      if (r > 3 || isSelected || isHovered) {
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
      const r = Math.max(6, node.size * 3.5 * p.scale + 8);
      if (d < r && d < bestDist) { best = node; bestDist = d; }
    }
    return best;
  }

  canvas.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    dragStart = { x: e.clientX, y: e.clientY }; dragYaw = targetYaw; dragPitch = targetPitch;
    autoSpin = false;
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
    autoSpin = false;
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
    flyAt = performance.now();
    autoSpin = false;
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
    nodes = (data.nodes || []).map((n) => ({ ...n, _hidden: false }));
    edges = data.edges || [];
    countEl.textContent = `${nodes.length} nodes · ${edges.length} connections`;
  }

  function openGalaxy() {
    if (open) return;
    open = true; root.classList.add("open");
    resize(); seedStars();
    frameId = requestAnimationFrame(drawFrame);
    autoSpin = true; targetYaw = 0; targetPitch = 0.3; targetDist = 90;
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
