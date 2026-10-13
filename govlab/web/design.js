// Design: choose the governance conditions, the game, the model and the sample, then launch.

import { api, app, conditionLabel, go, label, refreshRuns } from "./app.js";
import { add, fill, fmt, h, toast } from "./dom.js";

const NOTES = {
  plurality: "The most-voted player is ejected. A tie ejects no one.",
  majority: "A player needs more than half of the living players' votes.",
  supermajority: "A player needs at least two thirds of the living players' votes.",
  freeform: "Players say whatever they like in every round.",
  justification: "In the final round every statement must name an accused (or none) and one piece of evidence.",
  public: "Votes are cast in turn and everyone sees them as they fall.",
  secret: "Everyone votes at once; only the totals are announced.",
};

const GAME_FIELDS = [
  ["num_players", "Players"],
  ["num_impostors", "Insiders"],
  ["num_common_tasks", "Common tasks"],
  ["num_short_tasks", "Short tasks"],
  ["num_long_tasks", "Long tasks"],
  ["discussion_rounds", "Discussion rounds"],
  ["max_num_buttons", "Emergency meetings"],
  ["kill_cooldown", "Kill cooldown"],
  ["max_timesteps", "Time limit (steps)"],
];

const PRESET_NAMES = { study: "Study: 5 agents, 1 insider", five: "Upstream 5-player", seven: "Published: 7 agents, 2 insiders", three: "Tiny: 3 agents (smoke test)" };
const SAMPLE_PRESETS = [[5, "Pilot"], [15, "Floor"], [20, "Planned"], [30, "Target"]];
const PACES = [[0.6, "Slow"], [0.2, "Watchable"], [0.04, "Fast"], [0, "Instant"]];
const SERIES_VAR = { plurality: "--series-plurality", majority: "--series-majority", supermajority: "--series-supermajority" };

function loadSpec() {
  const fallback = structuredClone(app.meta.default_spec);
  if (!app.meta.credentials) Object.assign(fallback.llm, { provider: "mock", mock_latency: 0.2 });
  try {
    const saved = JSON.parse(localStorage.getItem("govlab.spec"));
    if (saved && Object.keys(fallback).every((key) => key in saved)) return saved;
  } catch {}
  return fallback;
}

export async function mountDesign(view) {
  const spec = loadSpec();
  let estimateTimer = null;
  let lastEstimate = null;

  const summary = h("div", { class: "card summary" });
  const form = h("div", {});
  add(view, 
    h(
      "div",
      { class: "page" },
      h(
        "div",
        { class: "page-head" },
        h("div", { class: "eyebrow" }, "II2202 · Governance experiment"),
        h("h1", {}, "Do voting rules reduce the damage from a malicious agent?"),
        h("p", {}, "Five agents share a task. One is an insider working against it. Choose the rules the team votes by, run the games, and compare how much damage the insider does and how often an innocent agent is thrown out."),
      ),
      h("div", { class: "design-grid" }, form, summary),
    ),
  );

  function changed(rerenderForm = false) {
    localStorage.setItem("govlab.spec", JSON.stringify(spec));
    if (rerenderForm) renderForm();
    renderSummary();
    clearTimeout(estimateTimer);
    estimateTimer = setTimeout(async () => {
      try {
        lastEstimate = { ok: true, ...(await api.post("/api/estimate", spec)) };
      } catch (error) {
        lastEstimate = { ok: false, error: error.message };
      }
      renderSummary();
    }, 150);
  }

  // --- controls ---------------------------------------------------------------

  function levelChips(key, options) {
    return h(
      "div",
      { class: "chips" },
      options.map((level) =>
        h(
          "button",
          {
            class: "chip",
            type: "button",
            "aria-pressed": String(spec[key].includes(level)),
            onClick: () => {
              const on = spec[key].includes(level);
              if (on && spec[key].length === 1) return toast("Keep at least one level of each factor.");
              spec[key] = options.filter((l) => (l === level ? !on : spec[key].includes(l)));
              changed(true);
            },
          },
          h("span", { class: "chip-title" }, label(level)),
          h("span", { class: "chip-note" }, NOTES[level]),
        ),
      ),
    );
  }

  function number(value, onChange, attrs = {}) {
    return h("input", {
      type: "number",
      value,
      ...attrs,
      onChange: (e) => {
        const parsed = attrs.step && String(attrs.step).includes(".") ? parseFloat(e.target.value) : parseInt(e.target.value, 10);
        onChange(Number.isFinite(parsed) ? parsed : null);
        changed();
      },
    });
  }

  function toggle(text, checked, onChange) {
    return h(
      "label",
      { class: "switch" },
      h("input", { type: "checkbox", checked, onChange: (e) => { onChange(e.target.checked); changed(); } }),
      h("span", { class: "switch-track" }),
      h("span", {}, text),
    );
  }

  function segmented(options, current, onPick) {
    return h(
      "div",
      { class: "segmented", role: "group" },
      options.map(([value, text]) =>
        h("button", { type: "button", "aria-pressed": String(value === current), onClick: () => { onPick(value); changed(true); } }, text),
      ),
    );
  }

  // --- the form ---------------------------------------------------------------

  function renderForm() {
    const o = app.meta.options;
    const mock = spec.llm.provider === "mock";
    const presetOf = Object.entries(app.meta.presets).find(([, preset]) => GAME_FIELDS.every(([k]) => preset[k] === spec.game[k]))?.[0] || "";

    fill(form, 
      h(
        "section",
        { class: "card" },
        h("div", { class: "card-head" }, h("h2", {}, "Governance")),
        h("p", { class: "card-sub" }, "The independent variables. Every combination of the levels you tick becomes one condition. The default is the 2×2 of the research plan."),
        h("div", { class: "field" }, h("span", { class: "field-label" }, "Vote threshold: how many votes remove an agent"), levelChips("thresholds", o.thresholds)),
        h("div", { class: "field" }, h("span", { class: "field-label" }, "Discussion protocol: what must precede the vote"), levelChips("protocols", o.protocols)),
        h("div", { class: "field" }, h("span", { class: "field-label" }, "Ballot: whether voters see each other's votes"), levelChips("ballots", o.ballots)),
        h(
          "div",
          { class: "field" },
          toggle("Tell the players which voting rule is in force", spec.disclose_rules, (v) => (spec.disclose_rules = v)),
          h("p", { class: "field-hint" }, "Off changes the tally without the voters knowing: the rule then acts only mechanically, not on how agents argue and vote."),
        ),
      ),

      h(
        "section",
        { class: "card" },
        h("div", { class: "card-head" }, h("h2", {}, "Team and game")),
        h("p", { class: "card-sub" }, "Held fixed across every condition. Tasks per player and the time limit are the knobs to turn if the pilot's baseline win rate falls outside 15–85%."),
        h(
          "div",
          { class: "field" },
          h(
            "select",
            { "aria-label": "Game preset", onChange: (e) => { if (e.target.value) { spec.game = { ...app.meta.presets[e.target.value] }; changed(true); } } },
            h("option", { value: "", selected: !presetOf }, "Custom"),
            Object.keys(app.meta.presets).map((name) => h("option", { value: name, selected: name === presetOf }, PRESET_NAMES[name] || name)),
          ),
        ),
        h("div", { class: "field row" }, GAME_FIELDS.map(([key, text]) => h("label", { class: "stack" }, h("span", {}, text), number(spec.game[key], (v) => { spec.game[key] = v; renderFormSoon(); }, { min: 0 })))),
      ),

      h(
        "section",
        { class: "card" },
        h("div", { class: "card-head" }, h("h2", {}, "Model"), segmented([["anthropic", "Claude"], ["mock", "Offline mock"]], spec.llm.provider, (v) => (spec.llm.provider = v))),
        mock
          ? h(
              "div",
              {},
              h("p", { class: "card-sub" }, "Scripted players that follow the same prompt and reply format as a model. Free and instant: use them to try the pipeline. Their results are not findings."),
              h("div", { class: "field" }, h("span", { class: "field-label" }, "Pace"), segmented(PACES, spec.llm.mock_latency, (v) => (spec.llm.mock_latency = v))),
            )
          : h(
              "div",
              {},
              h("p", { class: "card-sub" }, "One model for every agent in every condition. Haiku 5.5 takes no temperature setting; effort and thinking are the decoding settings held fixed."),
              app.meta.credentials
                ? null
                : h("div", { class: "notice" }, "No Claude API key found. Put ", h("code", {}, "ANTHROPIC_API_KEY=…"), " in a ", h("code", {}, ".env"), " file at the repository root and restart ", h("code", {}, "govlab serve"), ". Until then, the offline mock runs everything else."),
              h(
                "div",
                { class: "field row" },
                h("label", { class: "stack" }, h("span", {}, "Model"), h("input", { type: "text", value: spec.llm.model, style: { width: "190px" }, onChange: (e) => { spec.llm.model = e.target.value.trim(); changed(); } })),
                h("div", { class: "stack" }, h("span", {}, "Effort"), segmented(o.efforts.map((e) => [e, e[0].toUpperCase() + e.slice(1)]), spec.llm.effort, (v) => (spec.llm.effort = v))),
                h("div", { class: "stack" }, h("span", {}, "Thinking"), segmented([["disabled", "Off"], ["adaptive", "Adaptive"]], spec.llm.thinking, (v) => (spec.llm.thinking = v))),
                h("button", { class: "button", type: "button", disabled: !app.meta.credentials, onClick: testConnection }, "Test connection"),
              ),
              h("p", { class: "field-hint" }, "Thinking off keeps all of an agent's reasoning in its written scratchpad, which is logged in full."),
            ),
      ),

      h(
        "section",
        { class: "card" },
        h("div", { class: "card-head" }, h("h2", {}, "Sample")),
        h("p", { class: "card-sub" }, "Conditions are interleaved, so drift in the hosted model falls on all of them alike. A game that aborts or cannot be read is excluded and played again."),
        h(
          "div",
          { class: "field row" },
          h("label", { class: "stack" }, h("span", {}, "Name"), h("input", { type: "text", value: spec.name, style: { width: "200px" }, onChange: (e) => { spec.name = e.target.value; changed(); } })),
          h("label", { class: "stack" }, h("span", {}, "Games per condition"), number(spec.games_per_condition, (v) => (spec.games_per_condition = v), { min: 1, max: 500 })),
          h("div", { class: "stack" }, h("span", {}, " "), segmented(SAMPLE_PRESETS.map(([n, text]) => [n, `${text} ${n}`]), spec.games_per_condition, (v) => (spec.games_per_condition = v))),
        ),
        h(
          "div",
          { class: "field row" },
          h("label", { class: "stack" }, h("span", {}, "Games in parallel"), number(spec.concurrency, (v) => (spec.concurrency = v), { min: 1, max: 32 })),
          h("label", { class: "stack" }, h("span", {}, "Seed"), number(spec.seed, (v) => (spec.seed = v))),
          h("label", { class: "stack" }, h("span", {}, "Attempts per game"), number(spec.max_attempts, (v) => (spec.max_attempts = v), { min: 1, max: 10 })),
          h("label", { class: "stack" }, h("span", {}, "Budget cap (USD)"), number(spec.budget_usd ?? "", (v) => (spec.budget_usd = v > 0 ? v : null), { min: 0, step: "0.5", placeholder: "none" })),
        ),
        h(
          "div",
          { class: "field" },
          toggle("Give every condition the same starting positions", spec.matched_seeds, (v) => (spec.matched_seeds = v)),
          h("p", { class: "field-hint" }, "Replicate k uses the same seed in each condition, so roles, colours and tasks match across conditions and only the rules differ."),
        ),
      ),
    );
  }

  let formTimer = null;
  function renderFormSoon() {
    clearTimeout(formTimer);
    formTimer = setTimeout(renderForm, 0); // re-evaluates which preset matches
  }

  async function testConnection(event) {
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = "Testing…";
    try {
      const result = await api.post("/api/check", spec.llm);
      toast(result.ok ? `Connected: ${result.model} answered in ${result.latency_s.toFixed(1)} s.` : `Connection failed: ${result.error}`, 8000);
    } finally {
      button.disabled = false;
      button.textContent = "Test connection";
    }
  }

  // --- the summary ------------------------------------------------------------

  function matrix() {
    const rows = [];
    for (const ballot of spec.ballots) for (const protocol of spec.protocols) rows.push([protocol, ballot]);
    return h(
      "table",
      { class: "matrix" },
      h("thead", {}, h("tr", {}, h("td", { style: { background: "none" } }), spec.thresholds.map((t) => h("th", { scope: "col" }, h("span", { class: "swatch", style: { background: `var(${SERIES_VAR[t]})` } }), label(t))))),
      h(
        "tbody",
        {},
        rows.map(([protocol, ballot]) =>
          h(
            "tr",
            {},
            h("th", { scope: "row" }, label(protocol), spec.ballots.length > 1 ? h("div", { class: "faint", style: { fontWeight: 400 } }, label(ballot).replace(" ballot", "")) : null),
            spec.thresholds.map((threshold) => {
              const baseline = threshold === "plurality" && protocol === "freeform" && ballot === "public";
              return h("td", { class: baseline ? "baseline" : null, title: baseline ? "The upstream rules: the baseline condition" : null }, h("b", {}, spec.games_per_condition || 0), " games", baseline ? h("div", { class: "tiny faint" }, "baseline") : null);
            }),
          ),
        ),
      ),
    );
  }

  function promptPreview() {
    const t = app.meta.texts;
    const block = (title, text) => h("details", { class: "prompt" }, h("summary", {}, title), h("pre", {}, text));
    return h(
      "div",
      { style: { marginTop: "14px" } },
      h("div", { class: "field-label" }, "What each level adds to the players' instructions"),
      spec.disclose_rules
        ? [...spec.thresholds.map((l) => block(label(l), t.threshold[l])), ...(spec.ballots.length > 1 ? spec.ballots.map((l) => block(label(l), t.ballot[l])) : [])]
        : block("Voting rule (not disclosed)", t.undisclosed),
      spec.protocols.map((l) => block(`${label(l)} (final round only)`, t.protocol[l].trim())),
    );
  }

  function renderSummary() {
    const conditions = spec.thresholds.length * spec.protocols.length * spec.ballots.length;
    const games = conditions * (spec.games_per_condition || 0);
    const mock = spec.llm.provider === "mock";
    const e = lastEstimate;
    const blocked = !mock && !app.meta.credentials;
    const invalid = e && !e.ok;

    fill(summary, 
      h("div", { class: "eyebrow" }, "This experiment"),
      h("div", { class: "summary-figure num" }, games),
      h("p", { class: "muted", style: { marginBottom: "14px" } }, `games · ${conditions} condition${conditions === 1 ? "" : "s"} × ${spec.games_per_condition || 0}`),
      invalid ? h("div", { class: "notice error", style: { marginBottom: "12px" } }, e.error) : null,
      h("div", { class: "summary-line" }, h("span", {}, "Estimated cost"), h("span", { class: "num" }, mock ? "free" : e?.ok ? (e.cost_usd === null ? "unpriced model" : `about ${fmt.usd(e.cost_usd)}`) : "…")),
      h("div", { class: "summary-line" }, h("span", {}, "Estimated time"), h("span", { class: "num" }, e?.ok ? fmt.minutes(e.minutes) : "…")),
      h("div", { class: "summary-line" }, h("span", {}, "Model"), h("span", {}, mock ? "Offline mock" : spec.llm.model)),
      e?.ok && e.detectable_difference && conditions > 1
        ? h("div", { class: "summary-line" }, h("span", {}, "Detectable difference"), h("span", { class: "num", title: "Smallest difference in a rate between two levels of one factor that is detected with 80% power at α = 0.05, from a baseline of 50%." }, `≈ ${Math.round(e.detectable_difference * 100)} points`))
        : null,
      matrix(),
      mock ? h("div", { class: "notice info" }, "Offline mock: scripted players, not a model. Good for trying the tool; the results mean nothing.") : null,
      blocked ? h("div", { class: "notice" }, "Waiting for an API key. Everything else is ready.") : null,
      h(
        "div",
        { class: "actions" },
        h("button", { class: "button primary", type: "button", disabled: blocked || invalid || !games, onClick: () => launch(spec) }, `Start ${games} games`),
        h("button", { class: "button", type: "button", disabled: blocked || invalid, onClick: () => launch({ ...spec, name: "quick look", games_per_condition: 1, budget_usd: null }) }, "Quick look: one game per condition"),
      ),
      promptPreview(),
    );
  }

  async function launch(what) {
    try {
      const run = await api.post("/api/runs", what);
      await refreshRuns();
      go("watch", run.run_id);
    } catch (error) {
      toast(error.message, 9000);
    }
  }

  renderForm();
  changed();
  return () => clearTimeout(estimateTimer);
}

export { conditionLabel };
