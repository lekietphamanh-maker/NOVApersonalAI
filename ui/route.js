// Nova's route map: the city's roads in dim gold, the search spreading out from the start along the streets (one
// colour per leg), then the fastest path lighting up. Nova works the route out (routes.py); this page only draws it.

const LEG_COLORS = ["#3be4ff", "#ff5fd2", "#7dff9a", "#ffb040", "#a78bff"];
const PLAY_MS = 6500;

function h(tag, attributes = {}, ...children) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") element.className = value;
    else if (key.startsWith("on")) element.addEventListener(key.slice(2), value);
    else element.setAttribute(key, value === true ? "" : value);
  }
  element.append(...children.flat().filter((child) => child !== null && child !== undefined && child !== false)
    .map((child) => (typeof child === "string" || typeof child === "number" ? document.createTextNode(String(child)) : child)));
  return element;
}

function minutes(seconds) {
  const total = Math.max(1, Math.round(seconds / 60));
  return total < 60 ? `${total} min` : `${Math.floor(total / 60)} h ${String(total % 60).padStart(2, "0")} min`;
}

// Web Mercator, so streets keep their real shape.
const mercatorY = (lat) => Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360));

export function createRoute(root, { act, onOpenChange }) {
  const $ = (selector) => root.querySelector(selector);
  const canvas = $("#route-map"), context = canvas.getContext("2d"), info = $("#route-info");
  let route = null, opened = false, started = 0, frame = 0, base = null;

  function open() {
    if (opened) return;
    opened = true;
    root.hidden = false;
    onOpenChange?.(true);
    frame = requestAnimationFrame(draw);
  }

  function close() {
    if (!opened) return;
    opened = false;
    root.hidden = true;
    cancelAnimationFrame(frame);
    onOpenChange?.(false);
  }

  function fit() {
    const box = canvas.getBoundingClientRect(), scale = window.devicePixelRatio || 1;
    const width = Math.max(1, Math.round(box.width * scale)), height = Math.max(1, Math.round(box.height * scale));
    if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; base = null; }
    let west = Infinity, east = -Infinity, south = Infinity, north = -Infinity;
    for (const place of route.places) {
      west = Math.min(west, place.lon); east = Math.max(east, place.lon);
      south = Math.min(south, place.lat); north = Math.max(north, place.lat);
    }
    const pad = Math.max(0.006, (east - west) * 0.25, (north - south) * 0.25);
    west -= pad; east += pad; south -= pad; north += pad;
    const top = mercatorY(north), bottom = mercatorY(south), spanX = (east - west) * Math.PI / 180, spanY = top - bottom;
    const size = Math.min(width / spanX, height / spanY) * 0.94;
    const offsetX = (width - spanX * size) / 2, offsetY = (height - spanY * size) / 2;
    return { width, height, scale, x: (lon) => offsetX + (lon - west) * Math.PI / 180 * size,
             y: (lat) => offsetY + (top - mercatorY(lat)) * size };
  }

  function polyline(points, view) {
    context.beginPath();
    for (let index = 0; index < points.length; index += 2) {
      const x = view.x(points[index]), y = view.y(points[index + 1]);
      if (index) context.lineTo(x, y); else context.moveTo(x, y);
    }
    context.stroke();
  }

  function drawBase(view) {
    // The city's roads, drawn once and reused every frame.
    base = document.createElement("canvas");
    base.width = view.width; base.height = view.height;
    const baseContext = base.getContext("2d");
    baseContext.strokeStyle = "rgba(255, 176, 64, 0.16)";
    baseContext.lineWidth = 1 * view.scale;
    for (const line of route.roads) {
      baseContext.beginPath();
      for (let index = 0; index < line.length; index += 2) {
        const x = view.x(line[index]), y = view.y(line[index + 1]);
        if (index) baseContext.lineTo(x, y); else baseContext.moveTo(x, y);
      }
      baseContext.stroke();
    }
  }

  function draw(now) {
    if (!opened) return;
    frame = requestAnimationFrame(draw);
    if (!route) return;
    const view = fit();
    if (!base) drawBase(view);
    context.clearRect(0, 0, view.width, view.height);
    context.drawImage(base, 0, 0);
    const progress = Math.min(1, (now - started) / PLAY_MS);
    const searchShare = Math.min(1, progress / 0.8), shown = Math.floor(route.searched.length * searchShare);
    context.globalCompositeOperation = "lighter";
    context.lineWidth = 1.4 * view.scale;
    for (let index = 0; index < shown; index++) {
      const [leg, x1, y1, x2, y2] = route.searched[index];
      const fresh = index > shown - 400;
      context.strokeStyle = LEG_COLORS[leg % LEG_COLORS.length] + (fresh ? "ff" : "88");
      context.beginPath();
      context.moveTo(view.x(x1), view.y(y1));
      context.lineTo(view.x(x2), view.y(y2));
      context.stroke();
    }
    context.globalCompositeOperation = "source-over";
    if (progress >= 0.8) {
      const glow = (Math.sin(now / 300) + 1) / 2;
      context.shadowColor = "#ffd27a";
      context.shadowBlur = (10 + 8 * glow) * view.scale;
      context.strokeStyle = "#ffe2a8";
      context.lineWidth = 3.2 * view.scale;
      context.lineJoin = context.lineCap = "round";
      for (const line of route.line) polyline(line, view);
      context.shadowBlur = 0;
    }
    route.places.forEach((place, index) => {
      const x = view.x(place.lon), y = view.y(place.lat), last = index === route.places.length - 1;
      context.fillStyle = index === 0 ? "#3be4ff" : last ? "#ffb040" : "#ff5fd2";
      context.beginPath();
      context.arc(x, y, 7 * view.scale, 0, Math.PI * 2);
      context.fill();
      context.font = `600 ${12 * view.scale}px "JetBrains Mono", monospace`;
      context.fillStyle = "#fff";
      context.fillText(`${index === 0 ? "A" : last ? "B" : index} · ${place.name}`, x + 11 * view.scale, y - 9 * view.scale);
    });
  }

  function show(data) {
    route = data;
    base = null;
    started = performance.now();
    const how = { motorbike: "by motorbike", car: "by car", walk: "on foot" }[route.mode] || "";
    info.replaceChildren(
      h("b", {}, `${minutes(route.seconds)} · ${(route.metres / 1000).toFixed(1)} km ${how}`),
      h("span", { class: "muted small" }, route.places.map((place) => place.name).join(" → ") + (route.reordered ? " (quickest order)" : "")),
      ...(route.legs.length > 1 ? route.legs.map((leg, index) => h("span", { class: "small" },
        h("i", { style: `background:${LEG_COLORS[index % LEG_COLORS.length]}` }),
        `${route.places[index].name} → ${route.places[index + 1].name}: ${minutes(leg.seconds)}`)) : []),
      h("span", { class: "muted small" }, "Normal speeds for each kind of road: no live traffic."),
      h("div", { class: "row wrap" },
        h("button", { class: "box small", type: "button", onclick: () => { started = performance.now(); } }, "Replay"),
        h("button", { class: "box small on", type: "button", onclick: () => act("open_url", { url: route.google_maps }) }, "Google Maps (live traffic)")));
    open();
  }

  $("#route-close").addEventListener("click", close);
  $("#route-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const form = new FormData(event.target);
    info.replaceChildren(h("span", { class: "muted small" }, "Finding the fastest way…"));
    act("route", { start: form.get("start"), end: form.get("end"), stops: form.get("stops"), mode: form.get("mode") });
  });

  return { open, close, show, isOpen: () => opened, error: (text) => info.replaceChildren(h("span", { class: "small" }, text)) };
}
