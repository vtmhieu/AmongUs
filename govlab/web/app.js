// Shell: shared state, the API client, the top bar and the router.

import { add, clear, fill, h, hideTip, toast } from "./dom.js";
import { mountDesign } from "./design.js";
import { mountResults } from "./results.js";
import { mountWatch } from "./watch.js";

export const app = { meta: null, runs: [] };

export const api = {
  async request(method, path, body) {
    const response = await fetch(path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!response.ok) {
      let detail = `${response.status} ${response.statusText}`;
      try {
        detail = (await response.json()).detail || detail;
      } catch {}
      throw new Error(detail);
    }
    return response.json();
  },
  get: (path) => api.request("GET", path),
  post: (path, body) => api.request("POST", path, body || {}),
};

// --- labels ------------------------------------------------------------------

export function label(level) {
  return app.meta.labels[level] || level;
}

/** "majority/justification" -> "Majority · Justification" */
export function conditionLabel(condition) {
  return condition.split("/").map(label).join(" · ");
}

export const STATUS = {
  created: ["Created", ""],
  running: ["Running", "accent live"],
  completed: ["Completed", "good"],
  stopped: ["Stopped", "warn"],
  interrupted: ["Interrupted", "warn"],
  budget: ["Budget reached", "warn"],
  failed: ["Failed", "bad"],
  unknown: ["Unknown", ""],
};

export function statusPill(state) {
  const [text, cls] = STATUS[state] || STATUS.unknown;
  return h("span", { class: `pill ${cls}` }, text);
}

// --- routing -----------------------------------------------------------------

const TABS = [
  ["design", "Design"],
  ["watch", "Watch"],
  ["results", "Results"],
];

function route() {
  const [tab = "design", runId = null, gameId = null] = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  return { tab: TABS.some(([t]) => t === tab) ? tab : "design", runId, gameId };
}

export function go(tab, runId, gameId) {
  location.hash = "#/" + [tab, runId, gameId].filter(Boolean).join("/");
}

/** Replace the hash without re-rendering the view (used when the watched game changes). */
export function setHashQuietly(tab, runId, gameId) {
  quiet = true;
  history.replaceState(null, "", "#/" + [tab, runId, gameId].filter(Boolean).join("/"));
  quiet = false;
}

let quiet = false;
let unmount = null;

export async function refreshRuns() {
  app.runs = await api.get("/api/runs");
  renderTopbar();
  return app.runs;
}

function currentRunId() {
  return route().runId || localStorage.getItem("govlab.run") || app.runs[0]?.run_id || null;
}

function renderTopbar() {
  const { tab } = route();
  const runId = currentRunId();
  const tabs = clear(document.getElementById("tabs"));
  for (const [id, name] of TABS) {
    const href = id === "design" ? "#/design" : `#/${id}${runId ? "/" + runId : ""}`;
    add(tabs, h("a", { class: "tab", href, "aria-current": id === tab ? "page" : null }, name));
  }
  const picker = clear(document.getElementById("run-picker"));
  if (!app.runs.length) add(picker, h("option", { value: "" }, "No runs yet"));
  for (const run of app.runs) {
    const state = (STATUS[run.status.state] || STATUS.unknown)[0];
    add(picker, h("option", { value: run.run_id, selected: run.run_id === runId }, `${run.name} · ${state} · ${run.valid}/${run.total}`));
  }
  picker.disabled = !app.runs.length;
  picker.onchange = () => go(tab === "design" ? "watch" : tab, picker.value);

  const key = document.getElementById("key-status");
  key.className = `pill ${app.meta.credentials ? "good" : "warn"}`;
  key.textContent = app.meta.credentials ? "Claude API key found" : "No Claude API key";
  key.title = app.meta.credentials
    ? "Experiments can call the Claude API."
    : "Add ANTHROPIC_API_KEY to the .env file at the repository root and restart the server. The offline mock works without it.";
}

async function render() {
  if (quiet) return;
  const { tab, runId: routeRun, gameId } = route();
  if (unmount) unmount();
  unmount = null;
  hideTip(); // a tooltip must not outlive the view it belonged to
  const runId = routeRun || (tab !== "design" ? currentRunId() : null);
  if (routeRun) localStorage.setItem("govlab.run", routeRun);
  if (runId && !app.runs.some((r) => r.run_id === runId)) await refreshRuns().catch(() => {});
  renderTopbar();
  const view = clear(document.getElementById("view"));
  window.scrollTo(0, 0);
  try {
    if (tab === "design") unmount = await mountDesign(view);
    else if (!runId) add(view, noRuns());
    else if (tab === "watch") unmount = await mountWatch(view, runId, gameId);
    else unmount = await mountResults(view, runId);
  } catch (error) {
    fill(view, h("div", { class: "page" }, h("div", { class: "notice error" }, error.message)));
  }
}

function noRuns() {
  return h(
    "div",
    { class: "page" },
    h("div", { class: "card empty" }, h("h2", {}, "No runs yet"), h("p", {}, "Set up an experiment in Design, then come back here to watch it."), h("p", { style: { marginTop: "18px" } }, h("a", { class: "button primary", href: "#/design" }, "Design an experiment"))),
  );
}

// --- theme -------------------------------------------------------------------

function applyTheme(theme) {
  if (theme) document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
  const dark = theme ? theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  document.getElementById("theme-toggle").textContent = dark ? "☀" : "☾";
}

function initTheme() {
  applyTheme(localStorage.getItem("govlab.theme"));
  document.getElementById("theme-toggle").onclick = () => {
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    const next = dark ? "light" : "dark";
    localStorage.setItem("govlab.theme", next);
    applyTheme(next);
  };
}

async function start() {
  initTheme();
  try {
    app.meta = await api.get("/api/meta");
    await refreshRuns();
  } catch (error) {
    add(document.getElementById("view"), h("div", { class: "page" }, h("div", { class: "notice error" }, `Could not reach the server: ${error.message}`)));
    return;
  }
  window.addEventListener("hashchange", render);
  render();
}

window.addEventListener("unhandledrejection", (event) => toast(event.reason?.message || String(event.reason)));
start();
