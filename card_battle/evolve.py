"""v0.3: Evolutionary deck search — config, runner, artifact output."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from card_battle.evaluation import evaluate_population
from card_battle.loader import load_cards, load_deck
from card_battle.models import Card, DeckDef
from card_battle.mutation import (
    deck_to_counts,
    counts_to_deck,
    mutate_deck,
    random_deck,
)
from card_battle.selection import compute_fitness_stats, select_next_generation


@dataclass
class EvolutionConfig:
    global_seed: int = 42
    generations: int = 20
    population_size: int = 30
    matches_per_eval: int = 2
    elite_pool_size: int = 5
    elitism: int = 3
    tournament_k: int = 4
    mutation_weights: dict[str, float] = field(
        default_factory=lambda: {"swap_one": 0.5, "swap_n": 0.3, "tweak_counts": 0.2}
    )
    swap_n_range: tuple[int, int] = (2, 5)
    cards_path: str = "data/cards.json"
    seed_decks: list[str] = field(default_factory=list)
    initial_population: str = "seed_decks"  # "seed_decks" or "random"
    output_dir: str = "output/evolve"
    baseline_decks: list[str] = field(default_factory=list)
    log_every_n: int = 1
    top_n_summary: int = 5
    telemetry: dict[str, Any] = field(
        default_factory=lambda: {"enabled": False, "save_match_summaries": False}
    )
    metrics: dict[str, Any] = field(
        default_factory=lambda: {"top_n_decks": 5}
    )
    evaluation: dict[str, Any] = field(
        default_factory=lambda: {}
    )

    @classmethod
    def from_json(cls, path: str | Path, **overrides: Any) -> "EvolutionConfig":
        """Load config from JSON file with optional CLI overrides."""
        path = Path(path)
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        raw.update({k: v for k, v in overrides.items() if v is not None})
        # Handle swap_n_range as tuple
        if "swap_n_range" in raw and isinstance(raw["swap_n_range"], list):
            raw["swap_n_range"] = tuple(raw["swap_n_range"])
        return cls(**raw)


def _deck_to_dict(deck: DeckDef) -> dict[str, Any]:
    """Serialize a DeckDef to a JSON-friendly dict."""
    return {
        "deck_id": deck.deck_id,
        "entries": [{"card_id": e.card_id, "count": e.count} for e in deck.entries],
    }


class EvolutionRunner:
    """Orchestrates the evolutionary deck search loop."""

    def __init__(self, config: EvolutionConfig) -> None:
        self.config = config
        self.rng = random.Random(config.global_seed)
        self.card_db: dict[str, Card] = {}
        self.population: list[DeckDef] = []
        self.elite_pool: list[DeckDef] = []
        self.best_of_run: list[dict[str, Any]] = []
        self._deck_counter = 0

    def run(self) -> None:
        """Execute the full evolutionary loop."""
        cfg = self.config
        out = Path(cfg.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        telemetry_on = cfg.telemetry.get("enabled", False)

        # Load cards
        self.card_db = load_cards(cfg.cards_path)

        # Initialize population and elite pool
        self._initialize_population()
        self._initialize_elite_pool()

        # Save config
        self._write_json(out / "config_used.json", {
            k: v if not isinstance(v, tuple) else list(v)
            for k, v in vars(cfg).items()
        })

        policy_mix = cfg.evaluation.get("policies") if cfg.evaluation else None

        for gen in range(cfg.generations):
            # 1. Evaluate
            eval_out = evaluate_population(
                self.population, self.elite_pool, self.card_db,
                cfg.global_seed, gen, cfg.matches_per_eval,
                collect_telemetry=telemetry_on,
                policy_mix=policy_mix,
            )
            if telemetry_on:
                scored, gen_summaries = eval_out  # type: ignore[misc]
            else:
                scored = eval_out  # type: ignore[assignment]
                gen_summaries = []

            # 2. Update elite pool (top N across all time)
            self._update_elite_pool(scored)

            # 3. Track best-of-run
            best_deck, best_fit = max(scored, key=lambda x: x[1])
            self.best_of_run.append({
                "generation": gen,
                "deck_id": best_deck.deck_id,
                "fitness": best_fit,
                "deck": _deck_to_dict(best_deck),
            })

            # 4. Output artifacts
            if gen % cfg.log_every_n == 0:
                self._write_generation(out, gen, scored)

            # 4b. Output telemetry metrics
            if telemetry_on and gen_summaries:
                from card_battle.metrics import aggregate_match_summaries
                gen_metrics = aggregate_match_summaries(
                    gen_summaries, group_keys=["deck_id"],
                )
                # Add top-N deck breakdown
                top_n = cfg.metrics.get("top_n_decks", 5)
                ranked = sorted(scored, key=lambda x: x[1], reverse=True)
                top_ids = {d.deck_id for d, _ in ranked[:top_n]}
                top_summaries = [s for s in gen_summaries if s.get("deck_id") in top_ids]
                gen_metrics["top_n_decks"] = aggregate_match_summaries(
                    top_summaries, group_keys=["deck_id"],
                )
                best_summaries = [
                    s for s in gen_summaries
                    if s.get("deck_id") == best_deck.deck_id
                ]
                gen_metrics["best_deck"] = aggregate_match_summaries(best_summaries)
                if policy_mix:
                    gen_metrics["by_policy_pair"] = aggregate_match_summaries(
                        gen_summaries,
                        group_keys=["deck_id", "candidate_policy", "opponent_policy"],
                    )
                self._write_json(out / f"gen_{gen:03d}_metrics.json", gen_metrics)

            stats = compute_fitness_stats(scored)
            print(
                f"Gen {gen:3d} | "
                f"mean={stats['mean']:.4f} max={stats['max']:.4f} "
                f"min={stats['min']:.4f} std={stats['std']:.4f} | "
                f"best={best_deck.deck_id}"
            )

            # 5. Select parents
            parents = select_next_generation(
                scored, cfg.population_size,
                cfg.elitism, cfg.tournament_k, self.rng,
            )

            # 6. Mutate non-elite to produce next generation
            next_pop: list[DeckDef] = []
            for i, deck in enumerate(parents):
                if i < cfg.elitism:
                    # Elite: keep as-is
                    next_pop.append(deck)
                else:
                    # Mutate and assign new ID
                    mutated = mutate_deck(
                        deck, self.card_db, self.rng,
                        cfg.mutation_weights, cfg.swap_n_range,
                    )
                    mutated = self._assign_deck_id(mutated, gen + 1, i)
                    next_pop.append(mutated)

            self.population = next_pop

        # Final: write best_decks.json
        self._write_json(out / "best_decks.json", self.best_of_run)
        print(f"\nEvolution complete. Artifacts in: {out}")

    def _initialize_population(self) -> None:
        """Create the initial population from seed decks or randomly."""
        cfg = self.config

        if cfg.initial_population == "seed_decks" and cfg.seed_decks:
            # Load seed decks
            seeds: list[DeckDef] = []
            for path in cfg.seed_decks:
                seeds.append(load_deck(path, self.card_db))

            # Fill population: cycle through seeds + mutate
            pop: list[DeckDef] = []
            for i in range(cfg.population_size):
                base = seeds[i % len(seeds)]
                if i < len(seeds):
                    # Keep original seed decks as-is
                    pop.append(base)
                else:
                    # Mutate a copy of a seed deck
                    mutated = mutate_deck(
                        base, self.card_db, self.rng,
                        cfg.mutation_weights, cfg.swap_n_range,
                    )
                    mutated = self._assign_deck_id(mutated, 0, i)
                    pop.append(mutated)
            self.population = pop
        else:
            # Random initialization
            pop = []
            for i in range(cfg.population_size):
                deck_id = f"rnd_g0_s{i}"
                pop.append(random_deck(deck_id, self.card_db, self.rng))
            self.population = pop

    def _initialize_elite_pool(self) -> None:
        """Set up initial elite pool from seed decks or population sample."""
        cfg = self.config
        if cfg.seed_decks:
            self.elite_pool = []
            for path in cfg.seed_decks:
                self.elite_pool.append(load_deck(path, self.card_db))
            # Trim to elite_pool_size
            self.elite_pool = self.elite_pool[:cfg.elite_pool_size]
        else:
            # Use first N from population
            self.elite_pool = list(self.population[:cfg.elite_pool_size])

    def _update_elite_pool(self, scored: list[tuple[DeckDef, float]]) -> None:
        """Update elite pool with top decks from current generation."""
        cfg = self.config
        # Combine current elite pool (with neutral fitness) and scored decks
        # Keep the top N unique deck_ids by fitness
        all_candidates: dict[str, tuple[DeckDef, float]] = {}
        for deck in self.elite_pool:
            if deck.deck_id not in all_candidates:
                all_candidates[deck.deck_id] = (deck, 0.0)
        for deck, fitness in scored:
            existing = all_candidates.get(deck.deck_id)
            if existing is None or fitness > existing[1]:
                all_candidates[deck.deck_id] = (deck, fitness)

        ranked = sorted(all_candidates.values(), key=lambda x: x[1], reverse=True)
        self.elite_pool = [deck for deck, _ in ranked[:cfg.elite_pool_size]]

    def _assign_deck_id(self, deck: DeckDef, gen: int, slot: int) -> DeckDef:
        """Assign a unique ID to a deck."""
        self._deck_counter += 1
        new_id = f"evo_g{gen}_s{slot}_{self._deck_counter}"
        counts = deck_to_counts(deck)
        return counts_to_deck(new_id, counts)

    def _write_generation(
        self, out: Path, gen: int, scored: list[tuple[DeckDef, float]],
    ) -> None:
        """Write per-generation artifacts."""
        gen_dir = out / f"gen_{gen:03d}"
        gen_dir.mkdir(parents=True, exist_ok=True)

        # population.json — all decks + fitness
        pop_data = []
        for deck, fitness in scored:
            pop_data.append({
                "deck_id": deck.deck_id,
                "fitness": fitness,
                "entries": [{"card_id": e.card_id, "count": e.count} for e in deck.entries],
            })
        self._write_json(gen_dir / "population.json", pop_data)

        # summary.json — top N + stats
        stats = compute_fitness_stats(scored)
        ranked = sorted(scored, key=lambda x: x[1], reverse=True)
        top_n = ranked[:self.config.top_n_summary]
        summary = {
            "generation": gen,
            "stats": stats,
            "top_decks": [
                {"deck_id": d.deck_id, "fitness": f}
                for d, f in top_n
            ],
        }
        self._write_json(gen_dir / "summary.json", summary)

    @staticmethod
    def _write_json(path: Path, data: Any) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
