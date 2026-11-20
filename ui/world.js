// Nova's World view: a gold line globe with what's happening on Earth (Nova's world_monitor feeds). Drag to turn it,
// scroll to zoom, click a dot for the story. Nova flies it to a place when asked ("what's happening in the Middle East?").
// Nova owns the data; this page only draws it.

export const LAYERS = {
  conflict: { label: "Conflict", color: "#ff3b4e" },
  news: { label: "News", color: "#f2e6c8" },
  quakes: { label: "Earthquakes", color: "#ffb040" },
  disasters: { label: "Disaster alerts", color: "#ff6b3d" },
  storms: { label: "Storms", color: "#3be4ff" },
  fires: { label: "Wildfires", color: "#ff8a1f" },
  volcanoes: { label: "Volcanoes", color: "#ff5fd2" },
};
const RADIANS = Math.PI / 180;
const IDLE_SPIN = 0.012; // degrees per frame while nobody touches it

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

function ago(stamp) {
  const minutes = Math.max(0, Math.round((Date.now() - new Date(stamp).getTime()) / 60000));
  if (!Number.isFinite(minutes)) return "";
  if (minutes < 60) return minutes <= 1 ? "just now" : `${minutes} min ago`;
  if (minutes < 1440) return `${Math.round(minutes / 60)} h ago`;
  return `${Math.round(minutes / 1440)} d ago`;
}

// Orthographic projection around (lon0, lat0): [x, y, visible] with the globe's radius as 1.
export function project(lon, lat, lon0, lat0) {
  const phi = lat * RADIANS, lambda = (lon - lon0) * RADIANS, phi0 = lat0 * RADIANS;
  const cosC = Math.sin(phi0) * Math.sin(phi) + Math.cos(phi0) * Math.cos(phi) * Math.cos(lambda);
  return [Math.cos(phi) * Math.sin(lambda), Math.cos(phi0) * Math.sin(phi) - Math.sin(phi0) * Math.cos(phi) * Math.cos(lambda), cosC >= 0];
}

export function createWorld(root, { act, onOpenChange }) {
  const $ = (selector) => root.querySelector(selector);
  const canvas = $("#world-globe"), list = $("#world-list"), card = $("#world-card"), layersBox = $("#world-layers");
  const context = canvas.getContext("2d");
  let map = null, events = [], errors = {}, days = 1, opened = false, newsOn = true;
  const shown = Object.fromEntries(Object.keys(LAYERS).map((layer) => [layer, true]));
  const view = { lon: 20, lat: 20, zoom: 1 };
  let flight = null, dragging = null, lastTouch = 0, frame = 0, selected = null;

  async function loadMap() {
    if (map) return;
    try { map = await (await fetch("world-110m.json")).json(); } catch { map = { countries: [] }; }
  }

  function size() {
    const box = canvas.getBoundingClientRect(), scale = window.devicePixelRatio || 1;
    if (canvas.width !== Math.round(box.width * scale) || canvas.height !== Math.round(box.height * scale)) {
      canvas.width = Math.round(box.width * scale);
      canvas.height = Math.round(box.height * scale);
    }
    return { width: canvas.width, height: canvas.height, scale, radius: Math.min(canvas.width, canvas.height) * 0.42 * view.zoom };
  }

  function screen(lon, lat, geometry) {
    const [x, y, visible] = project(lon, lat, view.lon, view.lat);
    return [geometry.width / 2 + x * geometry.radius, geometry.height / 2 - y * geometry.radius, visible];
  }

  function drawLines(geometry) {
    const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent-rgb").trim() || "255, 176, 64";
    context.lineWidth = 1 * geometry.scale;
    context.strokeStyle = `rgba(${accent}, 0.10)`;
    for (let lat = -60; lat <= 60; lat += 30) path(Array.from({ length: 73 }, (_, step) => [step * 5 - 180, lat]), geometry);
    for (let lon = -180; lon < 180; lon += 30) path(Array.from({ length: 37 }, (_, step) => [lon, step * 5 - 90]), geometry);
    context.strokeStyle = `rgba(${accent}, 0.55)`;
    for (const country of map.countries) {
      for (const ring of country.rings) {
        const points = [];
        for (let index = 0; index < ring.length; index += 2) points.push([ring[index], ring[index + 1]]);
        points.push(points[0]);
        path(points, geometry);
      }
    }
  }

  function path(points, geometry) {
    context.beginPath();
    let drawing = false;
    for (const [lon, lat] of points) {
      const [x, y, visible] = screen(lon, lat, geometry);
      if (!visible) { drawing = false; continue; }
      if (drawing) context.lineTo(x, y); else context.moveTo(x, y);
      drawing = true;
    }
    context.stroke();
  }

  function visibleEvents() {
    return events.filter((event) => shown[event.layer]);
  }

  function draw(now) {
    if (!opened) return;
    frame = requestAnimationFrame(draw);
    if (flight) {
      const progress = Math.min(1, (now - flight.start) / flight.duration), ease = 1 - (1 - progress) ** 3;
      let turn = ((flight.to.lon - flight.from.lon + 540) % 360) - 180;
      view.lon = flight.from.lon + turn * ease;
      view.lat = flight.from.lat + (flight.to.lat - flight.from.lat) * ease;
      view.zoom = flight.from.zoom + (flight.to.zoom - flight.from.zoom) * ease;
      if (progress >= 1) flight = null;
    } else if (!dragging && now - lastTouch > 6000 && !selected) {
      view.lon = ((view.lon + IDLE_SPIN + 540) % 360) - 180;
    }
    const geometry = size();
    context.clearRect(0, 0, geometry.width, geometry.height);
    const glow = context.createRadialGradient(geometry.width / 2, geometry.height / 2, geometry.radius * 0.2,
      geometry.width / 2, geometry.height / 2, geometry.radius * 1.15);
    glow.addColorStop(0, "rgba(20, 16, 8, 0.95)");
    glow.addColorStop(0.86, "rgba(8, 9, 11, 0.95)");
    glow.addColorStop(1, "rgba(255, 176, 64, 0)");
    context.fillStyle = glow;
    context.beginPath();
    context.arc(geometry.width / 2, geometry.height / 2, geometry.radius * 1.15, 0, Math.PI * 2);
    context.fill();
    if (map) drawLines(geometry);
    const pulse = (Math.sin(now / 380) + 1) / 2;
    for (const event of visibleEvents()) {
      const [x, y, visible] = screen(event.lon, event.lat, geometry);
      if (!visible) continue;
      const color = LAYERS[event.layer]?.color || "#fff", radius = (2 + event.severity * 1.6) * geometry.scale;
      context.fillStyle = color;
      context.globalAlpha = 0.9;
      context.beginPath();
      context.arc(x, y, radius, 0, Math.PI * 2);
      context.fill();
      if (event.severity >= 3 || event === selected) {
        context.globalAlpha = 0.6 * (1 - pulse);
        context.strokeStyle = color;
        context.lineWidth = 1.5 * geometry.scale;
        context.beginPath();
        context.arc(x, y, radius + 10 * pulse * geometry.scale, 0, Math.PI * 2);
        context.stroke();
      }
      context.globalAlpha = 1;
    }
  }

  function nearest(clientX, clientY) {
    const box = canvas.getBoundingClientRect(), geometry = size();
    const x = (clientX - box.left) * geometry.scale, y = (clientY - box.top) * geometry.scale;
    let best = null, bestDistance = 14 * geometry.scale;
    for (const event of visibleEvents()) {
      const [ex, ey, visible] = screen(event.lon, event.lat, geometry);
      const distance = Math.hypot(ex - x, ey - y);
      if (visible && distance < bestDistance) { best = event; bestDistance = distance; }
    }
    return best;
  }

  function showCard(event) {
    selected = event;
    card.hidden = !event;
    if (!event) return;
    card.replaceChildren(
      h("span", { class: "world-card-layer", style: `color:${LAYERS[event.layer]?.color}` }, LAYERS[event.layer]?.label || event.layer),
      h("b", {}, event.title),
      h("span", { class: "muted small" }, [event.place, event.source, ago(event.time)].filter(Boolean).join(" · ")),
      event.url ? h("button", { class: "box small", type: "button", onclick: () => act("open_url", { url: event.url }) }, "Open the source") : null);
  }

  function flyTo(lon, lat, zoom = view.zoom) {
    flight = { from: { ...view }, to: { lon, lat, zoom: Math.max(0.7, Math.min(6, zoom)) }, start: performance.now(), duration: 1400 };
    lastTouch = performance.now();
  }

  function renderSide() {
    const counts = {};
    for (const event of events) counts[event.layer] = (counts[event.layer] || 0) + 1;
    layersBox.replaceChildren(...Object.entries(LAYERS).map(([layer, { label, color }]) => h("label", { class: "world-layer" },
      h("input", { type: "checkbox", checked: shown[layer], onchange: (event) => { shown[layer] = event.target.checked; renderSide(); } }),
      h("i", { style: `background:${color}` }), label, h("span", { class: "world-count" }, String(counts[layer] || 0)))));
    const items = visibleEvents().slice(0, 80);
    list.replaceChildren(...items.map((event) => h("li", {},
      h("button", { type: "button", onclick: () => { flyTo(event.lon, event.lat, Math.max(view.zoom, 2.2)); showCard(event); } },
        h("i", { style: `background:${LAYERS[event.layer]?.color}` }), h("span", {}, event.title),
        h("small", {}, [event.place, ago(event.time)].filter(Boolean).join(" · "))))));
    const problems = Object.keys(errors);
    $("#world-status").textContent = [`${events.length} events · last ${days === 1 ? "24 hours" : `${days} days`}`,
      newsOn ? "" : "news desk off: turn it on in BRIEF for news and conflict",
      problems.length ? `not reachable: ${problems.join(", ")}` : ""].filter(Boolean).join(" · ");
    for (const button of root.querySelectorAll("[data-world-days]")) button.classList.toggle("on", Number(button.dataset.worldDays) === days);
  }

  function setData(snapshot) {
    events = snapshot.events || [];
    errors = snapshot.errors || {};
    days = snapshot.days || days;
    newsOn = snapshot.news !== false;
    if (selected && !events.includes(selected)) showCard(null);
    renderSide();
  }

  async function load(force = false) {
    $("#world-status").textContent = "Loading the world…";
    const result = await act("world", { days, force });
    if (result && result.events) setData(result);
  }

  async function open(focus) {
    if (!opened) {
      opened = true;
      root.hidden = false;
      onOpenChange?.(true);
      await loadMap();
      frame = requestAnimationFrame(draw);
      load();
    }
    if (focus) {
      if (focus.days && focus.days !== days) { days = focus.days; load(); }
      if (Number.isFinite(focus.lon)) flyTo(focus.lon, focus.lat, focus.zoom || 2);
    }
  }

  function close() {
    if (!opened) return;
    opened = false;
    root.hidden = true;
    cancelAnimationFrame(frame);
    onOpenChange?.(false);
  }

  canvas.addEventListener("pointerdown", (event) => {
    dragging = { x: event.clientX, y: event.clientY, lon: view.lon, lat: view.lat, moved: false };
    canvas.setPointerCapture(event.pointerId);
    flight = null;
    lastTouch = performance.now();
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!dragging) { canvas.style.cursor = nearest(event.clientX, event.clientY) ? "pointer" : "grab"; return; }
    const degrees = 180 / (Math.PI * size().radius / (window.devicePixelRatio || 1));
    const dx = event.clientX - dragging.x, dy = event.clientY - dragging.y;
    if (Math.hypot(dx, dy) > 3) dragging.moved = true;
    view.lon = ((dragging.lon - dx * degrees + 540) % 360) - 180;
    view.lat = Math.max(-80, Math.min(80, dragging.lat + dy * degrees));
    lastTouch = performance.now();
  });
  canvas.addEventListener("pointerup", (event) => {
    if (dragging && !dragging.moved) showCard(nearest(event.clientX, event.clientY));
    dragging = null;
  });
  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    view.zoom = Math.max(0.7, Math.min(6, view.zoom * (event.deltaY < 0 ? 1.12 : 1 / 1.12)));
    flight = null;
    lastTouch = performance.now();
  }, { passive: false });
  $("#world-close").addEventListener("click", close);
  $("#world-refresh").addEventListener("click", () => load(true));
  for (const button of root.querySelectorAll("[data-world-days]")) {
    button.addEventListener("click", () => { days = Number(button.dataset.worldDays); load(); });
  }

  return { open, close, isOpen: () => opened, setData, flyTo, view: () => ({ ...view }), events: () => events.slice() };
}
