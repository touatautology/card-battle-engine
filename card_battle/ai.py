"""Phase 6: AI agents – ABC, GreedyAI, HumanAgent."""

from __future__ import annotations

import copy
from abc import ABC, abstractmethod

from card_battle.actions import Action, EndTurn, Attack, PlayCard, apply_action, get_legal_actions
from card_battle.models import GameState


class Agent(ABC):
    @abstractmethod
    def choose_action(self, gs: GameState, legal_actions: list[Action]) -> Action:
        ...


# ---------------------------------------------------------------------------
# GreedyAI
# ---------------------------------------------------------------------------

def _evaluate(gs: GameState, player_idx: int) -> float:
    me = gs.players[player_idx]
    opp = gs.players[1 - player_idx]

    # Instant win/loss
    if opp.hp <= 0:
        return 1000.0
    if me.hp <= 0:
        return -1000.0

    score = 0.0
    score += (20 - opp.hp) * 3.0       # opponent HP lost
    score -= (20 - me.hp) * 2.0        # my HP lost
    score += sum(u.atk for u in me.board) * 1.5
    score -= sum(u.atk for u in opp.board) * 1.5
    score += sum(u.hp for u in me.board) * 0.5
    score -= sum(u.hp for u in opp.board) * 0.5
    score += len(me.hand) * 0.5
    return score


class GreedyAI(Agent):
    def choose_action(self, gs: GameState, legal_actions: list[Action]) -> Action:
        player_idx = gs.active_player
        best_action = EndTurn()
        best_score = _evaluate(gs, player_idx)

        for action in legal_actions:
            if isinstance(action, EndTurn):
                continue
            sim = copy.deepcopy(gs)
            apply_action(sim, action)
            score = _evaluate(sim, player_idx)
            if score > best_score:
                best_score = score
                best_action = action

        return best_action


# ---------------------------------------------------------------------------
# HumanAgent (stdin)
# ---------------------------------------------------------------------------

class HumanAgent(Agent):
    def choose_action(self, gs: GameState, legal_actions: list[Action]) -> Action:
        from card_battle.display import render_board, render_actions
        render_board(gs)
        render_actions(legal_actions, gs)

        while True:
            try:
                raw = input("Choose action number: ").strip()
                idx = int(raw)
                if 0 <= idx < len(legal_actions):
                    return legal_actions[idx]
                print(f"  Invalid index. Enter 0-{len(legal_actions)-1}.")
            except (ValueError, EOFError):
                print("  Enter a number.")
