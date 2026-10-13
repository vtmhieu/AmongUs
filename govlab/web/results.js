// Results: the checks to make before interpreting, the five figures, and the planned tests.

import { api, conditionLabel, statusPill } from "./app.js";
import { cumulativeDamage, detection, killStack, rateBars } from "./charts.js";
import { add, fill, fmt, h, toast } from "./dom.js";

const RATIO = { odds_ratio: "OR", rate_ratio: "RR", hazard_ratio: "HR", risk_difference: "RD", cliffs_delta: "δ" };
const VERDICT = { supported: "good", contradicted: "bad", inconclusive: "", "not testable": "" };

function interval(p) {
  return p.p === null ? "–" : `${fmt.pct(p.p)}  [${fmt.pct(p.low)}, ${fmt.pct(p.high)}]`;
}

function effect(e) {
  if (e.value === null || e.value === undefined) return "–";
  const name = RATIO[e.measure];
  return e.low === null ? `${name} ${fmt.num(e.value)}` : `${name} ${fmt.num(e.value)}  [${fmt.num(e.low)}, ${fmt.num(e.high)}]`;
}

function table(headers, rows) {
  return h(
    "div",
    { class: "table-scroll" },
    h(
      "table",
      { class: "data" },
      h("thead", {}, h("tr", {}, headers.map(([text, cls]) => h("th", { class: cls || null, scope: "col" }, text)))),
      h("tbody", {}, rows.map((row) => h("tr", {}, row.map((cell, i) => h("td", { class: headers[i][1] || null }, cell))))),
    ),
  );
}

function stat(labelText, value, note) {
  return h("div", { class: "stat" }, h("div", { class: "stat-label" }, labelText), h("div", { class: "stat-value" }, value), note ? h("div", { class: "stat-note" }, note) : null);
}

function modelBlock(title, model) {
  if (!model) return null;
  const key = model.terms ? Object.keys(RATIO).find((k) => k in model.terms[0]) : null;
  return h(
    "details",
    { class: "prompt" },
    h("summary", {}, title, h("span", { class: "faint" }, ` · ${model.model}, n = ${model.n}`)),
    model.ok
      ? h(
          "div",
          { style: { padding: "8px 0 4px" } },
          model.note ? h("p", { class: "small muted", style: { marginBottom: "6px" } }, model.note + ".") : null,
          table(
            [["Term"], [RATIO[key], "num"], ["95% interval", "num"], ["p", "num"]],
            model.terms.filter((t) => t.term !== "intercept").map((t) => [t.term, fmt.num(t[key]), t[`${key}_low`] === null ? "–" : `[${fmt.num(t[`${key}_low`])}, ${fmt.num(t[`${key}_high`])}]`, fmt.p(t.p)]),
          ),
        )
      : h("p", { class: "small muted", style: { padding: "8px 0" } }, `Not estimated: ${model.reason}.`),
  );
}

export async function mountResults(view, runId) {
  const page = h("div", { class: "page" });
  add(view, page);
  let timer = null;
  let disposed = false;

  async function load(withFigures = false) {
    const results = await api.get(`/api/runs/${runId}/results${withFigures ? "?figures=true" : ""}`);
    if (disposed) return;
    const scroll = window.scrollY;
    render(results);
    window.scrollTo(0, scroll);
    clearTimeout(timer);
    if (results.run.status.state === "running") timer = setTimeout(() => load().catch(() => {}), 8000);
  }

  function render(r) {
    const run = r.run;
    const q = r.quality;
    const file = (path) => `/api/runs/${runId}/files/${path}`;
    fill(page, 
      h(
        "div",
        { class: "page-head", style: { maxWidth: "none", display: "flex", justifyContent: "space-between", gap: "20px", alignItems: "flex-end", flexWrap: "wrap" } },
        h("div", {}, h("div", { class: "eyebrow" }, "Results"), h("h1", {}, run.name), h("p", {}, `${q.valid_games} valid games of ${run.total} scheduled · ${run.model} · `, statusPill(run.status.state))),
        h("div", { class: "downloads" }, h("a", { class: "button", href: `#/watch/${runId}` }, "Watch games"), h("button", { class: "button", type: "button", onClick: () => load().then(() => toast("Results refreshed.", 2000)) }, "Refresh")),
      ),
    );
    if (r.is_mock) add(page, h("div", { class: "notice info", style: { marginBottom: "16px" } }, h("b", {}, "Offline mock run. "), "These games were played by scripted players, not by a model. The numbers exercise the pipeline and are not findings."));
    if (!r.ok) {
      add(page, h("div", { class: "card empty" }, h("h2", {}, "Nothing to analyse yet"), h("p", {}, run.status.state === "running" ? "Results appear here as games finish." : r.reason)));
      return;
    }

    // --- checks ---------------------------------------------------------------
    const changed = q.rule_changed_outcome;
    add(page, 
      h(
        "section",
        { class: "card" },
        h("div", { class: "card-head" }, h("h2", {}, "Before interpreting")),
        h("p", { class: "card-sub" }, "The pilot's go/no-go checks. All three should pass before the main experiment is run with these settings."),
        h("div", { class: "gates" }, q.gates.map((g) => h("div", { class: "gate" }, h("div", { class: "gate-title" }, h("span", { class: `pill ${g.pass ? "good" : "bad"}` }, g.pass ? "Pass" : "Fail"), g.label), h("p", {}, g.detail[0].toUpperCase() + g.detail.slice(1) + ".")))),
        h(
          "div",
          { class: "stats-row" },
          stat("Rule changed the outcome", changed.p === null ? "–" : fmt.pct(changed.p), `${changed.k} of ${changed.n} meetings: the manipulation check`),
          "justification_compliance" in q ? stat("Protocol compliance", fmt.pct(q.justification_compliance), "valid final-round justifications") : null,
          stat("Cost per game", run.provider === "mock" ? "free" : fmt.usd(q.cost_per_game_usd), `${fmt.usd(q.cost_usd)} spent in total`),
          stat("Time per game", fmt.seconds(q.seconds_per_game), `${fmt.int(q.calls_per_game)} model calls`),
          stat("Tokens per call", fmt.int(q.prompt_tokens_per_call), `${fmt.int(q.output_tokens_per_call)} out · ${fmt.pct(q.cache_hit_share)} from cache`),
          stat("Excluded", q.invalid_attempts, Object.entries(q.invalid_reasons).map(([k, n]) => `${n} ${k.replaceAll("_", " ")}`).join(", ") || "no game had to be replayed"),
        ),
        h(
          "details",
          { class: "prompt", style: { marginTop: "16px" } },
          h("summary", {}, "What the full experiment would take at these rates"),
          h("div", { style: { padding: "8px 0 2px" } }, table(
            [["Games per condition"], ["Games", "num"], ["Cost", "num"], ["Time", "num"], ["Detectable difference", "num"]],
            Object.entries(q.projection).map(([n, p]) => [n, p.games, run.provider === "mock" ? "free" : fmt.usd(p.cost_usd), fmt.minutes(p.minutes), p.detectable_difference ? `≈ ${Math.round(p.detectable_difference * 100)} points` : "–"]),
          )),
        ),
      ),
    );

    // --- figures --------------------------------------------------------------
    const c = r.charts;
    add(page, 
      h("div", { class: "section-title" }, h("h2", {}, "Figures")),
      h(
        "div",
        { class: "charts" },
        rateBars(c, "win", "Good-team win rate", "Share of games the crew won, with 95% intervals"),
        rateBars(c, "wrongful", "Wrongful removal", "Share of games in which a good agent was ejected, with 95% intervals"),
        killStack(c),
        h("figure", { class: "card chart-card" }, h("div", { class: "chart-title" }, "How the games ended"), h("div", { class: "chart-sub" }, "Number of games by ending, per condition"), endings(r.cells)),
        cumulativeDamage(c),
        detection(c),
      ),
    );

    // --- conditions -----------------------------------------------------------
    add(page, 
      h("div", { class: "section-title" }, h("h2", {}, "Conditions")),
      h(
        "section",
        { class: "card" },
        table(
          [["Condition"], ["n", "num"], ["Crew win", "num"], ["Wrongful removal", "num"], ["Insider ejected", "num"], ["Kills, mean", "num"], ["Kills per task step", "num"], ["Meetings, mean", "num"]],
          r.cells.map((cell) => [conditionLabel(cell.condition), cell.n, interval(cell.crew_win), interval(cell.wrongful_any), interval(cell.insider_ejected), fmt.num(cell.kills_mean), fmt.num(cell.kills_per_exposure, 3), fmt.num(cell.meetings_mean)]),
        ),
        h("p", { class: "field-hint" }, "Brackets are 95% Wilson intervals."),
      ),
    );

    // --- tests ----------------------------------------------------------------
    if (r.confirmatory.length) {
      add(page, 
        h("div", { class: "section-title" }, h("h2", {}, "Planned comparisons")),
        h(
          "section",
          { class: "card" },
          h("p", { class: "card-sub" }, "Two-sided at α = 0.05, Holm-corrected as one family. Read the effect sizes and their intervals; with this sample only large effects are detectable."),
          table(
            [[""], ["Question"], ["Contrast"], ["Effect  [95% interval]", "num"], ["Test"], ["p", "num"], ["p, Holm", "num"]],
            r.confirmatory.map((t) => [h("b", {}, t.id), t.question.replace("->", "→"), t.contrast, effect(t.effect), t.fallback_reason ? h("span", { title: `Regression not estimated: ${t.fallback_reason}` }, `${t.test} *`) : t.test, fmt.p(t.p), t.significant ? h("b", {}, fmt.p(t.p_holm)) : fmt.p(t.p_holm)]),
          ),
          h("p", { class: "field-hint" }, "OR odds ratio · RR rate ratio · RD risk difference · δ Cliff's delta. * the regression could not be estimated on this sample, so the exact test is shown."),
        ),
        h(
          "section",
          { class: "card" },
          h("div", { class: "card-head" }, h("h2", {}, "Hypotheses")),
          h("p", { class: "card-sub" }, "The research plan's decision rules, applied mechanically. Inconclusive is the expected reading for effects smaller than the study can detect, not evidence of no effect."),
          r.hypotheses.map((hyp) => h("div", { class: "hypothesis" }, h("div", {}, h("span", { class: `pill ${VERDICT[hyp.verdict]}` }, `${hyp.id} · ${hyp.verdict}`)), h("div", {}, h("p", {}, hyp.statement), h("p", { class: "small muted", style: { marginTop: "3px" } }, hyp.why[0].toUpperCase() + hyp.why.slice(1) + ".")))),
        ),
      );
    } else if (r.note) {
      add(page, h("div", { class: "notice info", style: { marginTop: "16px" } }, "This run has one condition, so there is nothing to compare. The figures and table above describe it."));
    }

    // --- models and files -----------------------------------------------------
    const d = r.detection;
    add(page, 
      h("div", { class: "section-title" }, h("h2", {}, "Models and files")),
      h(
        "section",
        { class: "card" },
        modelBlock("Good-team win, main effects", r.models.crew_win?.main),
        modelBlock("Good-team win, with interaction", r.models.crew_win?.interaction),
        modelBlock("Wrongful removal, main effects", r.models.wrongful_any?.main),
        modelBlock("Wrongful removal, with interaction", r.models.wrongful_any?.interaction),
        modelBlock("Damage, main effects", r.models.kills?.main),
        modelBlock("Damage, with interaction", r.models.kills?.interaction),
        modelBlock("Detection time, main effects", d.cox.main),
        modelBlock("Detection time, with interaction", d.cox.interaction),
        Object.entries(d.logrank).map(([factor, test]) => h("p", { class: "small muted", style: { paddingTop: "10px" } }, test.ok ? `Log-rank test across ${factor}: χ²(${test.df}) = ${fmt.num(test.chi2)}, p = ${fmt.p(test.p)}.` : `Log-rank test across ${factor}: not computed (${test.reason}).`)),
        h(
          "div",
          { class: "downloads", style: { marginTop: "18px" } },
          ["games", "meetings", "actions"].map((name) => h("a", { class: "button small", href: file(`tables/${name}.csv`), download: "" }, `${name}.csv`)),
          h("a", { class: "button small", href: file("analysis/report.md"), download: "" }, "report.md"),
          h("a", { class: "button small", href: file("manifest.json"), download: "" }, "manifest.json"),
          r.figures && Object.keys(r.figures).length
            ? Object.entries(r.figures).map(([name, files]) => h("a", { class: "button small", href: file(`analysis/figures/${files[1]}`), download: "" }, `${name.slice(0, 2)} pdf`))
            : h("button", { class: "button small", type: "button", onClick: (e) => { e.target.textContent = "Drawing…"; e.target.disabled = true; load(true); } }, "Draw report figures"),
        ),
      ),
    );
  }

  function endings(cells) {
    const kinds = [["ejected", "voted out"], ["tasks", "tasks done"], ["outnumbered", "outnumbered"], ["timeout", "time ran out"]];
    return h(
      "div",
      { class: "table-scroll" },
      h(
        "table",
        { class: "data" },
        h(
          "thead",
          {},
          h("tr", {}, h("th", {}), h("th", { class: "num", colspan: 2, scope: "colgroup" }, "Crew wins: insider…"), h("th", { class: "num", colspan: 2, scope: "colgroup" }, "Insider wins: crew…")),
          h("tr", {}, h("th", { scope: "col" }, "Condition"), kinds.map(([, text]) => h("th", { class: "num", scope: "col" }, text))),
        ),
        h("tbody", {}, cells.map((cell) => h("tr", {}, h("td", {}, conditionLabel(cell.condition)), kinds.map(([kind]) => h("td", { class: "num" }, cell.reasons[kind] || 0))))),
      ),
    );
  }

  add(page, h("div", { class: "empty" }, "Analysing…"));
  await load();
  return () => {
    disposed = true;
    clearTimeout(timer);
  };
}
