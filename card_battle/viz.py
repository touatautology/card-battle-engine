"""v0.7: Log-driven rich visualization — manifest builder & static site export."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from card_battle.viz_templates import APP_JS, INDEX_HTML, REPLAY_HTML, STYLE_CSS


def convert_replay_jsonl_to_json(jsonl_path: Path, out_path: Path) -> str:
    """Convert a JSONL replay file to a JSON array file.

    Returns the generated replay_id string.
    """
    jsonl_path = Path(jsonl_path)
    out_path = Path(out_path)

    events: list[dict[str, Any]] = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))

    # Extract replay_id from meta event
    seed = "unknown"
    deck_ids: list[str] = []
    for ev in events:
        if ev.get("type") == "meta":
            seed = str(ev.get("seed", "unknown"))
            deck_ids = ev.get("deck_ids", [])
            break

    if len(deck_ids) >= 2:
        replay_id = f"{deck_ids[0]}_vs_{deck_ids[1]}_{seed}"
    else:
        replay_id = f"replay_{seed}"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(events, f, ensure_ascii=False, separators=(",", ":"))

    return replay_id


def build_manifest(run_dir: Path, replays_out_dir: Path) -> dict[str, Any]:
    """Scan run_dir artifacts and build a manifest dict.

    Also converts any JSONL replays to JSON in replays_out_dir.
    """
    run_dir = Path(run_dir)
    replays_out_dir = Path(replays_out_dir)

    manifest: dict[str, Any] = {
        "cycles": [],
        "replays": [],
    }

    # Read cycle_summary.json
    summary_path = run_dir / "cycle_summary.json"
    if not summary_path.exists():
        return manifest

    with open(summary_path, encoding="utf-8") as f:
        summary = json.load(f)

    raw_cycles = summary.get("cycles", [])

    for raw_cycle in raw_cycles:
        cycle_index = raw_cycle.get("cycle_index", 0)
        cycle_id = f"cycle_{cycle_index:03d}"

        cycle_entry: dict[str, Any] = {
            "cycle_index": cycle_index,
            "cycle_id": cycle_id,
            "gate_passed": raw_cycle.get("gate_passed", False),
            "cards_added": raw_cycle.get("cards_added", 0),
            "exit_reason": raw_cycle.get("exit_reason", ""),
        }

        # Read promotion_report.json for deltas and gate checks
        promo_report_path = (
            run_dir / "cycles" / cycle_id / "promote" / "promotion_report.json"
        )
        if promo_report_path.exists():
            with open(promo_report_path, encoding="utf-8") as f:
                promo_report = json.load(f)

            # Win rate delta (average across targets)
            delta_dict = promo_report.get("delta", {})
            if delta_dict:
                wr_delta = sum(delta_dict.values()) / len(delta_dict)
            else:
                wr_delta = 0.0

            # Telemetry deltas
            before_telem = promo_report.get("before", {}).get(
                "telemetry_aggregate", {}
            )
            after_telem = promo_report.get("after", {}).get(
                "telemetry_aggregate", {}
            )

            avg_turns_delta = after_telem.get(
                "avg_total_turns", 0
            ) - before_telem.get("avg_total_turns", 0)

            before_mw = (before_telem.get("avg_p0_mana_wasted", 0)
                         + before_telem.get("avg_p1_mana_wasted", 0)) / 2
            after_mw = (after_telem.get("avg_p0_mana_wasted", 0)
                        + after_telem.get("avg_p1_mana_wasted", 0)) / 2
            mana_wasted_delta = after_mw - before_mw

            before_ud = (before_telem.get("avg_p0_unblocked_damage", 0)
                         + before_telem.get("avg_p1_unblocked_damage", 0)) / 2
            after_ud = (after_telem.get("avg_p0_unblocked_damage", 0)
                        + after_telem.get("avg_p1_unblocked_damage", 0)) / 2
            unblocked_dmg_delta = after_ud - before_ud

            cycle_entry["deltas"] = {
                "win_rate": round(wr_delta, 4),
                "avg_turns": round(avg_turns_delta, 4),
                "mana_wasted": round(mana_wasted_delta, 4),
                "unblocked_damage": round(unblocked_dmg_delta, 4),
            }

            # Gate checks
            gate_info = promo_report.get("gate", {})
            if gate_info.get("checks"):
                cycle_entry["gate_checks"] = gate_info["checks"]

        # Read selected_cards.json for promoted cards info
        selected_path = (
            run_dir / "cycles" / cycle_id / "cardgen" / "selected_cards.json"
        )
        if selected_path.exists():
            with open(selected_path, encoding="utf-8") as f:
                selected_cards = json.load(f)
            promoted_cards = []
            for report in selected_cards:
                card = report.get("candidate_card", report)
                promoted_cards.append({
                    "id": card.get("id", ""),
                    "card_type": card.get("card_type", ""),
                    "cost": card.get("cost", 0),
                })
            cycle_entry["promoted_cards"] = promoted_cards

        # Convert replays
        replays_dir = run_dir / "cycles" / cycle_id / "replays"
        if replays_dir.exists():
            jsonl_files = sorted(replays_dir.glob("*.jsonl"))
            for jsonl_file in jsonl_files:
                # Determine output path — use temp name, rename after getting id
                tmp_out = replays_out_dir / f"_tmp_{jsonl_file.stem}.json"
                replay_id = convert_replay_jsonl_to_json(jsonl_file, tmp_out)
                final_out = replays_out_dir / f"{replay_id}.json"
                tmp_out.rename(final_out)

                manifest["replays"].append({
                    "replay_id": replay_id,
                    "cycle_index": cycle_index,
                    "source_file": jsonl_file.name,
                })

        manifest["cycles"].append(cycle_entry)

    # Stable sort
    manifest["cycles"].sort(key=lambda c: c["cycle_index"])
    manifest["replays"].sort(key=lambda r: r["replay_id"])

    return manifest


def export_static_site(
    run_dir: str | Path,
    out_dir: str | Path,
) -> Path:
    """Generate the static visualization site.

    Returns the output directory path.
    """
    run_dir = Path(run_dir)
    out_dir = Path(out_dir)

    # Create directories
    replays_out_dir = out_dir / "data" / "replays"
    replays_out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "assets").mkdir(parents=True, exist_ok=True)

    # Build manifest
    manifest = build_manifest(run_dir, replays_out_dir)

    # Write manifest
    manifest_path = out_dir / "data" / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False, sort_keys=True)

    # Write HTML/JS/CSS from templates
    with open(out_dir / "index.html", "w", encoding="utf-8") as f:
        f.write(INDEX_HTML)

    with open(out_dir / "replay.html", "w", encoding="utf-8") as f:
        f.write(REPLAY_HTML)

    with open(out_dir / "assets" / "app.js", "w", encoding="utf-8") as f:
        f.write(APP_JS)

    with open(out_dir / "assets" / "style.css", "w", encoding="utf-8") as f:
        f.write(STYLE_CSS)

    return out_dir
