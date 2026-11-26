// What Rea's and Shannon's screens share: opening and closing in the HUD frame, and the strip of past jobs at the
// bottom. Nova runs the jobs (reverse_engineering.py, shannon_runner.py); these pages only draw them.

export function h(tag, attributes = {}, ...children) {
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

export function when(iso) {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

// Open/close in the HUD frame; onOpen runs each time the screen opens (to fetch its jobs).
export function screen(root, { onOpenChange, onOpen }) {
  let opened = false;
  return {
    open() {
      if (opened) return;
      opened = true;
      root.hidden = false;
      onOpenChange?.(true);
      onOpen?.();
    },
    close() {
      if (!opened) return;
      opened = false;
      root.hidden = true;
      onOpenChange?.(false);
    },
    isOpen: () => opened,
  };
}

// The past jobs, newest first: each a button that brings that job back onto the screen.
export function renderStrip(container, jobs, activeId, onPick, describe) {
  container.replaceChildren(...(jobs.length ? jobs.map((job) => h("button", {
    type: "button", class: `lab-chip ${job.status}${job.id === activeId ? " on" : ""}`,
    title: job.target || job.title, onclick: () => onPick(job.id),
  }, h("b", {}, job.title || "job"), h("small", {}, `${when(job.started)} · ${describe(job)}`))) : [
    h("span", { class: "muted small" }, "Past reports show here. They're also in your Library."),
  ]));
}

// --- the full report, read on screen: plain Markdown-lite to safe HTML ---
// The reports come from Claude Code, so every line is escaped first and only the report's own
// structure is restored: # headings, - bullets, 1. numbered lines, ``` code blocks, the rest
// plain paragraphs. No raw HTML from a report ever reaches the page.
export function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

export function reportToHtml(text) {
  const lines = String(text || "").split("\n");
  const out = [];
  let inCode = false, code = [], list = null;
  const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };
  const closeCode = () => { out.push(`<pre><code>${code.map(escapeHtml).join("\n")}</code></pre>`); code = []; };
  for (const raw of lines) {
    const line = raw.replace(/\s+$/, "");
    if (line.trim().startsWith("```")) {
      closeList();
      if (inCode) closeCode();
      inCode = !inCode;
      continue;
    }
    if (inCode) { code.push(line); continue; }
    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      closeList();
      const level = Math.min(4, heading[1].length) + 1; // # -> h2, so the panel title stays the only h1
      out.push(`<h${level}>${escapeHtml(heading[2])}</h${level}>`);
      continue;
    }
    const bullet = line.match(/^\s*[-*]\s+(.*)$/);
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (bullet || numbered) {
      const tag = bullet ? "ul" : "ol";
      if (list !== tag) { closeList(); out.push(`<${tag}>`); list = tag; }
      out.push(`<li>${escapeHtml((bullet || numbered)[1])}</li>`);
      continue;
    }
    closeList();
    if (line.trim()) out.push(`<p>${escapeHtml(line.trim())}</p>`);
  }
  closeList();
  if (inCode) closeCode();
  return out.join("\n");
}

// A full report as a readable panel inside the HUD, on top of the screen that opened it: the
// whole text (not a summary, not a link), scrollable, with a footer for the caller's buttons.
// Returns a close() that removes it. Esc closes it too.
export function openReportPanel(root, { title, text, footer = [] }) {
  const close = () => panel.remove();
  const body = h("div", { class: "report-body" });
  body.innerHTML = reportToHtml(text);
  const panel = h("div", { class: "report-panel", role: "dialog", "aria-label": title },
    h("header", { class: "report-head" },
      h("b", {}, title),
      h("button", { class: "box small", type: "button", onclick: close }, "Close")),
    body,
    h("footer", { class: "report-foot" }, ...footer));
  root.append(panel);
  panel.querySelector("button").focus();
  panel.addEventListener("keydown", (event) => { if (event.key === "Escape") { event.stopPropagation(); close(); } });
  return close;
}
