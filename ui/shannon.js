// Shannon's Mission board: pick a project and its running app, Run, and watch the five stages light up
// (recon → analysis → exploit → validate → report). The holes Shannon proved come out as cards, worst first, each with
// its proof and the fix. Past checks are in the strip below.

import { h, when, screen, renderStrip, renderFeed } from "./lab.js";

const STAGES = [["recon", "Recon", "maps the code and the app"], ["analysis", "Analysis", "looks for weak spots"],
  ["exploit", "Exploit", "really tries to break in"], ["validate", "Validate", "keeps only what it proved"],
  ["report", "Report", "proof and fix for each"]];
const SEVERITIES = ["critical", "high", "medium", "low"];

export function createShannon(root, { act, onOpenChange }) {
  const $ = (selector) => root.querySelector(selector);
  const board = $("#shannon-board"), side = $("#shannon-side"), strip = $("#shannon-strip"), problemLine = $("#shannon-problem");
  const form = $("#shannon-form"), stopButton = $("#shannon-stop");
  let jobs = [], job = null, log = [], running = "";
  const view = screen(root, { onOpenChange, onOpen: refresh });

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
    drawStrip();
    render();
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

  function renderStages() {
    const reached = job ? (job.status === "done" ? STAGES.length - 1 : STAGES.findIndex(([key]) => key === job.stage)) : -1;
    return h("ol", { class: "shannon-stages", "aria-label": "Stages" }, STAGES.map(([key, name, what], index) => h("li", {
      class: `${index <= reached ? "lit" : ""}${job?.status === "running" && index === Math.max(0, reached) ? " now" : ""}`,
      "aria-current": job?.status === "running" && index === Math.max(0, reached) ? "step" : null,
    }, h("i", { "aria-hidden": "true" }), h("b", {}, name), h("small", {}, what))));
  }

  function card(finding) {
    return h("article", { class: `shannon-card ${finding.severity}` },
      h("header", {}, h("span", { class: "shannon-severity" }, finding.severity), h("span", { class: "lab-tag" }, finding.kind)),
      h("b", {}, finding.title), finding.where ? h("code", {}, finding.where) : null,
      h("details", {}, h("summary", {}, "Proof"), h("p", {}, finding.proof || "In the full report.")),
      finding.fix ? h("details", {}, h("summary", {}, "Fix"), h("p", {}, finding.fix)) : null);
  }

  function render() {
    const parts = [renderStages()];
    if (!job) {
      parts.push(h("div", { class: "lab-empty" }, h("b", {}, "No checks yet"),
        h("span", {}, "Pick one of your projects, give the address it runs at on this PC (like localhost:3000), and Run.")));
    } else if (job.status === "running") {
      parts.push(h("div", { class: "lab-empty" }, h("b", {}, `Checking ${job.title}`),
        h("span", {}, `${job.target} · a full run takes about an hour or two`)));
    } else if (job.status === "failed") {
      parts.push(h("div", { class: "lab-empty" }, h("b", {}, "Shannon stopped"), h("span", {}, job.error || "")));
    } else if (!job.findings?.length) {
      parts.push(h("div", { class: "lab-empty" }, h("b", {}, "No proven holes"),
        h("span", {}, "Shannon couldn't break in anywhere it tried. The report says what it tested.")));
    } else {
      parts.push(h("div", { class: "shannon-cards" }, job.findings.map(card)));
    }
    board.replaceChildren(...parts);
    const feed = h("ol", { class: "lab-feed" });
    side.replaceChildren(
      job ? h("h4", {}, job.title) : h("h4", {}, "Shannon"),
      job ? h("p", { class: "muted small" }, `${when(job.started)} · ${job.target}`) : null,
      job?.report ? h("button", { class: "box small on", type: "button", onclick: () => act("shannon_report", { id: job.id }) }, "Open full report") : null,
      h("h5", {}, job?.status === "running" ? "Live" : "Log"), feed);
    renderFeed(feed, log.length ? log : ["Shannon's own output shows here while it runs."]);
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    problemLine.hidden = true;
    await act("shannon_start", { project: form.project.value, url: form.url.value });
  });
  stopButton.onclick = () => act("shannon_stop");
  $("#shannon-close").onclick = () => view.close();

  return {
    ...view,
    job(next) {
      jobs = [next, ...jobs.filter((item) => item.id !== next.id)];
      running = next.status === "running" ? next.id : (running === next.id ? "" : running);
      if (next.status === "running" && job?.id !== next.id && (!job || job.status !== "running")) { job = next; log = []; }
      if (job?.id === next.id) { job = { ...job, ...next }; render(); }
      drawStrip();
    },
    line({ id, line }) {
      if (job?.id !== id) return;
      log.push(line);
      const feed = side.querySelector(".lab-feed");
      if (feed) renderFeed(feed, log);
    },
    ready({ problem }) {
      problemLine.hidden = !problem;
      problemLine.textContent = problem ? `Can't run Shannon here yet: ${problem}.` : "";
    },
  };
}
