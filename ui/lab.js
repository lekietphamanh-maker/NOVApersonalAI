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
