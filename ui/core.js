// Nova's core. Asleep: a glowing line with orbits around it. Awake: the line opens into a holographic orb
// of circuit traces (an inner core, the sphere, outer shell bands, an equator ribbon and a diagonal streak)
// that turns in a loop, glows, and scatters and brightens with your voice.
// Modes: offline, idle, armed (mic on, waiting for "Nova"), listen, think, speak, error.

const TAU = Math.PI * 2;
const LABELS = { offline: "OFFLINE", idle: "ASLEEP", armed: "SAY “HEY NOVA”", listen: "LISTENING",
  think: "THINKING", speak: "SPEAKING", error: "ERROR" };
const TAGLINE = ["Neural", "Offline", "Voice", "Assistant"];
// [glow, spin, voice scatter, scanning band]
const MOODS = { offline: [0.25, 0.15, 0, 0], idle: [0.55, 0.35, 0, 0], armed: [0.75, 0.5, 0, 0],
  listen: [1, 0.8, 1, 0], think: [0.9, 2.2, 0.15, 1], speak: [1, 0.9, 0.7, 0], error: [0.7, 0.3, 0, 0] };
const AWAKE = new Set(["listen", "think", "speak"]);
const LINGER_MS = 3500; // stay open a moment after Nova finishes, then fold back into the line

function seeded(seed) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let value = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    value = (value + Math.imul(value ^ (value >>> 7), 61 | value)) ^ value;
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
}

const onSphere = (lat, lon, radius) => [Math.cos(lat) * Math.sin(lon) * radius, -Math.sin(lat) * radius, Math.cos(lat) * Math.cos(lon) * radius];

// Circuit traces on a sphere: runs along the latitude with small jogs and zigzags, like a circuit board.
function traces(random, { count, radius, lat: [latMin, latMax], lon: [lonMin, lonMax], steps: [fewest, most], zigzag, gaps = false }) {
  const list = [];
  let attempts = 0;
  while (list.length < count && attempts++ < count * 6) {
    let lat = latMin + random() * (latMax - latMin);
    let lon = lonMin + random() * (lonMax - lonMin);
    // Patchy, like the reference: some areas stay dark.
    if (gaps && Math.sin(3 * lat + 1.3) * Math.sin(4 * lon) + 0.5 * Math.sin(5 * lon + 2 * lat) < -0.35) continue;
    const direction = random() < 0.5 ? -1 : 1;
    const steps = fewest + Math.floor(random() * (most - fewest));
    const stepLon = (0.022 + random() * 0.035) * direction / Math.max(0.35, Math.cos(lat));
    const zig = random() < zigzag;
    const points = [];
    for (let step = 0; step <= steps; step++) {
      points.push(...onSphere(lat, lon, radius));
      if (zig) { lat += (step % 2 ? 1 : -1) * 0.014; lon += stepLon * 0.45; }
      else if (random() < 0.22) lat += (random() < 0.5 ? -1 : 1) * 0.028;
      else lon += stepLon;
    }
    list.push({ points: Float32Array.from(points), seed: random() * 100, hot: random() < 0.12 });
  }
  return list;
}

// Bands of circuitry hugging the sphere's outline (like broken outer rings): angle/radius pairs on screen.
function outlineBands(random, { count, radius: [rMin, rMax], angle: [aMin, aMax], steps: [fewest, most] }) {
  const list = [];
  for (let i = 0; i < count; i++) {
    let angle = aMin + random() * (aMax - aMin), r = rMin + random() * (rMax - rMin);
    const direction = random() < 0.5 ? -1 : 1, steps = fewest + Math.floor(random() * (most - fewest));
    const zig = random() < 0.3;
    const points = [];
    for (let step = 0; step <= steps; step++) {
      points.push(angle, r);
      if (zig) { r += (step % 2 ? 1 : -1) * 0.012; angle += direction * 0.01; }
      else if (random() < 0.25) r += (random() < 0.5 ? -1 : 1) * 0.02;
      else angle += direction * (0.018 + random() * 0.02);
    }
    list.push({ points: Float32Array.from(points), seed: random() * 100, hot: random() < 0.1 });
  }
  return list;
}

// The equator ribbon: a bundle of slightly wavy rings, wider than the sphere.
function ribbon(random, lines, radius, thickness) {
  const list = [];
  for (let k = 0; k < lines; k++) {
    const r = radius + (k / lines - 0.5) * thickness;
    const phase = random() * TAU, wobble = 0.004 + random() * 0.006, lift = (random() - 0.5) * 0.05;
    const points = [];
    for (let i = 0; i <= 160; i++) {
      const angle = (i / 160) * TAU;
      points.push(Math.sin(angle) * r, lift + Math.sin(angle * 23 + phase) * wobble, Math.cos(angle) * r);
    }
    list.push({ points: Float32Array.from(points), seed: random() * 100, hot: random() < 0.2 });
  }
  return list;
}

// widget: true for a small card: no name and state under the orb (the card shows its own), and the orbits fit the box.
export function createCore(canvas, { widget = false } = {}) {
  const context = canvas.getContext("2d");
  const orbCanvas = document.createElement("canvas"); // the orb alone, so it can glow (bloom) without the text
  const orb = orbCanvas.getContext("2d");
  const glowCanvas = document.createElement("canvas");
  const glow = glowCanvas.getContext("2d");
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const random = seeded(11);
  const layers = {
    core: traces(random, { count: 260, radius: 0.46, lat: [-1.3, 1.3], lon: [0, TAU], steps: [3, 8], zigzag: 0.5 }),
    sphere: traces(random, { count: 1250, radius: 1, lat: [-1.4, 1.4], lon: [0, TAU], steps: [3, 10], zigzag: 0.35, gaps: true }),
    ribbon: ribbon(random, 22, 1.3, 0.11),
  };
  const bands = [
    { traces: outlineBands(random, { count: 170, radius: [1.08, 1.24], angle: [-2.55, -0.55], steps: [6, 16] }), speed: 0.05 },
    { traces: outlineBands(random, { count: 140, radius: [1.06, 1.2], angle: [0.25, 1.85], steps: [6, 16] }), speed: -0.04 },
    { traces: outlineBands(random, { count: 60, radius: [1.1, 1.17], angle: [2.55, 3.5], steps: [5, 12] }), speed: 0.03 },
  ];
  const sparks = Array.from({ length: 26 }, () => ({ layer: random() < 0.7 ? "sphere" : "ribbon", index: 0, start: random() * 3, speed: 0.4 + random() * 0.6 }));
  sparks.forEach((spark) => { spark.index = Math.floor(random() * layers[spark.layer].length); });
  const orbits = [
    { radius: 1.65, tilt: 1.22, turn: 0.3, speed: 0.07, dots: [0, 2.6], dashed: false },
    { radius: 1.9, tilt: 1.32, turn: 2.2, speed: -0.05, dots: [1.4], dashed: false },
    { radius: 2.15, tilt: 1.12, turn: 4.0, speed: 0.04, dots: [4.2], dashed: true },
  ];
  let mode = "idle", label = "", micLevel = 0, accent = [255, 176, 64], errorUntil = 0, wakeUntil = 0;
  const eased = { open: 0, glow: 0.4, spin: 0.4, scatter: 0, scan: 0, level: 0, error: 0 };
  let spin = 0, orbitTime = 0, last = performance.now(), frameCost = 8, detail = 1;

  const color = (alpha, heat = 0) => {
    const [r, g, b] = accent;
    const mix = (value) => Math.round(value + (255 - value) * heat);
    return `rgba(${mix(r)}, ${mix(g)}, ${mix(b)}, ${Math.max(0, Math.min(1, alpha))})`;
  };
  const wave = (seed, t) => 0.5 + 0.5 * Math.sin(seed * 1.7 + t * 4.1) * Math.sin(seed * 0.9 - t * 2.3);

  function resize() {
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const { width, height } = canvas.getBoundingClientRect();
    for (const target of [canvas, orbCanvas]) {
      if (target.width !== Math.round(width * ratio) || target.height !== Math.round(height * ratio)) {
        target.width = Math.round(width * ratio);
        target.height = Math.round(height * ratio);
      }
    }
    glowCanvas.width = Math.max(1, Math.round(width / 4));
    glowCanvas.height = Math.max(1, Math.round(height / 4));
    return { width, height, ratio };
  }

  function frame(now) {
    const started = performance.now();
    const seconds = Math.min(0.05, (now - last) / 1000);
    last = now;
    const t = now / 1000;
    const shown = now < errorUntil ? "error" : mode;
    const [glowTarget, spinTarget, scatter, scan] = MOODS[shown] || MOODS.idle;
    const awake = AWAKE.has(shown) || now < wakeUntil;
    const follow = (rate) => 1 - Math.exp(-seconds * rate);
    eased.open += ((awake ? 1 : 0) - eased.open) * follow(awake ? 3.2 : 1.8);
    eased.glow += (glowTarget - eased.glow) * follow(4);
    eased.spin += (spinTarget * (reduced ? 0.15 : 1) - eased.spin) * follow(3);
    eased.scatter += ((reduced ? 0 : scatter) - eased.scatter) * follow(4);
    eased.scan += (scan - eased.scan) * follow(3);
    eased.error += ((shown === "error" ? 1 : 0) - eased.error) * follow(5);
    const speaking = shown === "speak" ? 0.3 + 0.5 * Math.abs(Math.sin(t * 8.3)) * Math.abs(Math.sin(t * 2.1 + 1)) : 0;
    eased.level += (Math.max(micLevel, speaking) - eased.level) * follow(16);
    spin += seconds * (0.18 + 0.7 * eased.spin);
    orbitTime += seconds * (reduced ? 0.2 : 1);

    const { width, height, ratio } = resize();
    if (width < 2 || height < 2) { // hidden (the brainstorm map is showing): idle until visible again
      requestAnimationFrame(frame);
      return;
    }
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, width, height);
    const cx = width / 2, cy = widget ? height / 2 : height / 2 - Math.min(26, height * 0.04);
    const radius = widget ? Math.min(width, height) / 4.6 : Math.max(60, Math.min(165, Math.min(width / 2.8, height / 2.6) * 0.62));
    const o = eased.open * eased.open * (3 - 2 * eased.open); // the sphere's height grows from a flat line to an orb
    const level = eased.level;
    const tilt = -0.28 + Math.sin(t * 0.21) * 0.05;
    const cosT = Math.cos(tilt), sinT = Math.sin(tilt);

    // ---- the orb, drawn on its own canvas ----
    orb.setTransform(ratio, 0, 0, ratio, 0, 0);
    orb.clearRect(0, 0, width, height);
    orb.globalCompositeOperation = "lighter";
    const fade = Math.min(1, o * 1.4);

    if (o > 0.02) {
      const drawLayer = (list, yaw, scale, baseAlpha, width_, depthWeight = 0.75) => {
        const cosA = Math.cos(yaw), sinA = Math.sin(yaw);
        const buckets = Array.from({ length: 12 }, () => []);
        const nodes = [];
        const step = detail < 1 && list.length > 200 ? 2 : 1;
        for (let index = 0; index < list.length; index += step) {
          const trace = list[index];
          const push = 1 + eased.scatter * level * (0.03 + 0.22 * wave(trace.seed, t)) + Math.sin(t * 1.3 + trace.seed) * 0.006;
          const points = trace.points, projected = new Float32Array((points.length / 3) * 2);
          let depthSum = 0;
          for (let p = 0, q = 0; p < points.length; p += 3, q += 2) {
            const x = points[p] * push, y = points[p + 1] * push, z = points[p + 2] * push;
            const x1 = x * cosA + z * sinA, z1 = -x * sinA + z * cosA;
            const y2 = y * cosT - z1 * sinT, z2 = y * sinT + z1 * cosT;
            const perspective = 1 / (1 - z2 * 0.2);
            projected[q] = cx + x1 * radius * scale * perspective;
            projected[q + 1] = cy + y2 * radius * scale * perspective * Math.max(0.015, o);
            depthSum += z2;
          }
          const depth = Math.max(0, Math.min(1, (depthSum / (points.length / 3) / scale + 1) / 2));
          const band = eased.scan * Math.max(0, 1 - Math.abs(points[1] / scale - Math.sin(t * 1.4)) * 3.5);
          const alpha = baseAlpha * ((1 - depthWeight) + depthWeight * depth ** 1.4) * (0.55 + 0.45 * eased.glow)
            + band * 0.5 + level * 0.3 * wave(trace.seed, t * 2);
          const bucket = Math.max(0, Math.min(5, Math.floor(alpha * 6))) + (trace.hot || band > 0.5 ? 6 : 0);
          buckets[bucket].push(projected);
          if (depth > 0.45) nodes.push(projected[0], projected[1], projected[projected.length - 2], projected[projected.length - 1]);
        }
        orb.lineJoin = "round";
        buckets.forEach((polylines, index) => {
          if (!polylines.length) return;
          orb.beginPath();
          for (const line of polylines) {
            orb.moveTo(line[0], line[1]);
            for (let q = 2; q < line.length; q += 2) orb.lineTo(line[q], line[q + 1]);
          }
          orb.lineWidth = index >= 6 ? width_ * 1.2 : width_;
          orb.strokeStyle = color((((index % 6) + 0.7) / 6) * 0.62 * fade, index >= 6 ? 0.3 : 0.04);
          orb.stroke();
        });
        // little solder dots at the ends of the traces facing us
        orb.beginPath();
        for (let n = 0; n < nodes.length; n += 2) orb.rect(nodes[n] - 1, nodes[n + 1] - 1, 2, 2);
        orb.fillStyle = color(0.45 * fade, 0.15);
        orb.fill();
      };

      // Inner core: concentric rings facing you, under a ball of tight circuitry
      for (let ring = 1; ring <= 7; ring++) {
        const r = radius * (0.1 + ring * 0.055) * (1 + level * 0.08);
        orb.beginPath();
        orb.ellipse(cx, cy, r, r * Math.max(0.015, o), 0, 0, TAU);
        orb.setLineDash(ring % 2 ? [r * 0.3, r * 0.08] : [r * 0.08, r * 0.05]);
        orb.lineDashOffset = (ring % 2 ? 1 : -1) * t * 20 * ring;
        orb.lineWidth = 1;
        orb.strokeStyle = color((0.25 + 0.2 * eased.glow) * fade, 0.25);
        orb.stroke();
      }
      orb.setLineDash([]);
      drawLayer(layers.core, -spin * 1.6, 1, 0.75, 1, 0.5);
      drawLayer(layers.sphere, spin, 1, 0.95, 1);
      // Outline bands: circuitry hugging the edge, each band turning slowly its own way
      for (const band of bands) {
        const turn = t * band.speed * (0.6 + eased.spin);
        const buckets = [[], [], []];
        for (const trace of band.traces) {
          const points = trace.points, push = 1 + eased.scatter * level * 0.12 * wave(trace.seed, t);
          const line = new Float32Array(points.length);
          for (let p = 0; p < points.length; p += 2) {
            const angle = points[p] + turn, r = points[p + 1] * push * radius;
            line[p] = cx + Math.cos(angle) * r;
            line[p + 1] = cy + Math.sin(angle) * r * Math.max(0.015, o);
          }
          buckets[trace.hot ? 2 : wave(trace.seed, t * 0.5) > 0.5 ? 1 : 0].push(line);
        }
        buckets.forEach((lines, index) => {
          orb.beginPath();
          for (const line of lines) {
            orb.moveTo(line[0], line[1]);
            for (let q = 2; q < line.length; q += 2) orb.lineTo(line[q], line[q + 1]);
          }
          orb.lineWidth = 1.05;
          orb.strokeStyle = color(([0.32, 0.5, 0.75][index] + level * 0.2) * (0.6 + 0.4 * eased.glow) * fade, index === 2 ? 0.35 : 0.05);
          orb.stroke();
        });
      }

      // Equator ribbon, tilted a little, turning on its own
      const ribbonTilt = 0.16 + Math.sin(t * 0.3) * 0.03;
      const cosR = Math.cos(ribbonTilt), sinR = Math.sin(ribbonTilt);
      {
        const cosA = Math.cos(spin * 0.8), sinA = Math.sin(spin * 0.8);
        orb.beginPath();
        for (const line of layers.ribbon) {
          const points = line.points;
          let first = true;
          for (let p = 0; p < points.length; p += 3) {
            const x = points[p], y = points[p + 1], z = points[p + 2];
            const x1 = x * cosA + z * sinA, z1 = -x * sinA + z * cosA;
            const y2 = y * cosR - z1 * sinR, z2 = y * sinR + z1 * cosR;
            if (z2 < -0.2) { first = true; continue; } // the back half hides behind the sphere
            const sx = cx + x1 * radius, sy = cy + y2 * radius * Math.max(0.015, o);
            if (first) { orb.moveTo(sx, sy); first = false; } else orb.lineTo(sx, sy);
          }
        }
        orb.lineWidth = 1;
        orb.strokeStyle = color((0.16 + 0.12 * eased.glow + level * 0.2) * fade, 0.02);
        orb.stroke();
      }

      // The diagonal streak through the middle: a ring seen almost edge-on
      const angle = 0.95 + Math.sin(t * 0.17) * 0.12;
      const ux = Math.cos(angle), uy = Math.sin(angle);
      orb.lineWidth = 1.2;
      for (let k = -2; k <= 2; k++) {
        const offset = k * 2.2;
        const thin = 0.025 + 0.01 * Math.sin(t * 0.7 + k);
        orb.beginPath();
        orb.ellipse(cx - uy * offset, cy + ux * offset * Math.max(0.015, o), radius * 0.97, radius * thin, angle, 0, TAU);
        orb.strokeStyle = color((0.45 - Math.abs(k) * 0.08 + level * 0.25) * fade, 0.3);
        orb.stroke();
      }

      // Broken outline arcs
      [[1.0, 0.3, 2.1, 1], [1.035, 2.9, 1.6, -1], [0.965, 4.6, 1.3, 1]].forEach(([scale, start, length, direction]) => {
        orb.beginPath();
        orb.ellipse(cx, cy, radius * scale, radius * scale * Math.max(0.015, o), 0, start + direction * t * 0.12, start + length + direction * t * 0.12);
        orb.lineWidth = 1.2;
        orb.strokeStyle = color(0.6 * fade, 0.3);
        orb.stroke();
      });

      // Sparks running along the circuits
      for (const spark of sparks) {
        const line = layers[spark.layer][spark.index];
        if (!line) continue;
        const progress = ((t * spark.speed + spark.start) % 3) / 3;
        const p = Math.floor(progress * (line.points.length / 3 - 1)) * 3;
        const yaw = spark.layer === "sphere" ? spin : spin * 0.8;
        const cosA = Math.cos(yaw), sinA = Math.sin(yaw);
        const [x, y, z] = [line.points[p], line.points[p + 1], line.points[p + 2]];
        const x1 = x * cosA + z * sinA, z1 = -x * sinA + z * cosA;
        const tiltCos = spark.layer === "sphere" ? cosT : cosR, tiltSin = spark.layer === "sphere" ? sinT : sinR;
        const y2 = y * tiltCos - z1 * tiltSin, z2 = y * tiltSin + z1 * tiltCos;
        if (z2 < 0) continue;
        const sx = cx + x1 * radius, sy = cy + y2 * radius * Math.max(0.015, o);
        const size = 4 + level * 6;
        const dot = orb.createRadialGradient(sx, sy, 0, sx, sy, size);
        dot.addColorStop(0, color(0.6 * fade, 0.6));
        dot.addColorStop(1, color(0));
        orb.fillStyle = dot;
        orb.fillRect(sx - size, sy - size, size * 2, size * 2);
      }

      // A warm heart, brighter with the voice
      const coreSize = radius * (0.28 + 0.1 * level);
      const heart = orb.createRadialGradient(cx, cy, 0, cx, cy, coreSize);
      heart.addColorStop(0, color((0.18 + 0.35 * level) * fade, 0.5));
      heart.addColorStop(1, color(0));
      orb.fillStyle = heart;
      orb.fillRect(cx - coreSize, cy - coreSize, coreSize * 2, coreSize * 2);
    }

    // ---- compose: halo, orbits, sleeping line, then the orb with its bloom ----
    context.globalCompositeOperation = "lighter";
    const halo = context.createRadialGradient(cx, cy, radius * 0.2, cx, cy, radius * 2);
    halo.addColorStop(0, color(0.1 * eased.glow * (0.35 + o) + level * 0.08, 0.1));
    halo.addColorStop(0.5, color(0.035 * eased.glow * (0.4 + o)));
    halo.addColorStop(1, color(0));
    context.fillStyle = halo;
    context.fillRect(cx - radius * 2.1, cy - radius * 2.1, radius * 4.2, radius * 4.2);

    for (const orbit of orbits) {
      const turn = orbit.turn + orbitTime * orbit.speed;
      const cosN = Math.cos(orbit.tilt), sinN = Math.sin(orbit.tilt), cosO = Math.cos(turn), sinO = Math.sin(turn);
      const point = (angle) => {
        let x = Math.cos(angle) * orbit.radius, y = Math.sin(angle) * orbit.radius * cosN;
        const z = Math.sin(angle) * orbit.radius * sinN;
        [x, y] = [x * cosO - y * sinO, x * sinO + y * cosO];
        const perspective = 1 / (1 - (z / orbit.radius) * 0.12);
        return [cx + x * radius * perspective, cy + y * radius * perspective * (0.55 + 0.45 * o), z];
      };
      context.beginPath();
      for (let step = 0; step <= 120; step++) {
        const [x, y] = point((step / 120) * TAU);
        step ? context.lineTo(x, y) : context.moveTo(x, y);
      }
      context.setLineDash(orbit.dashed ? [2, 6] : []);
      context.lineWidth = 1;
      context.strokeStyle = color(0.14 + 0.12 * eased.glow);
      context.stroke();
      context.setLineDash([]);
      for (const phase of orbit.dots) {
        const [x, y, z] = point(phase + orbitTime * orbit.speed * 9);
        const size = 2.2 + (z > 0 ? 1.2 : 0);
        const dot = context.createRadialGradient(x, y, 0, x, y, size * 4);
        dot.addColorStop(0, color(0.95, 0.5));
        dot.addColorStop(0.3, color(0.5));
        dot.addColorStop(1, color(0));
        context.fillStyle = dot;
        context.fillRect(x - size * 4, y - size * 4, size * 8, size * 8);
      }
    }

    if (o < 0.98) {
      const visible = 1 - o;
      const half = radius * (1.25 + 0.15 * Math.sin(t * 0.8));
      const line = context.createLinearGradient(cx - half, cy, cx + half, cy);
      line.addColorStop(0, color(0));
      line.addColorStop(0.3, color(0.55 * visible * eased.glow));
      line.addColorStop(0.5, color(visible, 0.65));
      line.addColorStop(0.7, color(0.55 * visible * eased.glow));
      line.addColorStop(1, color(0));
      context.strokeStyle = line;
      context.lineWidth = 8;
      context.globalAlpha = 0.18;
      context.beginPath(); context.moveTo(cx - half, cy); context.lineTo(cx + half, cy); context.stroke();
      context.globalAlpha = 1;
      context.lineWidth = 1.6;
      context.beginPath(); context.moveTo(cx - half, cy); context.lineTo(cx + half, cy); context.stroke();
      const travel = ((t * (shown === "armed" ? 0.45 : 0.18)) % 1) * 2 - 1;
      const sparkX = cx + travel * half * 0.85;
      const sparkGlow = context.createRadialGradient(sparkX, cy, 0, sparkX, cy, 14);
      sparkGlow.addColorStop(0, color(0.8 * visible, 0.6));
      sparkGlow.addColorStop(1, color(0));
      context.fillStyle = sparkGlow;
      context.fillRect(sparkX - 14, cy - 14, 28, 28);
    }

    if (o > 0.02) {
      // Bloom: a blurred quarter-size copy added under the sharp lines
      glow.clearRect(0, 0, glowCanvas.width, glowCanvas.height);
      glow.filter = "blur(2px)";
      glow.drawImage(orbCanvas, 0, 0, glowCanvas.width, glowCanvas.height);
      glow.filter = "none";
      context.globalAlpha = 0.55 + 0.4 * level;
      context.drawImage(glowCanvas, 0, 0, width, height);
      context.globalAlpha = 1;
      context.drawImage(orbCanvas, 0, 0, width, height);
    }

    if (eased.error > 0.02) {
      context.beginPath();
      context.arc(cx, cy, radius * (1.1 + 0.05 * Math.sin(t * 10)), 0, TAU);
      context.lineWidth = 2;
      context.strokeStyle = `rgba(255, 77, 106, ${eased.error * 0.8})`;
      context.stroke();
    }

    // ---- name, what NOVA stands for, and the state ----
    context.globalCompositeOperation = "source-over";
    if (!widget) drawText(cx, cy, radius, o, shown, width);

    // Keep it smooth on slow PCs: draw half the traces when frames get expensive
    frameCost += (performance.now() - started - frameCost) * 0.05;
    detail = frameCost > 18 ? 0.5 : frameCost < 10 ? 1 : detail;
    requestAnimationFrame(frame);
  }

  function drawText(cx, cy, radius, o, shown, width) {
    const textY = cy + radius * (0.32 + 1.0 * o) + 32;
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.shadowColor = color(0.9);
    context.shadowBlur = 16;
    context.fillStyle = `rgba(255, 244, 226, ${0.78 + 0.2 * eased.glow})`;
    const nameSize = Math.round(Math.max(18, Math.min(30, radius * 0.2)));
    context.font = `600 ${nameSize}px Rajdhani, "Segoe UI", sans-serif`;
    context.letterSpacing = `${Math.round(nameSize * 0.5)}px`;
    context.fillText("NOVA", cx + nameSize * 0.25, textY);
    context.shadowBlur = 0;
    // The long name, its initials lit: N O V A
    context.font = `600 9px "JetBrains Mono", Consolas, monospace`;
    context.letterSpacing = "1.5px";
    const words = TAGLINE.map((word) => word.toUpperCase());
    const space = context.measureText(" ").width + 3;
    const total = words.reduce((sum, word) => sum + context.measureText(word).width, 0) + space * (words.length - 1);
    if (total < width - 40) {
      let x = cx - total / 2;
      context.textAlign = "left";
      for (const word of words) {
        const initial = word[0], rest = word.slice(1);
        context.fillStyle = word === "FOR" ? "rgba(200, 190, 175, 0.45)" : color(1, 0.15);
        context.fillText(initial, x, textY + nameSize * 0.85);
        const initialWidth = context.measureText(initial).width;
        context.fillStyle = "rgba(200, 190, 175, 0.55)";
        context.fillText(rest, x + initialWidth, textY + nameSize * 0.85);
        x += initialWidth + context.measureText(rest).width + space;
      }
      context.textAlign = "center";
    }
    context.font = `600 10px "JetBrains Mono", Consolas, monospace`;
    context.letterSpacing = "3px";
    context.fillStyle = color(0.9, 0.1);
    context.fillText(label || LABELS[shown] || "", cx, textY + nameSize * 0.85 + 20);
    context.letterSpacing = "0px";
  }
  requestAnimationFrame(frame);

  return {
    setMode(next, text = "") {
      if (AWAKE.has(mode) && !AWAKE.has(next)) wakeUntil = performance.now() + LINGER_MS;
      mode = next in MOODS ? next : "idle";
      label = text;
    },
    setLevel(value) { micLevel = Math.max(0, Math.min(1, Number(value) || 0)); },
    setAccent(rgb) { accent = String(rgb).split(",").map((part) => Number(part.trim()) || 0); },
    flashError(milliseconds = 2200) { errorUntil = performance.now() + milliseconds; },
    get frameCost() { return frameCost; },
  };
}
