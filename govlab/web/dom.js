// Small DOM helpers. Text always goes in as text nodes, never as HTML: speeches,
// thoughts and player names come from a model and are untrusted.

const SVG_NS = "http://www.w3.org/2000/svg";

function build(el, attrs, children) {
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.setAttribute("class", value);
    else if (key === "style" && typeof value === "object") Object.assign(el.style, value);
    else if (key.startsWith("on")) el.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === "dataset") Object.assign(el.dataset, value);
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

export const h = (tag, attrs, ...children) => build(document.createElement(tag), attrs, children);
export const s = (tag, attrs, ...children) => build(document.createElementNS(SVG_NS, tag), attrs, children);

export function clear(el) {
  el.replaceChildren();
  return el;
}

/** Append children the way h() does: arrays are flattened, null and false are skipped. */
export function add(el, ...children) {
  return build(el, null, children);
}

/** Replace an element's children. */
export function fill(el, ...children) {
  return add(clear(el), ...children);
}

export const fmt = {
  pct: (x, digits = 0) => (x === null || x === undefined ? "–" : `${(x * 100).toFixed(digits)}%`),
  num: (x, digits = 2) => (x === null || x === undefined ? "–" : Number(x).toFixed(digits)),
  int: (x) => (x === null || x === undefined ? "–" : Math.round(x).toLocaleString("en-US")),
  usd: (x) => {
    if (x === null || x === undefined) return "–";
    if (x === 0) return "$0";
    return x < 1 ? `$${x.toFixed(x < 0.1 ? 3 : 2)}` : `$${x.toFixed(2)}`;
  },
  p: (x) => (x === null || x === undefined ? "–" : x < 0.001 ? "<0.001" : x.toFixed(3)),
  minutes: (m) => {
    if (m === null || m === undefined) return "–";
    if (m < 1) return "under a minute";
    if (m < 90) return `${Math.round(m)} min`;
    return `${(m / 60).toFixed(1)} h`;
  },
  seconds: (sec) => (sec < 90 ? `${Math.round(sec)} s` : `${(sec / 60).toFixed(1)} min`),
  when: (iso) => new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }),
};

// --- one shared tooltip ------------------------------------------------------

const tip = () => document.getElementById("tooltip");

export function showTip(event, content) {
  const el = tip();
  fill(el, content);
  el.hidden = false;
  const pad = 14;
  const box = el.getBoundingClientRect();
  let x = event.clientX + pad;
  let y = event.clientY + pad;
  if (x + box.width > window.innerWidth - 8) x = event.clientX - box.width - pad;
  if (y + box.height > window.innerHeight - 8) y = event.clientY - box.height - pad;
  el.style.left = `${Math.max(8, x)}px`;
  el.style.top = `${Math.max(8, y)}px`;
}

export function hideTip() {
  tip().hidden = true;
}

/** Give an element a tooltip on hover and on keyboard focus. */
export function tipOn(el, content) {
  const make = () => (typeof content === "function" ? content() : content);
  el.addEventListener("pointermove", (e) => showTip(e, make()));
  el.addEventListener("pointerleave", hideTip);
  el.addEventListener("focus", () => {
    const box = el.getBoundingClientRect();
    showTip({ clientX: box.left + box.width / 2, clientY: box.bottom }, make());
  });
  el.addEventListener("blur", hideTip);
  return el;
}

let toastTimer;
export function toast(message, ms = 5000) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), ms);
}
