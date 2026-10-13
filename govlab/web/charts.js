// The five planned figures as SVG, from the same data the written report is drawn from.
//
// Colour is the vote threshold and nothing else (at most three validated hues).
// Protocol and ballot are positions: bar groups in the rate charts, panels in the line
// charts. Every mark has a hover and keyboard-focus readout; the tables below the
// charts carry the same numbers, so nothing is reachable by hover alone.

import { add, fmt, h, hideTip, s, showTip } from "./dom.js";

const SERIES = { plurality: "var(--series-plurality)", majority: "var(--series-majority)", supermajority: "var(--series-supermajority)" };
const KILLS = ["var(--kills-0)", "var(--kills-1)", "var(--kills-2)", "var(--kills-3)"];
const TICKS = [0, 0.25, 0.5, 0.75, 1];

function card(title, subtitle, legend, body, wide = false) {
  return h("figure", { class: `card chart-card${wide ? " wide" : ""}` }, h("figcaption", {}, h("div", { class: "chart-title" }, title), h("div", { class: "chart-sub" }, subtitle)), legend, h("div", { class: "chart" }, body));
}

function thresholdLegend(chart, line = false) {
  if (chart.thresholds.length < 2) return null; // one series: the title already names it
  return h("div", { class: "chart-legend" }, chart.thresholds.map((t) => h("span", {}, h("i", { class: `key${line ? " line" : ""}`, style: { background: SERIES[t] } }), chart.labels[t])));
}

function hover(el, content, group) {
  const on = (event) => {
    group?.classList.add("dim");
    el.classList.add("on");
    const box = el.getBoundingClientRect();
    showTip(event.clientX === undefined ? { clientX: box.left + box.width / 2, clientY: box.top } : event, content());
  };
  const off = () => {
    group?.classList.remove("dim");
    el.classList.remove("on");
    hideTip();
  };
  el.addEventListener("pointermove", on);
  el.addEventListener("pointerleave", off);
  el.addEventListener("focus", on);
  el.addEventListener("blur", off);
  el.setAttribute("tabindex", "0");
}

/** A bar with a 4px rounded data end and a square foot on the baseline. */
function barPath(x, y, w, hgt) {
  const r = Math.min(4, hgt, w / 2);
  return `M${x},${y + hgt}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + hgt}Z`;
}

// --- F1 and F4: a rate per condition with its Wilson interval ----------------------

export function rateBars(chart, measure, title, subtitle) {
  const W = 520, H = 262, m = { l: 42, r: 10, t: 22, b: 46 };
  const plotW = W - m.l - m.r, plotH = H - m.t - m.b;
  const y = (v) => m.t + plotH * (1 - v);
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": title });
  for (const tick of TICKS) {
    add(svg, s("line", { class: tick === 0 ? "baseline" : "gridline", x1: m.l, x2: W - m.r, y1: y(tick), y2: y(tick) }), s("text", { x: m.l - 8, y: y(tick) + 4, "text-anchor": "end" }, fmt.pct(tick)));
  }
  const marks = s("g", {});
  add(svg, marks);
  const band = plotW / chart.groups.length;
  const barW = Math.min(24, (band - 40) / chart.thresholds.length - 8);
  chart.groups.forEach((group, gi) => {
    const centre = m.l + band * (gi + 0.5);
    add(svg, s("text", { x: centre, y: H - 8, "text-anchor": "middle", style: "font-weight:600" }, group.label));
    chart.thresholds.forEach((threshold, ti) => {
      const cell = chart.cells[`${threshold}|${group.key}`];
      if (!cell || cell[measure].p === null) return;
      const p = cell[measure];
      const x = centre + (ti - (chart.thresholds.length - 1) / 2) * (barW + 10) - barW / 2;
      const g = s("g", { class: "mark" });
      add(g, 
        s("path", { d: barPath(x, y(p.p), barW, Math.max(y(0) - y(p.p), 0.5)), fill: SERIES[threshold] }),
        s("line", { class: "whisker", x1: x + barW / 2, x2: x + barW / 2, y1: y(p.high), y2: y(p.low) }),
        s("text", { class: "value", x: x + barW / 2, y: y(p.high) - 6, "text-anchor": "middle" }, fmt.pct(p.p)),
        s("text", { x: x + barW / 2, y: y(0) + 14, "text-anchor": "middle", style: "font-size:10.5px" }, `n=${p.n}`),
        s("rect", { class: "hit", x: x - 6, y: m.t, width: barW + 12, height: plotH }),
      );
      hover(g, () => [h("b", {}, cell.label), h("div", {}, `${fmt.pct(p.p)} (${p.k} of ${p.n} games)`), h("div", {}, `95% interval ${fmt.pct(p.low)} to ${fmt.pct(p.high)}`)], marks);
      add(marks, g);
    });
  });
  return card(title, subtitle, thresholdLegend(chart), svg);
}

// --- F2: how many kills the insider got, as a share of games -----------------------

export function killStack(chart) {
  const cells = Object.values(chart.cells);
  const W = 520, rowH = 40, m = { l: 168, r: 74, t: 6, b: 26 };
  const H = m.t + m.b + rowH * cells.length;
  const plotW = W - m.l - m.r;
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Kills per game by condition" });
  for (const tick of TICKS) add(svg, s("text", { x: m.l + plotW * tick, y: H - 6, "text-anchor": "middle" }, fmt.pct(tick)));
  const marks = s("g", {});
  add(svg, marks);
  cells.forEach((cell, row) => {
    const top = m.t + row * rowH + 8;
    add(svg, s("text", { x: m.l - 10, y: top + 16, "text-anchor": "end" }, cell.label), s("text", { class: "value", x: W - m.r + 10, y: top + 16 }, `mean ${fmt.num(cell.kills_mean)}`));
    let x = m.l;
    chart.kill_bins.forEach((bin, i) => {
      const n = cell.kills[bin];
      if (!n) return;
      const w = (plotW * n) / cell.n;
      const g = s("g", { class: "mark" });
      // a 2px gap in the surface colour separates the segments
      add(g, s("rect", { x: x + 1, y: top, width: Math.max(w - 2, 1), height: 24, rx: 3, fill: KILLS[i] }));
      if (w > 36) add(g, s("text", { x: x + w / 2, y: top + 16, "text-anchor": "middle", style: `fill:var(--kills-ink-${i});font-weight:600;font-size:11.5px` }, fmt.pct(n / cell.n)));
      hover(g, () => [h("b", {}, cell.label), h("div", {}, `${bin} kill${bin === "1" ? "" : "s"}: ${n} of ${cell.n} games (${fmt.pct(n / cell.n)})`)], marks);
      add(marks, g);
      x += w;
    });
  });
  const legend = h("div", { class: "chart-legend" }, chart.kill_bins.map((bin, i) => h("span", {}, h("i", { class: "key", style: { background: KILLS[i] } }), `${bin} kill${bin === "1" ? "" : "s"}`)));
  return card("Damage absorbed", "Share of games by the number of kills the insider made", legend, svg);
}

// --- F3 and F5: lines over time, one panel per protocol ----------------------------

function linePanel(chart, group, spec) {
  const W = 520, H = 236, m = { l: 44, r: 46, t: 12, b: 38 };
  const plotW = W - m.l - m.r, plotH = H - m.t - m.b;
  const x = (v) => m.l + (plotW * v) / spec.xMax;
  const y = (v) => m.t + plotH * (1 - v / spec.yMax);
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `${spec.title}: ${group.label}` });
  for (const tick of spec.yTicks) add(svg, s("line", { class: tick === 0 ? "baseline" : "gridline", x1: m.l, x2: W - m.r, y1: y(tick), y2: y(tick) }), s("text", { x: m.l - 8, y: y(tick) + 4, "text-anchor": "end" }, spec.yFormat(tick)));
  for (const tick of spec.xTicks) add(svg, s("text", { x: x(tick), y: H - 18, "text-anchor": "middle" }, tick));
  add(svg, s("text", { x: m.l + plotW / 2, y: H - 2, "text-anchor": "middle", style: "fill:var(--text-3)" }, spec.xLabel));

  const series = chart.thresholds.map((threshold) => ({ threshold, cell: chart.cells[`${threshold}|${group.key}`] })).filter((d) => d.cell).map((d) => ({ ...d, points: spec.points(d.cell) }));
  const ends = [];
  for (const { threshold, points } of series) {
    let d = "";
    points.forEach(([px, py], i) => {
      if (i === 0) d += `M${x(px)},${y(py)}`;
      else if (spec.step) d += `H${x(px)}V${y(py)}`;
      else d += `L${x(px)},${y(py)}`;
    });
    // a casing in the surface colour keeps crossing lines apart
    add(svg, s("path", { d, fill: "none", stroke: "var(--surface)", "stroke-width": 5, "stroke-linejoin": "round", "stroke-linecap": "round" }), s("path", { d, fill: "none", stroke: SERIES[threshold], "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
    const [lx, ly] = points.at(-1);
    add(svg, s("circle", { cx: x(lx), cy: y(ly), r: 4, fill: SERIES[threshold], stroke: "var(--surface)", "stroke-width": 2 }));
    ends.push({ x: x(lx) + 9, y: y(ly) + 4, text: spec.yFormat(ly) });
  }
  // end labels keep clear of each other
  ends.sort((a, b) => a.y - b.y).forEach((end, i, all) => {
    if (i && end.y - all[i - 1].y < 14) end.y = all[i - 1].y + 14;
    add(svg, s("text", { class: "value", x: end.x, y: end.y }, end.text));
  });

  // one crosshair, every series in the readout
  const cross = s("line", { class: "crosshair", y1: m.t, y2: m.t + plotH, visibility: "hidden" });
  const hit = s("rect", { class: "hit", x: m.l, y: m.t, width: plotW, height: plotH, tabindex: "0" });
  const readout = (at, event) => {
    cross.setAttribute("x1", x(at));
    cross.setAttribute("x2", x(at));
    cross.setAttribute("visibility", "visible");
    showTip(event, [h("b", {}, `${spec.xName} ${at}`), ...series.map(({ threshold, points }) => h("div", { class: "tt-row" }, h("i", { class: "key line", style: { background: SERIES[threshold] } }), h("b", {}, spec.yFormat(spec.valueAt(points, at))), ` ${chart.labels[threshold]}`))]);
  };
  hit.addEventListener("pointermove", (event) => {
    const box = svg.getBoundingClientRect();
    const at = Math.round((((event.clientX - box.left) / box.width) * W - m.l) / plotW * spec.xMax);
    readout(Math.max(0, Math.min(spec.xMax, at)), event);
  });
  let focusAt = spec.xMax;
  const focusReadout = () => {
    const box = svg.getBoundingClientRect();
    readout(focusAt, { clientX: box.left + (x(focusAt) / W) * box.width, clientY: box.top + 20 });
  };
  hit.addEventListener("focus", focusReadout);
  hit.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    focusAt = Math.max(0, Math.min(spec.xMax, focusAt + (event.key === "ArrowRight" ? 1 : -1)));
    focusReadout();
    event.preventDefault();
  });
  const leave = () => { cross.setAttribute("visibility", "hidden"); hideTip(); };
  hit.addEventListener("pointerleave", leave);
  hit.addEventListener("blur", leave);
  add(svg, cross, hit);
  return h("div", {}, chart.groups.length > 1 ? h("div", { class: "panel-title" }, group.label) : null, svg);
}

function linePanels(chart, spec) {
  const panels = h("div", { class: "panels", style: { gridTemplateColumns: `repeat(${Math.min(chart.groups.length, 2)}, minmax(0, 1fr))` } }, chart.groups.map((group) => linePanel(chart, group, spec)));
  return card(spec.title, spec.subtitle, thresholdLegend(chart, true), panels, chart.groups.length > 1);
}

function niceTicks(max, count = 4) {
  const step = [0.1, 0.2, 0.25, 0.5, 1, 2, 5].find((c) => max / c <= count) || 10;
  const ticks = [];
  for (let v = 0; v < max + step - 1e-9; v += step) ticks.push(Number(v.toFixed(2))); // the last tick covers max
  return ticks;
}

export function cumulativeDamage(chart) {
  const top = Math.max(...Object.values(chart.cells).flatMap((c) => c.cumulative.map((p) => p.mean)), 0.5);
  const yTicks = niceTicks(top);
  const xMax = Math.max(chart.max_timestep, 1);
  return linePanels(chart, {
    title: "When the damage happens",
    subtitle: "Mean kills per game so far, by timestep. A finished game keeps its total.",
    xLabel: "Timestep", xName: "After timestep", xMax,
    xTicks: niceSteps(xMax),
    yMax: yTicks.at(-1), yTicks,
    yFormat: (v) => fmt.num(v),
    points: (cell) => cell.cumulative.map((p) => [p.t, p.mean]),
    valueAt: (points, at) => points[Math.min(at, points.length - 1)][1],
    step: false,
  });
}

export function detection(chart) {
  const xMax = Math.max(chart.max_meetings, 1);
  return linePanels(chart, {
    title: "How long the insider survives",
    subtitle: "Share of games in which the insider has not been ejected after each meeting (Kaplan–Meier; games that end first are censored).",
    xLabel: "Meetings held", xName: "After meeting", xMax,
    xTicks: Array.from({ length: xMax + 1 }, (_, i) => i),
    yMax: 1, yTicks: TICKS,
    yFormat: (v) => fmt.pct(v),
    points: (cell) => [...cell.survival.map((p) => [p.t, p.s]), [Math.max(cell.meetings_max, 1), cell.survival.at(-1).s]],
    valueAt: (points, at) => points.filter(([t]) => t <= at).at(-1)[1],
    step: true,
  });
}

function niceSteps(max) {
  const step = [1, 2, 5, 10, 20, 50].find((c) => max / c <= 7) || 100;
  const ticks = [];
  for (let v = 0; v <= max; v += step) ticks.push(v);
  return ticks;
}
