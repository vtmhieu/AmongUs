// The Skeld, drawn from the engine's own room polygons, with a token per player.

import { add, h, s, tipOn } from "./dom.js";

// Among Us crew colours, slightly softened to sit on paper.
export const PLAYER_COLOURS = {
  red: "#C8322B", blue: "#2D4FD6", green: "#1F8A45", pink: "#E86BB8", orange: "#EE8324", yellow: "#EAD34A",
  black: "#454B52", white: "#DDE3EE", purple: "#7A45C4", brown: "#7B5230", cyan: "#3BD6C4", lime: "#63D94A",
};
const DARK_INK = new Set(["yellow", "white", "cyan", "lime", "pink", "orange"]);

export function inkFor(colour) {
  return DARK_INK.has(colour) ? "#141413" : "#FFFFFF";
}

/** A small coloured disc with the player's number, used wherever a player is named. */
export function playerDot(player, extraClass = "") {
  return h("span", { class: `dot ${extraClass}`, style: { background: PLAYER_COLOURS[player.color], color: inkFor(player.color) } }, player.number);
}

function centroid(coords) {
  let x = 0;
  let y = 0;
  for (let i = 0; i < coords.length; i += 2) {
    x += coords[i];
    y += coords[i + 1];
  }
  const n = coords.length / 2;
  return [x / n, y / n];
}

export function createMap(mapData) {
  const centres = {};
  const tops = {};
  for (const [name, coords] of Object.entries(mapData.rooms)) {
    centres[name] = centroid(coords);
    tops[name] = Math.min(...coords.filter((_, i) => i % 2 === 1));
  }
  const corridors = s("g", {});
  for (const [a, b] of mapData.corridors) {
    add(corridors, s("line", { class: "corridor", x1: centres[a][0], y1: centres[a][1], x2: centres[b][0], y2: centres[b][1] }));
  }
  const rooms = s("g", {});
  const roomEls = {};
  for (const [name, coords] of Object.entries(mapData.rooms)) {
    const points = [];
    for (let i = 0; i < coords.length; i += 2) points.push(`${coords[i]},${coords[i + 1]}`);
    roomEls[name] = s("polygon", { class: "room", points: points.join(" ") });
    add(rooms, roomEls[name], s("text", { class: "room-label", x: centres[name][0], y: tops[name] - 7 }, name));
  }
  const tokens = s("g", {});
  const svg = s("svg", { class: "map", viewBox: "-8 -22 994 574", role: "img", "aria-label": "Map of the ship with each player's position" }, corridors, rooms, tokens);
  const tokenEls = {};

  function ensureToken(player) {
    if (tokenEls[player.name]) return tokenEls[player.name];
    const g = s(
      "g",
      { class: "token", tabindex: "0" },
      s("circle", { class: "ring", r: 14 }),
      s("circle", { class: "halo", r: 18.5, visibility: "hidden" }),
      s("circle", { class: "body", r: 13.5, fill: PLAYER_COLOURS[player.color] }),
      s("text", { fill: inkFor(player.color) }, player.number),
      s("path", { class: "cross", d: "M-7 -7L7 7M7 -7L-7 7", visibility: "hidden" }),
    );
    add(tokens, g);
    tokenEls[player.name] = g;
    return g;
  }

  /**
   * players: [{name, number, color, identity}], state: the snapshot of an event,
   * opts: {showRoles, acting: name, meeting: bool, crime: room, hidden: Set of names}
   */
  function update(players, state, opts = {}) {
    const byRoom = {};
    for (const player of players) {
      const where = state.players[player.name];
      const gone = !where || opts.hidden?.has(player.name);
      if (tokenEls[player.name]) tokenEls[player.name].style.display = gone ? "none" : "";
      if (gone) continue;
      (byRoom[where.location] ||= []).push(player);
    }
    for (const [name, el] of Object.entries(roomEls)) {
      const here = byRoom[name] || [];
      el.setAttribute("class", `room${here.some((p) => state.players[p.name].alive) ? " occupied" : ""}${opts.meeting && name === "Cafeteria" ? " meeting" : ""}${opts.crime === name ? " crime" : ""}`);
    }
    for (const [room, here] of Object.entries(byRoom)) {
      const perRow = here.length > 4 ? 3 : here.length > 2 ? 2 : here.length;
      const rowCount = Math.ceil(here.length / perRow);
      here.forEach((player, i) => {
        const row = Math.floor(i / perRow);
        const inRow = Math.min(perRow, here.length - row * perRow);
        const x = centres[room][0] + (i % perRow - (inRow - 1) / 2) * 31;
        const y = centres[room][1] + (row - (rowCount - 1) / 2) * 31 + 4;
        const where = state.players[player.name];
        const g = ensureToken(player);
        const insider = opts.showRoles && player.identity === "Impostor";
        g.setAttribute("class", `token${where.alive ? "" : " dead"}${opts.acting === player.name ? " acting" : ""}`);
        g.style.transform = `translate(${x}px, ${y}px)`;
        g.querySelector(".halo").setAttribute("visibility", insider ? "visible" : "hidden");
        g.querySelector(".cross").setAttribute("visibility", where.alive ? "hidden" : "visible");
        g._tip = `${player.name}${opts.showRoles ? ` · ${player.identity === "Impostor" ? "insider" : "crew"}` : ""} · ${where.alive ? room : "out of the game"}`;
        if (!g._tipped) {
          tipOn(g, () => g._tip);
          g._tipped = true;
        }
      });
    }
  }

  return { el: svg, update };
}
