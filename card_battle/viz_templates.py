"""v0.7: HTML/JS/CSS templates for static visualization site."""

# ---------------------------------------------------------------------------
# style.css
# ---------------------------------------------------------------------------

STYLE_CSS = """\
:root {
  --bg: #f8f9fa;
  --card-bg: #fff;
  --border: #dee2e6;
  --text: #212529;
  --text-muted: #6c757d;
  --accent: #0d6efd;
  --green: #198754;
  --red: #dc3545;
  --yellow: #ffc107;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.5;
  padding: 1.5rem;
  max-width: 1200px;
  margin: 0 auto;
}

h1 { font-size: 1.5rem; margin-bottom: 1rem; }
h2 { font-size: 1.2rem; margin-bottom: 0.75rem; }

a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

/* --- Cycle Dashboard --- */

.summary-bar {
  display: flex; gap: 1.5rem; margin-bottom: 1.5rem;
  padding: 1rem; background: var(--card-bg); border: 1px solid var(--border);
  border-radius: 8px;
}
.summary-stat { text-align: center; }
.summary-stat .val { font-size: 1.5rem; font-weight: 700; font-variant-numeric: tabular-nums; }
.summary-stat .lbl { font-size: 0.75rem; text-transform: uppercase; color: var(--text-muted); letter-spacing: 0.05em; }

.cycle-grid { display: flex; flex-direction: column; gap: 1rem; }

.cycle-card {
  background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px;
  padding: 1rem 1.25rem; cursor: pointer; transition: box-shadow 0.15s;
}
.cycle-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.08); }

.cycle-header {
  display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.5rem;
}
.cycle-id { font-weight: 600; font-size: 1rem; }
.badge {
  font-size: 0.7rem; font-weight: 600; padding: 0.15rem 0.5rem;
  border-radius: 999px; text-transform: uppercase; letter-spacing: 0.03em;
}
.badge-pass { background: #d1e7dd; color: #0f5132; }
.badge-fail { background: #f8d7da; color: #842029; }

.cycle-subtitle { font-size: 0.85rem; color: var(--text-muted); margin-bottom: 0.75rem; }

.delta-grid {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.5rem; margin-bottom: 0.75rem;
}
.delta-item {
  text-align: center; padding: 0.4rem; background: var(--bg); border-radius: 6px;
  font-variant-numeric: tabular-nums;
}
.delta-item .dlabel { font-size: 0.65rem; text-transform: uppercase; color: var(--text-muted); }
.delta-item .dval { font-size: 0.95rem; font-weight: 600; }
.dval.positive { color: var(--green); }
.dval.negative { color: var(--red); }
.dval.neutral { color: var(--text-muted); }

.cycle-detail { display: none; margin-top: 0.75rem; padding-top: 0.75rem; border-top: 1px solid var(--border); }
.cycle-card.expanded .cycle-detail { display: block; }

.promoted-list { list-style: none; padding: 0; }
.promoted-list li {
  font-size: 0.85rem; padding: 0.25rem 0;
  font-family: "SFMono-Regular", Consolas, monospace;
}

.gate-checks { margin-top: 0.5rem; }
.gate-check { font-size: 0.8rem; margin-bottom: 0.2rem; }
.gate-check .chk-pass { color: var(--green); }
.gate-check .chk-fail { color: var(--red); }

.replay-links { margin-top: 0.5rem; }
.replay-links a {
  display: inline-block; font-size: 0.8rem; margin-right: 0.75rem;
  padding: 0.2rem 0.5rem; background: var(--bg); border-radius: 4px;
}

/* --- Replay Player --- */

.player-controls {
  display: flex; align-items: center; gap: 1rem;
  padding: 0.75rem 1rem; background: var(--card-bg); border: 1px solid var(--border);
  border-radius: 8px; margin-bottom: 1rem;
}
.player-controls button {
  background: var(--accent); color: #fff; border: none; border-radius: 4px;
  padding: 0.3rem 0.75rem; cursor: pointer; font-size: 0.9rem;
}
.player-controls button:hover { opacity: 0.85; }
.player-controls input[type=range] { flex: 1; }
.turn-label { font-weight: 600; font-variant-numeric: tabular-nums; min-width: 8ch; }
.compact-toggle { margin-left: auto; }
.compact-toggle label { font-size: 0.85rem; cursor: pointer; }

.board-layout {
  display: grid; grid-template-columns: 200px 1fr 200px; gap: 1rem; margin-bottom: 1rem;
}

.player-panel {
  background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px;
  padding: 1rem;
}
.player-panel h3 { font-size: 0.9rem; margin-bottom: 0.5rem; }
.player-panel .stat { font-size: 0.85rem; margin-bottom: 0.25rem; font-variant-numeric: tabular-nums; }

.hp-bar-container {
  height: 8px; background: #e9ecef; border-radius: 4px; overflow: hidden; margin: 0.3rem 0;
}
.hp-bar {
  height: 100%; border-radius: 4px; transition: width 0.3s;
}
.hp-bar.healthy { background: var(--green); }
.hp-bar.warning { background: var(--yellow); }
.hp-bar.danger { background: var(--red); }

.board-panel {
  background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px;
  padding: 1rem; min-height: 200px;
}
.board-section { margin-bottom: 0.75rem; }
.board-section h4 { font-size: 0.8rem; color: var(--text-muted); margin-bottom: 0.3rem; }

.unit-grid { display: flex; flex-wrap: wrap; gap: 0.5rem; }
.unit-card {
  background: var(--bg); border: 1px solid var(--border); border-radius: 6px;
  padding: 0.4rem 0.6rem; font-size: 0.8rem; min-width: 100px;
  font-variant-numeric: tabular-nums;
}
.unit-card .uid { font-family: monospace; color: var(--text-muted); font-size: 0.7rem; }
.unit-card .card-name { font-weight: 600; }
.unit-card .stats { font-size: 0.75rem; }
.unit-card.can-attack { border-color: var(--green); }
.unit-card.new-unit { border-color: var(--green); border-width: 2px; background: #d1e7dd30; }
.unit-card.dead-unit { border-color: var(--red); text-decoration: line-through; opacity: 0.6; }
.unit-card .hp-change { font-weight: 700; font-size: 0.7rem; }
.hp-change.hp-down { color: var(--red); }
.hp-change.hp-up { color: var(--green); }

.event-log {
  background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px;
  padding: 1rem; max-height: 300px; overflow-y: auto;
}
.event-log h3 { font-size: 0.9rem; margin-bottom: 0.5rem; }
.event-entry {
  font-size: 0.8rem; padding: 0.15rem 0;
  font-family: "SFMono-Regular", Consolas, monospace;
}
.event-entry.play_card { color: var(--accent); }
.event-entry.declare_attack { color: #e85d04; }
.event-entry.declare_block { color: #6f42c1; }
.event-entry.combat_resolve { color: var(--red); }

.no-data {
  text-align: center; padding: 3rem; color: var(--text-muted); font-size: 1.1rem;
}
"""

# ---------------------------------------------------------------------------
# app.js
# ---------------------------------------------------------------------------

APP_JS = """\
/* v0.7 Visualization — shared JS */

(function() {
  "use strict";

  // --- Cycle Dashboard ---
  if (document.getElementById("cycle-app")) {
    initDashboard();
  }

  // --- Replay Player ---
  if (document.getElementById("replay-app")) {
    initReplayPlayer();
  }

  function initDashboard() {
    fetch("data/manifest.json")
      .then(r => r.json())
      .then(renderDashboard)
      .catch(err => {
        document.getElementById("cycle-app").innerHTML =
          '<div class="no-data">Failed to load manifest.json: ' + err.message + '</div>';
      });
  }

  function renderDashboard(manifest) {
    const app = document.getElementById("cycle-app");
    const cycles = manifest.cycles || [];
    const replays = manifest.replays || [];

    // Summary bar
    const totalCycles = cycles.length;
    const gatesPassed = cycles.filter(c => c.gate_passed).length;
    const totalCards = cycles.reduce((s, c) => s + (c.cards_added || 0), 0);

    let html = '<div class="summary-bar">';
    html += summaryStatHTML(totalCycles, "Cycles");
    html += summaryStatHTML(gatesPassed, "Gates Passed");
    html += summaryStatHTML(totalCycles - gatesPassed, "Gates Failed");
    html += summaryStatHTML(totalCards, "Cards Added");
    html += summaryStatHTML(replays.length, "Replays");
    html += '</div>';

    // Cycle cards
    html += '<div class="cycle-grid">';
    for (const c of cycles) {
      html += renderCycleCard(c, replays);
    }
    if (cycles.length === 0) {
      html += '<div class="no-data">No cycles found in manifest.</div>';
    }
    html += '</div>';

    app.innerHTML = html;

    // Click handlers for expand/collapse
    app.querySelectorAll(".cycle-card").forEach(card => {
      card.addEventListener("click", function() {
        this.classList.toggle("expanded");
      });
    });
  }

  function summaryStatHTML(val, label) {
    return '<div class="summary-stat"><div class="val">' + val + '</div><div class="lbl">' + label + '</div></div>';
  }

  function renderCycleCard(c, allReplays) {
    const gateClass = c.gate_passed ? "badge-pass" : "badge-fail";
    const gateText = c.gate_passed ? "GATE PASSED" : "GATE FAILED";
    const cycleReplays = allReplays.filter(r => r.cycle_index === c.cycle_index);

    let html = '<div class="cycle-card">';
    html += '<div class="cycle-header">';
    html += '<span class="cycle-id">cycle_' + String(c.cycle_index).padStart(3, "0") + '</span>';
    html += '<span class="badge ' + gateClass + '">' + gateText + '</span>';
    html += '</div>';

    html += '<div class="cycle-subtitle">+' + (c.cards_added || 0) + ' cards promoted</div>';

    // Deltas
    const d = c.deltas || {};
    html += '<div class="delta-grid">';
    html += deltaItemHTML("win_rate", d.win_rate);
    html += deltaItemHTML("avg_turns", d.avg_turns);
    html += deltaItemHTML("mana_waste", d.mana_wasted);
    html += deltaItemHTML("unblk_dmg", d.unblocked_damage);
    html += '</div>';

    // Replay links
    if (cycleReplays.length > 0) {
      html += '<div class="replay-links">';
      for (const r of cycleReplays) {
        html += '<a href="replay.html?replay=' + encodeURIComponent(r.replay_id) +
                '" onclick="event.stopPropagation()" title="' + escapeHTML(r.replay_id) +
                '">' + escapeHTML(r.display_id || r.replay_id) + '</a>';
      }
      html += '</div>';
    }

    // Expandable detail
    html += '<div class="cycle-detail">';

    // Promoted cards
    if (c.promoted_cards && c.promoted_cards.length > 0) {
      html += '<h4>Promoted Cards</h4><ul class="promoted-list">';
      for (const pc of c.promoted_cards) {
        html += '<li>' + escapeHTML(pc.id || pc) + (pc.card_type ? ' (' + pc.card_type + ', cost ' + pc.cost + ')' : '') + '</li>';
      }
      html += '</ul>';
    }

    // Gate checks
    if (c.gate_checks) {
      html += '<div class="gate-checks"><h4>Gate Checks</h4>';
      for (const [name, chk] of Object.entries(c.gate_checks)) {
        const cls = chk.passed ? "chk-pass" : "chk-fail";
        const icon = chk.passed ? "\\u2713" : "\\u2717";
        html += '<div class="gate-check"><span class="' + cls + '">' + icon + '</span> ' +
                name + ': ' + chk.actual + ' (threshold: ' + chk.threshold + ')</div>';
      }
      html += '</div>';
    }

    html += '</div>'; // cycle-detail
    html += '</div>'; // cycle-card
    return html;
  }

  function deltaItemHTML(label, value) {
    let cls = "neutral";
    let display = "—";
    if (value !== undefined && value !== null) {
      display = (value >= 0 ? "+" : "") + (typeof value === "number" ? value.toFixed(4) : value);
      cls = value > 0 ? "positive" : (value < 0 ? "negative" : "neutral");
    }
    return '<div class="delta-item"><div class="dlabel">' + label + '</div><div class="dval ' + cls + '">' + display + '</div></div>';
  }

  // --- Replay Player ---

  function initReplayPlayer() {
    const params = new URLSearchParams(window.location.search);
    const replayId = params.get("replay");

    if (!replayId) {
      document.getElementById("replay-app").innerHTML =
        '<div class="no-data">No replay specified. Use ?replay=&lt;id&gt;</div>';
      return;
    }

    fetch("data/replays/" + encodeURIComponent(replayId) + ".json")
      .then(r => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(events => initPlayer(replayId, events))
      .catch(err => {
        document.getElementById("replay-app").innerHTML =
          '<div class="no-data">Failed to load replay: ' + err.message + '</div>';
      });
  }

  function initPlayer(replayId, events) {
    const app = document.getElementById("replay-app");

    // Parse turn snapshots from events
    const turns = buildTurnSnapshots(events);
    if (turns.length === 0) {
      app.innerHTML = '<div class="no-data">No turns found in replay.</div>';
      return;
    }

    let currentTurn = 0;
    let compact = false;

    function render() {
      const maxTurn = turns.length - 1;
      const t = turns[currentTurn];

      let html = '<h1>Replay</h1><p style="font-family:monospace;font-size:0.85rem;color:var(--text-muted);margin-bottom:1rem">' + escapeHTML(replayId) + '</p>';

      // Controls
      html += '<div class="player-controls">';
      html += '<button id="btn-prev" title="Previous turn (\\u2190)">\\u25c0</button>';
      html += '<span class="turn-label">Turn ' + t.turn + ' / ' + turns[maxTurn].turn + '</span>';
      html += '<button id="btn-next" title="Next turn (\\u2192)">\\u25b6</button>';
      html += '<input type="range" id="turn-slider" min="0" max="' + maxTurn + '" value="' + currentTurn + '">';
      html += '<div class="compact-toggle"><label><input type="checkbox" id="compact-check"' +
              (compact ? ' checked' : '') + '> Compact</label></div>';
      html += '</div>';

      // Board layout
      html += '<div class="board-layout">';
      html += renderPlayerPanel(0, t, turns, currentTurn);
      html += renderBoard(t, turns, currentTurn, compact);
      html += renderPlayerPanel(1, t, turns, currentTurn);
      html += '</div>';

      // Events
      html += renderEventLog(t);

      app.innerHTML = html;

      // Bind events
      document.getElementById("btn-prev").addEventListener("click", () => { if (currentTurn > 0) { currentTurn--; render(); } });
      document.getElementById("btn-next").addEventListener("click", () => { if (currentTurn < maxTurn) { currentTurn++; render(); } });
      document.getElementById("turn-slider").addEventListener("input", function() { currentTurn = parseInt(this.value); render(); });
      document.getElementById("compact-check").addEventListener("change", function() { compact = this.checked; render(); });
    }

    // Keyboard navigation
    document.addEventListener("keydown", function(e) {
      if (e.key === "ArrowLeft") { if (currentTurn > 0) { currentTurn--; render(); } }
      else if (e.key === "ArrowRight") { if (currentTurn < turns.length - 1) { currentTurn++; render(); } }
    });

    render();
  }

  function buildTurnSnapshots(events) {
    const turns = [];
    let currentTurnEvents = [];
    let meta = {};
    let lastP0 = null, lastP1 = null;

    for (const ev of events) {
      if (ev.type === "meta") { meta = ev; continue; }

      if (ev.type === "turn_start") {
        if (currentTurnEvents.length > 0 && lastP0) {
          turns.push({
            turn: currentTurnEvents[0].turn || turns.length,
            active_player: currentTurnEvents[0].active_player,
            p0: lastP0, p1: lastP1,
            events: currentTurnEvents,
            meta: meta,
          });
        }
        lastP0 = ev.p0 || lastP0;
        lastP1 = ev.p1 || lastP1;
        currentTurnEvents = [ev];
      } else if (ev.type === "game_start") {
        lastP0 = ev.p0;
        lastP1 = ev.p1;
      } else if (ev.type === "game_end") {
        currentTurnEvents.push(ev);
        if (lastP0) {
          turns.push({
            turn: ev.turns || currentTurnEvents[0].turn || turns.length,
            active_player: currentTurnEvents[0].active_player,
            p0: lastP0, p1: lastP1,
            events: currentTurnEvents,
            meta: meta,
            game_end: ev,
          });
        }
        currentTurnEvents = [];
      } else {
        currentTurnEvents.push(ev);
      }
    }

    // Remaining events
    if (currentTurnEvents.length > 0 && lastP0) {
      turns.push({
        turn: currentTurnEvents[0].turn || turns.length,
        active_player: currentTurnEvents[0].active_player,
        p0: lastP0, p1: lastP1,
        events: currentTurnEvents,
        meta: meta,
      });
    }

    return turns;
  }

  function renderPlayerPanel(playerIdx, turn, allTurns, turnIdx) {
    const p = playerIdx === 0 ? turn.p0 : turn.p1;
    const hp = p.hp;
    const hpPct = Math.max(0, Math.min(100, (hp / 20) * 100));
    const barClass = hpPct > 50 ? "healthy" : (hpPct > 25 ? "warning" : "danger");

    // HP diff
    let hpDiff = "";
    if (turnIdx > 0) {
      const prev = allTurns[turnIdx - 1];
      const prevP = playerIdx === 0 ? prev.p0 : prev.p1;
      const diff = hp - prevP.hp;
      if (diff !== 0) {
        const cls = diff < 0 ? "hp-down" : "hp-up";
        hpDiff = ' <span class="hp-change ' + cls + '">(' + (diff > 0 ? "+" : "") + diff + ')</span>';
      }
    }

    let html = '<div class="player-panel">';
    html += '<h3>Player ' + playerIdx + (turn.active_player === playerIdx ? ' \\u25c0' : '') + '</h3>';
    html += '<div class="stat">HP: ' + hp + ' / 20' + hpDiff + '</div>';
    html += '<div class="hp-bar-container"><div class="hp-bar ' + barClass + '" style="width:' + hpPct + '%"></div></div>';
    html += '<div class="stat">Mana: ' + p.mana + ' / ' + p.mana_max + '</div>';
    html += '<div class="stat">Hand: ' + p.hand_count + '</div>';
    html += '<div class="stat">Deck: ' + p.deck_count + '</div>';
    html += '<div class="stat">Graveyard: ' + p.graveyard_count + '</div>';
    html += '</div>';
    return html;
  }

  function renderBoard(turn, allTurns, turnIdx, compact) {
    const prevTurn = turnIdx > 0 ? allTurns[turnIdx - 1] : null;
    let html = '<div class="board-panel">';

    for (let pi = 0; pi < 2; pi++) {
      const p = pi === 0 ? turn.p0 : turn.p1;
      const prevP = prevTurn ? (pi === 0 ? prevTurn.p0 : prevTurn.p1) : null;
      const board = p.board || [];
      const prevBoard = prevP ? (prevP.board || []) : [];
      const prevUids = new Set(prevBoard.map(u => u.uid));

      // Find dead units (were in prev board, not in current)
      const currentUids = new Set(board.map(u => u.uid));
      const deadUnits = prevBoard.filter(u => !currentUids.has(u.uid));

      html += '<div class="board-section"><h4>P' + pi + ' Board (' + board.length + ')</h4>';
      html += '<div class="unit-grid">';

      if (board.length === 0 && deadUnits.length === 0) {
        html += '<span style="color:var(--text-muted);font-size:0.8rem">(empty)</span>';
      }

      for (const u of board) {
        const isNew = !prevUids.has(u.uid);
        const prevUnit = prevBoard.find(pu => pu.uid === u.uid);
        const hpDiff = prevUnit ? u.hp - prevUnit.hp : 0;
        let classes = "unit-card";
        if (u.can_attack) classes += " can-attack";
        if (isNew) classes += " new-unit";

        html += '<div class="' + classes + '">';
        if (!compact) html += '<div class="uid">#' + u.uid + '</div>';
        html += '<div class="card-name">' + escapeHTML(u.card_id) + '</div>';
        html += '<div class="stats">' + u.atk + '/' + u.hp;
        if (hpDiff !== 0) {
          const cls = hpDiff < 0 ? "hp-down" : "hp-up";
          html += ' <span class="hp-change ' + cls + '">(' + (hpDiff > 0 ? "+" : "") + hpDiff + ')</span>';
        }
        html += '</div>';
        if (!compact && u.can_attack) html += '<div style="font-size:0.65rem;color:var(--green)">can attack</div>';
        html += '</div>';
      }

      // Show dead units
      for (const u of deadUnits) {
        html += '<div class="unit-card dead-unit">';
        if (!compact) html += '<div class="uid">#' + u.uid + '</div>';
        html += '<div class="card-name">' + escapeHTML(u.card_id) + '</div>';
        html += '<div class="stats">' + u.atk + '/' + u.hp + ' \\u2620</div>';
        html += '</div>';
      }

      html += '</div></div>';
    }

    html += '</div>';
    return html;
  }

  function renderEventLog(turn) {
    const actionTypes = new Set(["play_card", "go_to_combat", "declare_attack", "declare_block", "combat_resolve", "game_end"]);
    const events = (turn.events || []).filter(e => actionTypes.has(e.type));

    let html = '<div class="event-log"><h3>Events (Turn ' + turn.turn + ')</h3>';

    if (events.length === 0) {
      html += '<div class="event-entry" style="color:var(--text-muted)">(no actions this turn)</div>';
    }

    for (const ev of events) {
      let text = "";
      if (ev.type === "play_card") {
        text = "P" + ev.player + " plays " + ev.card_id + " (cost " + ev.cost + ", " + (ev.card_type || "?") + ")";
      } else if (ev.type === "go_to_combat") {
        text = "P" + ev.player + " enters combat";
      } else if (ev.type === "declare_attack") {
        const atks = (ev.attackers || []).map(a => a.card_id + "(atk=" + a.atk + ")").join(", ");
        text = "P" + ev.player + " attacks: " + (atks || "(none)");
      } else if (ev.type === "declare_block") {
        const pairs = ev.pairs || [];
        if (pairs.length > 0) {
          text = "P" + ev.player + " blocks: " + pairs.map(p => p.blocker_card_id + " blocks " + p.attacker_card_id).join(", ");
        } else {
          text = "P" + ev.player + " blocks: (none)";
        }
      } else if (ev.type === "combat_resolve") {
        text = "Combat: " + ev.player_damage + " dmg to player, HP: " + ev.hp_after_p0 + " / " + ev.hp_after_p1;
        if (ev.atk_deaths > 0 || ev.def_deaths > 0) {
          text += " (" + ev.atk_deaths + " atk deaths, " + ev.def_deaths + " def deaths)";
        }
      } else if (ev.type === "game_end") {
        text = "GAME END: " + ev.winner + " in " + ev.turns + " turns (HP: " + (ev.final_hp || []).join("/") + ")";
      }

      html += '<div class="event-entry ' + ev.type + '">\\u2192 ' + escapeHTML(text) + '</div>';
    }

    html += '</div>';
    return html;
  }

  function escapeHTML(str) {
    if (typeof str !== "string") return String(str);
    return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

})();
"""

# ---------------------------------------------------------------------------
# index.html (Cycle Dashboard)
# ---------------------------------------------------------------------------

INDEX_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Cycle Dashboard</title>
  <link rel="stylesheet" href="assets/style.css">
</head>
<body>
  <h1>Cycle Dashboard</h1>
  <div id="cycle-app"><div class="no-data">Loading...</div></div>
  <script src="assets/app.js"></script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# replay.html (Replay Player)
# ---------------------------------------------------------------------------

REPLAY_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Replay Player</title>
  <link rel="stylesheet" href="assets/style.css">
</head>
<body>
  <p><a href="index.html">&larr; Dashboard</a></p>
  <div id="replay-app"><div class="no-data">Loading...</div></div>
  <script src="assets/app.js"></script>
</body>
</html>
"""
