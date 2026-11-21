// The Workplace projector: a ring pad at the bottom of the board throwing light up at every item on it. Each item
// gets its own beam with motes of light running up it, so the light follows the item wherever it's dragged. Drawn on
// one canvas behind the items; it only runs while the projector is on.

const BLUE = [90, 190, 255];
const MOTES_PER_BEAM = 4;
const POWER_UP_MS = 900;

export function createProjector(canvas, { targets }) {
  const context = canvas.getContext("2d");
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let running = false, poweredAt = 0, mood = "idle", level = 0, frameId = 0;
  const rgba = (alpha, [r, g, b] = BLUE) => `rgba(${r}, ${g}, ${b}, ${Math.max(0, Math.min(1, alpha))})`;

  function size() {
    const ratio = Math.min(devicePixelRatio || 1, 2), { width, height } = canvas.getBoundingClientRect();
    if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
    }
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    return { width, height };
  }

  // Where the light comes from: the middle of the pad, just above the ask bar.
  const origin = (width, height) => ({ x: width / 2, y: height - 58, rx: Math.min(230, width * 0.19) });

  function pad(o, power, time) {
    const ry = o.rx * 0.2;
    const glow = context.createRadialGradient(o.x, o.y, 0, o.x, o.y, o.rx * 1.25);
    glow.addColorStop(0, rgba(0.55 * power)); glow.addColorStop(0.45, rgba(0.16 * power)); glow.addColorStop(1, rgba(0));
    context.save();
    context.translate(o.x, o.y); context.scale(1, ry / o.rx); context.translate(-o.x, -o.y);
    context.fillStyle = glow;
    context.beginPath(); context.arc(o.x, o.y, o.rx * 1.25, 0, Math.PI * 2); context.fill();
    // Rings, some dashed and turning, like the projector pad in the reference.
    const rings = [[1, 2.2, [], 0], [0.92, 1, [18, 10], 1], [0.8, 3, [60, 24, 8, 24], -0.6], [0.66, 1, [4, 6], 0.9],
      [0.52, 2, [30, 14], -1.3], [0.36, 1.5, [], 0], [0.22, 2.5, [10, 8], 2]];
    for (const [scale, width, dash, speed] of rings) {
      context.setLineDash(dash.map((part) => part * scale));
      context.lineDashOffset = reduced ? 0 : -time * 0.03 * speed * 60;
      context.strokeStyle = rgba((0.35 + 0.5 * scale) * power, scale > 0.9 ? [150, 225, 255] : BLUE);
      context.lineWidth = width;
      context.beginPath(); context.arc(o.x, o.y, o.rx * scale * Math.min(1, power * 1.15), 0, Math.PI * 2); context.stroke();
    }
    context.setLineDash([]);
    context.restore();
    const core = context.createRadialGradient(o.x, o.y - 4, 0, o.x, o.y - 4, 26);
    core.addColorStop(0, `rgba(235, 250, 255, ${0.95 * power})`); core.addColorStop(1, rgba(0));
    context.fillStyle = core;
    context.beginPath(); context.arc(o.x, o.y - 4, 26, 0, Math.PI * 2); context.fill();
  }

  function cone(o, power, time, height) {
    // Wide soft rays fanning up from the pad, slowly swaying.
    const top = Math.max(40, height * 0.08);
    for (let index = 0; index < 9; index++) {
      const sway = reduced ? 0 : Math.sin(time * 0.0004 + index * 1.7) * 30;
      const spread = (index - 4) * o.rx * 0.32 + sway, width = o.rx * (0.18 + 0.1 * Math.sin(index * 2.3) ** 2);
      const gradient = context.createLinearGradient(0, o.y, 0, top);
      gradient.addColorStop(0, rgba(0.16 * power)); gradient.addColorStop(1, rgba(0));
      context.fillStyle = gradient;
      context.beginPath();
      context.moveTo(o.x - 10, o.y - 6); context.lineTo(o.x + spread - width, top); context.lineTo(o.x + spread + width, top); context.lineTo(o.x + 10, o.y - 6);
      context.fill();
    }
  }

  function beam(o, box, power, time, seed, bright) {
    const apex = { x: o.x, y: o.y - 8 };
    const edgeY = box.bottom < apex.y ? box.bottom : box.top;  // light lands on the side facing the pad
    const left = { x: box.left, y: edgeY }, right = { x: box.right, y: edgeY };
    const strength = power * (bright ? 1.7 : 1);
    const gradient = context.createLinearGradient(apex.x, apex.y, (left.x + right.x) / 2, edgeY);
    gradient.addColorStop(0, rgba(0.32 * strength)); gradient.addColorStop(1, rgba(0.06 * strength));
    context.fillStyle = gradient;
    context.beginPath(); context.moveTo(apex.x - 3, apex.y); context.lineTo(left.x, left.y); context.lineTo(right.x, right.y); context.lineTo(apex.x + 3, apex.y); context.fill();
    context.strokeStyle = rgba(0.5 * strength, [160, 225, 255]);
    context.lineWidth = bright ? 2 : 1.2;
    context.beginPath(); context.moveTo(left.x, left.y); context.lineTo(right.x, right.y); context.stroke();
    if (reduced) return;
    // Motes of light running up the beam to the item.
    for (let index = 0; index < MOTES_PER_BEAM; index++) {
      const phase = (time * 0.00045 * (1 + (seed % 5) * 0.12) + index / MOTES_PER_BEAM + seed * 0.37) % 1;
      const across = (Math.sin(seed * 12.9 + index * 78.2) * 0.5 + 0.5);
      const x = apex.x + (left.x + (right.x - left.x) * across - apex.x) * phase, y = apex.y + (edgeY - apex.y) * phase;
      const radius = 1.4 + 2.2 * phase;
      const mote = context.createRadialGradient(x, y, 0, x, y, radius * 4);
      mote.addColorStop(0, `rgba(230, 248, 255, ${0.9 * strength * Math.sin(phase * Math.PI)})`); mote.addColorStop(1, rgba(0));
      context.fillStyle = mote;
      context.beginPath(); context.arc(x, y, radius * 4, 0, Math.PI * 2); context.fill();
    }
  }

  function frame(time) {
    if (!running) return;
    const { width, height } = size();
    context.clearRect(0, 0, width, height);
    const busy = mood === "think" || mood === "speak" || mood === "listen";
    const breathe = reduced ? 1 : 0.88 + 0.12 * Math.sin(time * (busy ? 0.008 : 0.0025)) + level * 0.4;
    const power = Math.max(0, Math.min(1, (time - poweredAt) / POWER_UP_MS)) * breathe;  // the first frame's timestamp can precede poweredAt
    const o = origin(width, height);
    context.globalCompositeOperation = "lighter";
    cone(o, power, time, height);
    targets().forEach((target, index) => beam(o, target.box, power, time, index + 1, target.selected));
    pad(o, power, time);
    context.globalCompositeOperation = "source-over";
    frameId = requestAnimationFrame(frame);
  }

  return {
    start() { if (running) return; running = true; poweredAt = performance.now(); frameId = requestAnimationFrame(frame); },
    stop() { running = false; cancelAnimationFrame(frameId); const { width, height } = size(); context.clearRect(0, 0, width, height); },
    setMood(next, value = 0) { mood = next; level = Math.max(0, Math.min(1, value)); },
    origin: () => { const { width, height } = canvas.getBoundingClientRect(); return origin(width, height); },
  };
}
