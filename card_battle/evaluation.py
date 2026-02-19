"""v0.3: Fitness evaluation via match simulation."""

from __future__ import annotations

import hashlib
from typing import Any

from card_battle.ai import GreedyAI
from card_battle.engine import init_game, run_game
from card_battle.models import Card, DeckDef, GameResult
from card_battle.telemetry import MatchTelemetry

# Type alias for policy_mix configuration
PolicyMix = dict[str, list[dict[str, Any]]]


def derive_match_seed(
    global_seed: int,
    generation: int,
    deck_a_id: str,
    deck_b_id: str,
    game_index: int,
    seat_swapped: bool,
    pc_name: str = "",
    po_name: str = "",
) -> int:
    """Deterministic seed from match parameters via SHA-256.

    When pc_name/po_name are empty strings, produces the same seed as v3.1
    for backward compatibility.
    """
    swap_flag = 1 if seat_swapped else 0
    key = f"{global_seed}:{generation}:{deck_a_id}:{deck_b_id}:{game_index}:{swap_flag}"
    if pc_name or po_name:
        key += f":{pc_name}:{po_name}"
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _match_id_from_seed(seed: int, swapped: bool) -> str:
    """Generate a stable match_id string."""
    return f"m_{seed}_{int(swapped)}"


def _score_game(log: Any, swapped: bool) -> float:
    """Extract score (1.0/0.5/0.0) for the candidate deck from a game log."""
    if swapped:
        if log.winner == GameResult.PLAYER_1_WIN:
            return 1.0
        elif log.winner == GameResult.DRAW:
            return 0.5
    else:
        if log.winner == GameResult.PLAYER_0_WIN:
            return 1.0
        elif log.winner == GameResult.DRAW:
            return 0.5
    return 0.0


def _make_telemetry(
    collect: bool,
    save_turn_trace: bool = False,
    turn_trace_max_cards: int = 3,
) -> MatchTelemetry | None:
    if not collect:
        return None
    return MatchTelemetry(
        save_turn_trace=save_turn_trace,
        turn_trace_max_cards=turn_trace_max_cards,
    )


def evaluate_deck_vs_pool(
    deck: DeckDef,
    elite_pool: list[DeckDef],
    card_db: dict[str, Card],
    global_seed: int,
    generation: int,
    matches_per_opponent: int,
    collect_telemetry: bool = False,
    policy_mix: PolicyMix | None = None,
    save_turn_trace: bool = False,
    turn_trace_max_cards: int = 3,
) -> float | tuple[float, list[dict[str, Any]]]:
    """Evaluate a deck against the elite pool. Returns average win rate [0, 1].

    Each matchup is played matches_per_opponent times x 2 seats (normal + swapped).
    Win = 1.0, Draw = 0.5, Loss = 0.0.

    If policy_mix is None, uses GreedyAI vs GreedyAI (v3.1 compatible).
    If policy_mix is provided, evaluates across all candidate x opponent policy
    pairs with weighted averaging.

    If collect_telemetry is True, returns (win_rate, summaries) instead of just win_rate.
    """
    if not elite_pool:
        return (0.5, []) if collect_telemetry else 0.5

    if policy_mix is not None:
        return _evaluate_multi_policy(
            deck, elite_pool, card_db, global_seed, generation,
            matches_per_opponent, collect_telemetry, policy_mix,
            save_turn_trace, turn_trace_max_cards,
        )

    # v3.1 compatible path: GreedyAI vs GreedyAI
    agents = (GreedyAI(), GreedyAI())
    total_score = 0.0
    total_games = 0
    summaries: list[dict[str, Any]] = []

    for opponent in elite_pool:
        for game_idx in range(matches_per_opponent):
            for swapped in (False, True):
                seed = derive_match_seed(
                    global_seed, generation,
                    deck.deck_id, opponent.deck_id,
                    game_idx, swapped,
                )
                tm = _make_telemetry(collect_telemetry, save_turn_trace, turn_trace_max_cards)
                if swapped:
                    gs = init_game(card_db, opponent, deck, seed)
                else:
                    gs = init_game(card_db, deck, opponent, seed)
                log = run_game(gs, agents, telemetry=tm)
                total_score += _score_game(log, swapped)

                if tm is not None:
                    s = tm.to_summary()
                    s["match_id"] = _match_id_from_seed(seed, swapped)
                    s["deck_id"] = deck.deck_id
                    s["opponent_id"] = opponent.deck_id
                    s["swapped"] = swapped
                    if swapped:
                        s["deck_id_p0"] = opponent.deck_id
                        s["deck_id_p1"] = deck.deck_id
                    else:
                        s["deck_id_p0"] = deck.deck_id
                        s["deck_id_p1"] = opponent.deck_id
                    summaries.append(s)

                total_games += 1

    win_rate = total_score / total_games
    if collect_telemetry:
        return (win_rate, summaries)
    return win_rate


def _evaluate_multi_policy(
    deck: DeckDef,
    elite_pool: list[DeckDef],
    card_db: dict[str, Card],
    global_seed: int,
    generation: int,
    matches_per_opponent: int,
    collect_telemetry: bool,
    policy_mix: PolicyMix,
    save_turn_trace: bool = False,
    turn_trace_max_cards: int = 3,
) -> float | tuple[float, list[dict[str, Any]]]:
    """Evaluate with multiple candidate/opponent policy pairs."""
    from card_battle.policies import default_registry, normalize_weights

    registry = default_registry()

    # Default to greedy:1.0 if candidates/opponents not specified
    cand_raw = policy_mix.get("candidates", [{"name": "greedy", "weight": 1.0}])
    opp_raw = policy_mix.get("opponents", [{"name": "greedy", "weight": 1.0}])
    cand_entries = normalize_weights(cand_raw)
    opp_entries = normalize_weights(opp_raw)

    total_weighted = 0.0
    total_weight = 0.0
    summaries: list[dict[str, Any]] = []

    for pc_name, wc in cand_entries:
        pc = registry.get_policy(pc_name)
        for po_name, wo in opp_entries:
            po = registry.get_policy(po_name)
            pair_weight = wc * wo
            pair_score = 0.0
            pair_games = 0

            for opponent in elite_pool:
                for game_idx in range(matches_per_opponent):
                    for swapped in (False, True):
                        seed = derive_match_seed(
                            global_seed, generation,
                            deck.deck_id, opponent.deck_id,
                            game_idx, swapped,
                            pc_name, po_name,
                        )
                        cand_agent = pc.make_agent(seed)
                        opp_agent = po.make_agent(seed + 1)

                        tm = _make_telemetry(collect_telemetry, save_turn_trace, turn_trace_max_cards)
                        if swapped:
                            agents = (opp_agent, cand_agent)
                            gs = init_game(card_db, opponent, deck, seed)
                        else:
                            agents = (cand_agent, opp_agent)
                            gs = init_game(card_db, deck, opponent, seed)
                        log = run_game(gs, agents, telemetry=tm)
                        pair_score += _score_game(log, swapped)

                        if tm is not None:
                            s = tm.to_summary()
                            s["match_id"] = _match_id_from_seed(seed, swapped)
                            s["deck_id"] = deck.deck_id
                            s["opponent_id"] = opponent.deck_id
                            s["swapped"] = swapped
                            s["candidate_policy"] = pc_name
                            s["opponent_policy"] = po_name
                            if swapped:
                                s["deck_id_p0"] = opponent.deck_id
                                s["deck_id_p1"] = deck.deck_id
                            else:
                                s["deck_id_p0"] = deck.deck_id
                                s["deck_id_p1"] = opponent.deck_id
                            summaries.append(s)

                        pair_games += 1

            pair_wr = pair_score / pair_games if pair_games > 0 else 0.5
            total_weighted += pair_weight * pair_wr
            total_weight += pair_weight

    fitness = total_weighted / total_weight if total_weight > 0 else 0.5
    if collect_telemetry:
        return (fitness, summaries)
    return fitness


def evaluate_population(
    population: list[DeckDef],
    elite_pool: list[DeckDef],
    card_db: dict[str, Card],
    global_seed: int,
    generation: int,
    matches_per_opponent: int,
    collect_telemetry: bool = False,
    policy_mix: PolicyMix | None = None,
    save_turn_trace: bool = False,
    turn_trace_max_cards: int = 3,
) -> list[tuple[DeckDef, float]] | tuple[list[tuple[DeckDef, float]], list[dict[str, Any]]]:
    """Evaluate all decks in a population against the elite pool.

    If collect_telemetry is True, returns (scored, all_summaries).
    """
    results: list[tuple[DeckDef, float]] = []
    all_summaries: list[dict[str, Any]] = []

    for deck in population:
        out = evaluate_deck_vs_pool(
            deck, elite_pool, card_db,
            global_seed, generation, matches_per_opponent,
            collect_telemetry=collect_telemetry,
            policy_mix=policy_mix,
            save_turn_trace=save_turn_trace,
            turn_trace_max_cards=turn_trace_max_cards,
        )
        if collect_telemetry:
            fitness, sums = out  # type: ignore[misc]
            all_summaries.extend(sums)
        else:
            fitness = out  # type: ignore[assignment]
        results.append((deck, fitness))

    if collect_telemetry:
        return (results, all_summaries)
    return results
