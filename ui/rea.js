// Rea's Blueprint: the analysed app drawn as its main parts (glowing boxes in columns: interface → logic → network →
// data) with the links between them. Click a part to see what Rea found in it; past reports are in the strip below.

import { h, s, when, screen, renderStrip, renderFeed } from "./lab.js";

const COLUMNS = [["ui"], ["logic", "native"], ["network", "external"], ["data", "storage"]];
const COLUMN_NAMES = ["Interface", "Logic", "Network", "Data"];
const WIDTH = 1000, HEIGHT = 600, BOX_W = 190, BOX_H = 62;

function column(kind) {
  const index = COLUMNS.findIndex((kinds) => kinds.includes(kind));
  return index < 0 ? 1 : index;
}

// Where each part sits: used columns spread across the width, parts spread down their column.
function layout(parts) {
  const used = [...new Set(parts.map((part) => column(part.kind)))].sort();
  const places = new Map();
  used.forEach((columnIndex, position) => {
    const members = parts.filter((part) => column(part.kind) === columnIndex);
    const x = (WIDTH / used.length) * (position + 0.5);
    members.forEach((part, row) => places.set(part.id, { x, y: (HEIGHT / members.length) * (row + 0.5) + 14 }));
  });
  return { places, columns: used.map((columnIndex, position) => ({ name: COLUMN_NAMES[columnIndex], x: (WIDTH / used.length) * (position + 0.5) })) };
}

// The link's path, and where its label sits (the middle of the curve).
function curve(from, to) {
  const middleY = (from.y + to.y) / 2;
  if (Math.abs(from.x - to.x) < 1) { // same column: bow out to the right
    const edge = from.x + BOX_W / 2, bend = edge + 60;
    return { d: `M${edge},${from.y} C${bend},${from.y} ${bend},${to.y} ${edge},${to.y}`, x: edge + 45, y: middleY };
  }
  const direction = to.x > from.x ? 1 : -1;
  const start = from.x + (direction * BOX_W) / 2, end = to.x - (direction * BOX_W) / 2, middle = (start + end) / 2;
  return { d: `M${start},${from.y} C${middle},${from.y} ${middle},${to.y} ${end},${to.y}`, x: middle, y: middleY };
}

export function createRea(root, { act, onOpenChange }) {
  const $ = (selector) => root.querySelector(selector);
  const stage = $("#rea-stage"), side = $("#rea-side"), strip = $("#rea-strip"), problemLine = $("#rea-problem");
  let jobs = [], job = null, selected = "", steps = [];
  const view = screen(root, { onOpenChange, onOpen: refresh });

  async function refresh() {
    const result = await act("rea_view");
    if (!result.ok) return;
    jobs = result.jobs || [];
    drawStrip();
    if (!job && jobs[0]) pick(jobs[0].id);
    else if (!job) render();
  }

  async function pick(id) {
    const result = await act("rea_open", { id });
    if (!result.ok) return;
    job = result.job;
    selected = "";
    steps = job.steps || [];
    drawStrip();
    render();
  }

  function drawStrip() {
    renderStrip(strip, jobs, job?.id, pick, (item) => (item.status === "running" ? "analysing…"
      : item.status === "failed" ? "stopped" : `${item.counts?.parts ?? 0} parts`));
  }

  function render() {
    if (!job) {
      stage.replaceChildren(h("div", { class: "lab-empty" }, h("b", {}, "Nothing analysed yet"),
        h("span", {}, "Type an app, file, folder or site above and what you want to know, or say “reverse engineer …”.")));
      side.replaceChildren(h("p", { class: "muted small" }, "Rea works through Claude Code on your plan. Only analyse software you're allowed to."));
      return;
    }
    if (job.status === "running") return renderRunning();
    if (job.status === "failed" || !job.blueprint?.parts?.length) {
      stage.replaceChildren(h("div", { class: "lab-empty" }, h("b", {}, job.status === "failed" ? "Rea stopped" : "No blueprint in this report"),
        h("span", {}, job.error || "The written report is still there.")));
      return renderOverview();
    }
    renderBlueprint();
    selected ? renderPart() : renderOverview();
  }

  function renderRunning() {
    const feed = h("ol", { class: "lab-feed" });
    stage.replaceChildren(h("div", { class: "lab-scan" }, h("div", { class: "lab-radar", "aria-hidden": "true" }),
      h("b", {}, `Analysing ${job.title}`), h("span", { class: "muted small" }, job.goal || "how it works, overall")));
    side.replaceChildren(h("h4", {}, "Live"), feed);
    renderFeed(feed, steps.length ? steps : ["Starting Claude Code with REA…"]);
  }

  function renderBlueprint() {
    const { parts, links } = job.blueprint;
    const { places, columns } = layout(parts);
    const svg = s("svg", { viewBox: `0 0 ${WIDTH} ${HEIGHT + 30}`, class: "rea-blueprint", role: "img",
      "aria-label": `Blueprint of ${job.title}: ${parts.map((part) => part.name).join(", ")}` },
      s("defs", {}, s("filter", { id: "rea-glow", x: "-30%", y: "-30%", width: "160%", height: "160%" },
        s("feGaussianBlur", { stdDeviation: "5", result: "blur" }),
        s("feMerge", {}, s("feMergeNode", { in: "blur" }), s("feMergeNode", { in: "SourceGraphic" })))));
    for (const item of columns) svg.append(s("text", { x: item.x, y: 18, class: "rea-column" }, item.name.toUpperCase()));
    for (const link of links) {
      const from = places.get(link.from), to = places.get(link.to);
      if (!from || !to) continue;
      const lit = selected && (link.from === selected || link.to === selected);
      const path = curve(from, to);
      svg.append(s("path", { d: path.d, class: `rea-link${lit ? " lit" : ""}` }));
      if (link.label) svg.append(s("text", { x: path.x, y: path.y - 6, class: `rea-link-label${lit ? " lit" : ""}` }, link.label));
    }
    for (const part of parts) {
      const place = places.get(part.id);
      const group = s("g", { class: `rea-part${part.id === selected ? " on" : ""}`, tabindex: "0", role: "button",
        "aria-label": `${part.name}, ${part.kind}`, transform: `translate(${place.x - BOX_W / 2},${place.y - BOX_H / 2})`,
        onclick: () => choose(part.id), onkeydown: (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); choose(part.id); } } },
        s("rect", { width: BOX_W, height: BOX_H, rx: 6, filter: "url(#rea-glow)" }),
        s("text", { x: 14, y: 26, class: "rea-name" }, part.name.length > 22 ? `${part.name.slice(0, 21)}…` : part.name),
        s("text", { x: 14, y: 46, class: "rea-kind" }, `${part.kind.toUpperCase()}${part.findings.length ? ` · ${part.findings.length} FOUND` : ""}`));
      svg.append(group);
    }
    stage.replaceChildren(svg);
  }

  function choose(id) {
    selected = selected === id ? "" : id;
    render();
  }

  function renderOverview() {
    const summary = (job.summary || "").split("\n").filter(Boolean).map((line) => h("p", {}, line.replace(/^#+\s*/, "")));
    side.replaceChildren(h("h4", {}, job.title), h("p", { class: "muted small" }, `${when(job.started)} · ${job.target}`),
      ...summary,
      job.report ? h("button", { class: "box small on", type: "button", onclick: () => act("rea_report", { id: job.id }) }, "Open full report") : null,
      job.blueprint?.parts?.length ? h("p", { class: "muted small" }, "Click a part to see what Rea found in it.") : null);
  }

  function renderPart() {
    const part = job.blueprint.parts.find((item) => item.id === selected);
    if (!part) return renderOverview();
    const name = (id) => job.blueprint.parts.find((item) => item.id === id)?.name || id;
    const talks = job.blueprint.links.filter((link) => link.from === part.id || link.to === part.id)
      .map((link) => h("li", {}, link.from === part.id ? `→ ${name(link.to)}` : `← ${name(link.from)}`, link.label ? h("small", {}, ` ${link.label}`) : null));
    side.replaceChildren(h("span", { class: "lab-tag" }, part.kind), h("h4", {}, part.name), h("p", {}, part.summary),
      part.findings.length ? h("h5", {}, "Found") : null, h("ul", { class: "lab-list" }, part.findings.map((item) => h("li", {}, item))),
      talks.length ? h("h5", {}, "Talks to") : null, h("ul", { class: "lab-list" }, talks),
      h("button", { class: "box small", type: "button", onclick: () => choose(part.id) }, "Back to overview"));
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
    job(next) { // a job started or ended
      jobs = [next, ...jobs.filter((item) => item.id !== next.id)];
      if (next.status === "running" && (!job || job.status !== "running")) { job = next; steps = []; selected = ""; }
      if (job?.id === next.id) next.status === "running" ? render() : pick(next.id);
      drawStrip();
    },
    step({ id, line }) {
      if (job?.id !== id) return;
      steps.push(line);
      const feed = side.querySelector(".lab-feed");
      if (feed) renderFeed(feed, steps);
    },
    ready({ problem }) {
      problemLine.hidden = !problem;
      problemLine.textContent = problem ? `Can't run Rea here yet: ${problem}.` : "";
    },
  };
}
