// Watch: the run's progress, one game on the map, and its transcript, live or replayed.

import { api, conditionLabel, label, refreshRuns, setHashQuietly, statusPill } from "./app.js";
import { add, clear, fill, fmt, h, tipOn, toast } from "./dom.js";
import { createMap, playerDot } from "./map.js";
import { app } from "./app.js";

const SPEEDS = [[900, "Slow"], [350, "Normal"], [90, "Fast"]];

export async function mountWatch(view, runId, initialGame) {
  let detail = await api.get(`/api/runs/${runId}`);
  let run = detail.run;
  const spec = detail.spec;
  const games = new Map(detail.games.map((g) => [g.game_id, g]));
  const conditions = run.conditions;

  // what is on screen
  let gameId = null;
  let events = [];
  let seen = new Set();
  let players = [];
  let cursor = 0;
  let live = true;
  let follow = run.active;
  let playing = null;
  let speed = 350;
  let showRoles = localStorage.getItem("govlab.roles") !== "0";
  let showThoughts = localStorage.getItem("govlab.thoughts") === "1";
  let source = null;
  let frame = null;
  let disposed = false;

  const map = createMap(app.meta.map);
  const el = {
    runHead: h("div", { class: "panel-head" }),
    rail: h("div", { class: "panel-body" }),
    stageHead: h("div", { class: "stage-head" }),
    banner: h("div", { class: "banner", hidden: true }),
    roster: h("div", { class: "roster" }),
    transport: h("div", { class: "transport" }),
    feedHead: h("div", { class: "panel-head" }),
    feed: h("div", { class: "panel-body" }),
  };
  add(view, 
    h(
      "div",
      { class: "watch" },
      h("aside", { class: "panel" }, el.runHead, el.rail, legend()),
      h("section", { class: "stage" }, el.stageHead, h("div", { class: "map-wrap" }, map.el, el.banner), el.roster, el.transport),
      h("aside", { class: "panel" }, el.feedHead, el.feed),
    ),
  );

  function legend() {
    const item = (cls, glyph, text) => h("span", {}, h("i", { class: `tile ${cls}` }, glyph), text);
    return h("div", { class: "legend" }, item("crew", "C", "Crew won"), item("impostor", "I", "Insider won"), item("running", "•", "Playing"), item("invalid", "!", "Excluded"));
  }

  // --- the run rail -----------------------------------------------------------

  function latestBySlot() {
    const bySlot = new Map();
    for (const g of games.values()) {
      const current = bySlot.get(g.slot);
      if (!current || g.attempt > current.attempt) bySlot.set(g.slot, g);
    }
    return bySlot;
  }

  // The header's buttons are built once and only shown or hidden: a button that is
  // rebuilt on every status message can swallow a click that lands mid-update.
  const head = {
    title: h("h2", { style: { fontSize: "17px", overflowWrap: "anywhere" } }),
    pill: h("span", {}),
    bar: h("i", {}),
    facts: h("div", { class: "run-facts num" }),
    notes: h("div", {}),
    stop: h("button", { class: "button small", type: "button", onClick: stopRun }, "Stop"),
    resume: h("button", { class: "button small", type: "button", onClick: resumeRun }, "Resume"),
  };
  add(
    el.runHead,
    h("div", { style: { display: "flex", justifyContent: "space-between", gap: "8px", alignItems: "flex-start" } }, head.title, head.pill),
    h("div", { class: "progress" }, head.bar),
    head.facts,
    head.notes,
    h("div", { style: { display: "flex", gap: "8px", marginTop: "12px", flexWrap: "wrap" } }, head.stop, head.resume, h("a", { class: "button small", href: `#/results/${runId}` }, "Results")),
  );

  function renderRun() {
    const running = [...games.values()].filter((g) => g.status === "running").length;
    const state = run.status.state;
    head.title.textContent = run.name;
    fill(head.pill, statusPill(state));
    head.bar.style.width = `${(100 * run.valid) / Math.max(run.total, 1)}%`;
    fill(
      head.facts,
      h("span", {}, `${run.valid} of ${run.total} games`),
      running ? h("span", {}, `${running} playing`) : null,
      run.attempts > run.valid ? h("span", {}, `${run.attempts - run.valid} excluded`) : null, // attempts counts finished games only
      h("span", {}, run.provider === "mock" ? "offline mock" : fmt.usd(run.cost_usd)),
    );
    fill(
      head.notes,
      run.status.error ? h("div", { class: `notice ${state === "failed" ? "error" : ""}`, style: { marginTop: "10px" } }, run.status.error) : null,
      state === "interrupted" ? h("div", { class: "notice", style: { marginTop: "10px" } }, "The server stopped while this run was in progress. Resume plays the games that are left.") : null,
    );
    head.stop.hidden = !run.active;
    head.resume.hidden = run.active || run.valid + run.failed >= run.total;
  }

  function renderRail() {
    const bySlot = latestBySlot();
    const slotsOf = {};
    for (const c of conditions) slotsOf[c] = [];
    // slots are interleaved; rebuild each condition's column from the games known so far
    for (const g of [...bySlot.values()].sort((a, b) => a.slot - b.slot)) slotsOf[g.condition]?.push(g);
    clear(el.rail);
    for (const condition of conditions) {
      const known = slotsOf[condition];
      const wins = known.filter((g) => g.status === "valid" && g.winner === "crew").length;
      const done = known.filter((g) => g.status === "valid").length;
      const tiles = known.map((g) => {
        const cls = g.status === "running" ? "running" : g.status === "invalid" ? "invalid" : g.winner;
        const glyph = g.status === "running" ? "•" : g.status === "invalid" ? "!" : g.winner === "crew" ? "C" : "I";
        const tile = h("button", { class: `tile ${cls}`, type: "button", "aria-pressed": String(g.game_id === gameId), "aria-label": `Game ${g.game_id}`, onClick: () => select(g.game_id, false) }, glyph);
        return tipOn(tile, () => tileTip(g));
      });
      for (let i = known.length; i < run.games_per_condition; i++) tiles.push(h("i", { class: "tile pending" }));
      add(el.rail, 
        h("div", { class: "condition-group" }, h("div", { class: "condition-name" }, h("span", {}, conditionLabel(condition)), h("span", { class: "num faint" }, done ? `${wins}/${done} crew` : "")), h("div", { class: "tiles" }, tiles)),
      );
    }
  }

  function tileTip(g) {
    if (g.status === "running") return [h("b", {}, g.game_id), " · playing now"];
    if (g.status === "invalid") return [h("b", {}, g.game_id), ` · excluded (${(g.invalid_reason || "").replaceAll("_", " ")})`, g.error ? h("div", {}, g.error) : null];
    return [h("b", {}, g.game_id), ` · ${g.winner === "crew" ? "crew won" : "insider won"} (${g.reason})`, h("div", {}, `${g.kills} kill${g.kills === 1 ? "" : "s"} · ${g.meetings} meeting${g.meetings === 1 ? "" : "s"} · ${g.wrongful_ejections} wrongful removal${g.wrongful_ejections === 1 ? "" : "s"}`)];
  }

  async function stopRun() {
    run = await api.post(`/api/runs/${runId}/stop`);
    renderRun();
  }

  async function resumeRun() {
    try {
      run = await api.post(`/api/runs/${runId}/resume`);
      follow = true;
      renderRun();
      refreshRuns();
    } catch (error) {
      toast(error.message, 8000);
    }
  }

  // --- choosing and loading a game ---------------------------------------------

  function connect() {
    if (source) source.close();
    source = new EventSource(`/api/runs/${runId}/stream${gameId ? `?game=${encodeURIComponent(gameId)}` : ""}`);
    source.onmessage = (message) => {
      const data = JSON.parse(message.data);
      if (data.kind === "run") {
        const wasActive = run.active;
        run = { ...run, ...data.run, active: !["completed", "stopped", "failed", "budget"].includes(data.run.status.state) };
        renderRun();
        if (wasActive && !run.active) refreshRuns();
      } else if (data.kind === "game") {
        games.set(data.game.game_id, { ...games.get(data.game.game_id), ...data.game });
        if (data.game.status === "cancelled") games.delete(data.game.game_id);
        renderRail();
        renderRun();
        const current = games.get(gameId);
        if (data.game.status === "running" && follow && (!current || current.status !== "running")) select(data.game.game_id, true);
      } else if (data.kind === "event" && data.game_id === gameId) {
        addEvents([data.event]);
      }
    };
  }

  function addEvents(incoming) {
    let added = false;
    for (const event of incoming) {
      if (seen.has(event.seq)) continue;
      seen.add(event.seq);
      events.push(event);
      added = true;
    }
    if (!added) return;
    events.sort((a, b) => a.seq - b.seq);
    if (!players.length && events[0]?.type === "game_start") {
      players = events[0].players.map((p) => ({ ...p, number: p.name.match(/\d+/)[0] }));
    }
    if (live) cursor = events.length;
    schedule();
  }

  async function select(id, keepFollowing) {
    if (id === gameId) return;
    stopPlaying();
    gameId = id;
    events = [];
    seen = new Set();
    players = [];
    cursor = 0;
    if (!keepFollowing) follow = false;
    const running = games.get(id)?.status === "running";
    live = true;
    setHashQuietly("watch", runId, id);
    connect(); // first, so nothing emitted while the history loads is missed
    renderRail();
    const history = await api.get(`/api/runs/${runId}/games/${id}/events`);
    if (gameId !== id) return;
    addEvents(history);
    if (!running) live = false;
    cursor = events.length;
    schedule();
  }

  // --- rendering one game -------------------------------------------------------

  function schedule() {
    if (frame || disposed) return;
    const draw = () => {
      frame = null;
      renderGame();
    };
    // browsers pause animation frames in a background tab; a timer keeps the view current there
    frame = document.hidden ? setTimeout(draw, 250) : requestAnimationFrame(draw);
  }

  function byName(name) {
    return players.find((p) => p.name === name);
  }

  function short(name) {
    return name ? name.replace(/^Player /, "P") : "";
  }

  function renderGame() {
    const game = games.get(gameId);
    const shown = events.slice(0, cursor);
    const start = events[0]?.type === "game_start" ? events[0] : null;

    fill(el.stageHead, 
      h("div", { class: "stage-title" }, game ? conditionLabel(game.condition) : "Waiting for the first game"),
      game ? h("span", { class: "pill plain mono" }, game.game_id) : null,
      game ? h("span", { class: "pill plain" }, `seed ${game.seed}`) : null,
      h(
        "div",
        { class: "stage-toggles" },
        run.active ? switchEl("Follow the run", follow, (v) => { follow = v; }) : null,
        switchEl("Roles", showRoles, (v) => { showRoles = v; localStorage.setItem("govlab.roles", v ? "1" : "0"); schedule(); }),
        switchEl("Thoughts", showThoughts, (v) => { showThoughts = v; localStorage.setItem("govlab.thoughts", v ? "1" : "0"); schedule(); }),
      ),
    );
    if (!start) {
      el.banner.hidden = true;
      clear(el.roster);
      clear(el.transport);
      fill(el.feedHead, h("h3", {}, "Transcript"));
      fill(el.feed, h("div", { class: "empty small" }, run.active ? "The first game is about to start." : game ? "Loading…" : "Pick a game on the left."));
      return;
    }

    // the state of the world at the cursor
    let state = start.state;
    let acting = null;
    let meeting = false;
    let crime = null;
    let bannerText = "Game start";
    let lastMeetingSeq = -1;
    const removedAt = {};
    for (const e of shown) {
      if (e.state) state = e.state;
      acting = null;
      crime = null;
      if (e.type === "meeting_start") { meeting = true; lastMeetingSeq = e.seq; bannerText = `Meeting ${e.meeting}`; }
      else if (e.type === "tally") { meeting = false; if (e.ejected) removedAt[e.ejected] = -1; bannerText = e.ejected ? `${short(e.ejected)} ejected` : "No one ejected"; }
      else if (e.type === "step" && e.phase === "task") bannerText = `Timestep ${e.timestep + 1} of ${start.game_config.max_timesteps}`;
      else if (e.type === "turn") {
        acting = e.player;
        if (e.action === "KILL") { crime = state.players[e.player].location; removedAt[e.target] = e.seq; bannerText = `${short(e.player)} killed ${short(e.target)}`; }
        else if (e.phase === "meeting") bannerText = e.action === "VOTE" ? `Meeting ${e.meeting} · voting` : `Meeting ${e.meeting} · round ${e.round + 1} of ${start.game_config.discussion_rounds}`;
      } else if (e.type === "game_end") bannerText = e.winner === "crew" ? "The crew wins" : "The insider wins";
    }
    // a body stays where it fell until a meeting is called; the ejected leave at once
    const hidden = new Set(Object.entries(removedAt).filter(([, seq]) => seq < lastMeetingSeq || seq === -1).map(([name]) => name));
    map.update(players, state, { showRoles, acting, meeting, crime, hidden });
    el.banner.hidden = false;
    el.banner.textContent = bannerText;

    fill(el.roster, 
      players.map((p) => {
        const s = state.players[p.name];
        const insider = showRoles && p.identity === "Impostor";
        const fate = s.alive ? s.location : removedAt[p.name] === -1 ? "ejected" : "killed";
        const tasks = p.identity === "Impostor" ? (showRoles ? "insider" : `${s.tasks_done}/${p.tasks.length} tasks`) : `${s.tasks_done}/${p.tasks.length} tasks`;
        return h("div", { class: `player${s.alive ? "" : " dead"}${insider ? " insider" : ""}` }, playerDot(p), h("div", { style: { minWidth: 0 } }, h("div", { class: "player-name" }, p.name), h("div", { class: "player-meta" }, `${fate} · ${tasks}`)));
      }),
    );

    renderTransport(game);
    renderFeed(shown, start, state);
  }

  function switchEl(text, checked, onChange) {
    return h("label", { class: "switch small" }, h("input", { type: "checkbox", checked, onChange: (e) => onChange(e.target.checked) }), h("span", { class: "switch-track" }), h("span", {}, text));
  }

  // --- playback -----------------------------------------------------------------

  function stopPlaying() {
    clearInterval(playing);
    playing = null;
  }

  function play() {
    if (cursor >= events.length) cursor = 1;
    live = false;
    stopPlaying();
    playing = setInterval(() => {
      if (cursor >= events.length) { stopPlaying(); if (games.get(gameId)?.status === "running") live = true; }
      else cursor += 1;
      schedule();
    }, speed);
    schedule();
  }

  function renderTransport(game) {
    const running = game?.status === "running";
    fill(el.transport, 
      h("button", { class: "icon-button", type: "button", "aria-label": playing ? "Pause" : "Play", onClick: () => { if (playing) { stopPlaying(); schedule(); } else play(); } }, playing ? "❚❚" : "▶"),
      h("input", {
        type: "range", min: 1, max: Math.max(events.length, 1), value: cursor, "aria-label": "Position in the game",
        onInput: (e) => { stopPlaying(); cursor = Number(e.target.value); live = running && cursor >= events.length; schedule(); },
      }),
      h("span", { class: "tiny num faint", style: { minWidth: "64px", textAlign: "right" } }, `${cursor} / ${events.length}`),
      h("select", { "aria-label": "Replay speed", onChange: (e) => { speed = Number(e.target.value); if (playing) play(); } }, SPEEDS.map(([ms, text]) => h("option", { value: ms, selected: ms === speed }, text))),
      running ? h("button", { class: `button small ${live ? "primary" : ""}`, type: "button", onClick: () => { stopPlaying(); live = true; cursor = events.length; schedule(); } }, live ? "● Live" : "Go live") : null,
    );
  }

  // --- the transcript -----------------------------------------------------------

  function who(name) {
    const p = byName(name);
    return p ? playerDot(p) : null;
  }

  function describe(e) {
    switch (e.action) {
      case "MOVE": return `moved to ${e.to}`;
      case "VENT": return `vented to ${e.to}`;
      case "COMPLETE TASK": return `worked on ${e.task}`;
      case "COMPLETE FAKE TASK": return `pretended to do ${e.task}`;
      case "VIEW MONITOR": return "watched the security cameras";
      case "CALL MEETING": return e.kind === "report" ? "reported a body" : "pressed the emergency button";
      case "WAIT": return "stood still (the reply could not be read)";
      default: return e.text;
    }
  }

  function renderFeed(shown, start, state) {
    const insiders = players.filter((p) => p.identity === "Impostor").map((p) => p.name);
    const nearBottom = el.feed.scrollHeight - el.feed.scrollTop - el.feed.clientHeight < 80;
    fill(el.feedHead, 
      h("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: "10px" } }, h("h3", {}, "Transcript"), h("span", { class: "tiny faint num" }, `${state.tasks.done}/${state.tasks.total} crew tasks done`)),
    );
    const feed = h("div", { class: "feed" });
    let box = null; // the open meeting's body
    let round = null;
    let votes = [];

    for (const e of shown) {
      if (e.type === "game_start") {
        add(feed, h("div", { class: "line note" }, showRoles ? `The insider is ${insiders.join(", ")}.` : "Roles are hidden."));
      } else if (e.type === "step" && e.phase === "task") {
        add(feed, h("div", { class: "feed-step" }, `Timestep ${e.timestep + 1}`));
      } else if (e.type === "meeting_start") {
        round = null;
        votes = [];
        box = h("div", { class: "meeting-body" });
        const cause = e.kind === "report" ? `${short(e.caller)} reported ${e.bodies.map(short).join(", ") || "a body"} dead in ${e.location}` : `${short(e.caller)} pressed the emergency button`;
        add(feed, h("div", { class: "meeting" }, h("div", { class: "meeting-head" }, h("span", {}, `Meeting ${e.meeting}`), h("span", { class: "faint", style: { fontWeight: 500 } }, cause)), box));
      } else if (e.type === "turn" && e.phase === "meeting" && box) {
        if (e.action === "SPEAK") {
          if (e.round !== round) {
            round = e.round;
            add(box, h("div", { class: "round" }, `Round ${e.round + 1}${e.final_round ? " · final" : ""}`));
          }
          const insider = showRoles && e.identity === "Impostor";
          const claim = e.justification
            ? h("div", { class: "claim" }, h("span", { class: `tag ${e.justification.accused ? (insiders.includes(e.justification.accused) && showRoles ? "good" : "accent") : ""}` }, e.justification.accused ? `accuses ${short(e.justification.accused)}` : "accuses no one"))
            : e.final_round && start.governance.protocol === "justification"
              ? h("div", { class: "claim" }, h("span", { class: "tag bad" }, "no valid justification"))
              : null;
          add(box, h("div", { class: "say" }, who(e.player), h("div", { class: `bubble${insider ? " insider" : ""}` }, h("b", {}, short(e.player), insider ? " · insider" : "", e.fallback ? " · unreadable reply" : ""), e.message, claim)));
        } else if (e.action === "VOTE") {
          votes.push(e);
          if (start.governance.ballot === "public") add(box, h("div", { class: "line small" }, who(e.player), h("span", {}, e.target === "SKIP" ? "skips" : ["votes ", h("b", {}, short(e.target))], e.fallback ? " (unreadable reply: counted as a skip)" : "")));
        }
        if (showThoughts && e.thought) add(box, h("div", { class: "thought" }, e.thought));
      } else if (e.type === "tally" && box) {
        add(box, tallyEl(e, insiders));
        box = null;
      } else if (e.type === "turn" && e.action === "CALL MEETING") {
        // logged just after its meeting_start; the meeting's header already says who called it
        if (showThoughts && e.thought && box) add(box, h("div", { class: "thought" }, e.thought));
      } else if (e.type === "turn") {
        const line = h("div", { class: `line${e.action === "KILL" ? " kill" : ""}${e.action === "WAIT" ? " note" : ""}` }, who(e.player));
        if (e.action === "KILL") add(line, h("span", {}, `${short(e.player)} killed ${short(e.target)} in ${e.state.players[e.player].location}`, e.witnesses.length ? ` · seen by ${e.witnesses.map(short).join(", ")}` : " · no witnesses"));
        else add(line, h("span", {}, h("b", { style: { fontWeight: 600 } }, short(e.player)), " ", describe(e)));
        add(feed, line);
        if (showThoughts && e.thought) add(feed, h("div", { class: "thought" }, e.thought));
      } else if (e.type === "game_end") {
        const reasons = { ejected: "the insider was voted out", tasks: "every task was completed", outnumbered: "the crew no longer outnumbers the insider", timeout: "time ran out" };
        add(feed, h("div", { class: `outcome ${e.winner}` }, `${e.winner === "crew" ? "The crew wins" : "The insider wins"}: ${reasons[e.reason]}.`, h("div", { class: "small", style: { fontWeight: 500, marginTop: "3px" } }, `${e.kills} kill${e.kills === 1 ? "" : "s"} · ${e.wrongful_ejections} wrongful removal${e.wrongful_ejections === 1 ? "" : "s"} · ${e.meetings} meeting${e.meetings === 1 ? "" : "s"} · ${e.timesteps} timesteps`)));
      }
    }
    fill(el.feed, feed);
    if (live || playing || nearBottom) el.feed.scrollTop = el.feed.scrollHeight;
  }

  function tallyEl(e, insiders) {
    const rows = Object.entries(e.counts).sort((a, b) => b[1] - a[1]);
    const el = h("div", { class: "tally" }, h("div", { class: "tiny faint", style: { fontWeight: 600, marginBottom: "4px" } }, `${label(e.rule)} · ${e.n_voters} voters${e.required ? ` · ${e.required} needed` : ""}`));
    for (const [option, n] of rows) {
      const p = byName(option);
      add(el, 
        h(
          "div",
          { class: "tally-row" },
          h("span", { style: { display: "flex", alignItems: "center", gap: "6px", minWidth: 0 } }, p ? playerDot(p) : null, h("span", {}, option === "SKIP" ? "Skip" : short(option))),
          h("div", { class: "tally-track" }, h("div", { class: `tally-fill${option === e.ejected ? " out" : ""}`, style: { width: `${(100 * n) / e.n_voters}%` } }), e.required ? h("div", { class: "tally-need", style: { left: `calc(${(100 * e.required) / e.n_voters}% - 1px)` } }) : null),
          h("span", { class: "num", style: { textAlign: "right", fontWeight: 600 } }, n),
        ),
      );
    }
    const verdict = e.ejected
      ? [`${short(e.ejected)} is ejected`, showRoles ? h("span", { class: `tag ${e.wrongful ? "bad" : "good"}`, style: { marginLeft: "8px" } }, e.wrongful ? "a crewmate: wrongful" : "the insider: correct") : null]
      : ["No one is ejected"];
    add(el, h("div", { class: "verdict" }, verdict));
    if (e.rule_changed_outcome) {
      const others = Object.entries(e.counterfactual).filter(([rule, out]) => rule !== e.rule && out !== e.ejected).map(([rule, out]) => `${label(rule).toLowerCase()} would ${out ? `eject ${short(out)}` : "eject no one"}`);
      add(el, h("div", { class: "tiny faint", style: { marginTop: "5px" } }, `On these ballots, ${others.join("; ")}.`));
    }
    return el;
  }

  // --- start ---------------------------------------------------------------------

  renderRun();
  renderRail();
  renderGame();
  const all = [...games.values()];
  const first = (initialGame && games.has(initialGame) && initialGame) || all.find((g) => g.status === "running")?.game_id || all.filter((g) => g.status === "valid").at(-1)?.game_id || all.at(-1)?.game_id;
  if (first) await select(first, true);
  else connect();

  return () => {
    disposed = true;
    stopPlaying();
    if (source) source.close();
    cancelAnimationFrame(frame);
    clearTimeout(frame);
  };
}
