"""Versioned deterministic selection over bounded, feasible LoRA combinations."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations, product

from itov.catalog import MAX_INTEGER, require

ALGORITHM = "itov-rotation-v1"
MAX_COMBINATIONS = 20_000
MAX_TOTAL_COMBINATIONS = 100_000
MAX_WEIGHT_BITS = 4096


class PlanningError(ValueError):
    def __init__(self, code: str, message: str, *, index: int | None = None, details=None):
        super().__init__(message)
        self.code, self.index, self.details = code, index, details

    def to_dict(self) -> dict:
        return {
            "ok": False,
            "code": self.code,
            "error": str(self),
            "index": self.index,
            "details": self.details,
        }


class Draws:
    """SHAKE-256 rejection sampling, independent of Python's random implementation."""

    def __init__(self, seed: int):
        self.seed = seed.to_bytes(8, "big")
        self.counter = 0

    def below(self, bound: int) -> int:
        require(
            0 < bound and bound.bit_length() <= MAX_WEIGHT_BITS,
            "Selection weight exceeds algorithm limits",
        )
        if bound == 1:
            return 0
        bits = (bound - 1).bit_length()
        while True:
            payload = b"ITOV-ROTATION-v1\0" + self.seed + self.counter.to_bytes(8, "big")
            self.counter += 1
            value = int.from_bytes(hashlib.shake_256(payload).digest((bits + 7) // 8), "big")
            value &= (1 << bits) - 1
            if value < bound:
                return value


def choose(items: list, weights: list[int], draws: Draws):
    ticket = draws.below(sum(weights))
    for item, weight in zip(items, weights, strict=True):
        if ticket < weight:
            return item
        ticket -= weight
    raise AssertionError("Weighted selection escaped its total")


@dataclass(frozen=True)
class Stack:
    ids: tuple[str, ...]
    weight: int


def _integer_weights(weights: list[Fraction]) -> list[int]:
    denominator = math.lcm(*(weight.denominator for weight in weights))
    require(denominator.bit_length() <= MAX_WEIGHT_BITS, "Selection denominator exceeds limit")
    values = [weight.numerator * (denominator // weight.denominator) for weight in weights]
    require(sum(values).bit_length() <= MAX_WEIGHT_BITS, "Selection weights exceed limit")
    return values


def feasible_stacks(catalog: dict, request: dict):
    policy = request["lora_policy"]
    loras = {item["id"]: item for item in catalog["loras"]}
    presets = {item["id"]: item for item in catalog["presets"]}
    matrix = catalog["compatibility"]
    hard = {frozenset(pair) for pair in matrix["hard_conflicts"]}
    soft = {frozenset(pair) for pair in matrix["soft_conflicts"]}
    forbidden = hard | soft if policy["soft_conflicts"] == "exclude" else hard
    synergies = sorted(matrix["synergies"], key=lambda item: sorted(item["loras"]))
    require(len(synergies) <= 64, "Planner supports at most 64 synergy declarations")
    pairings = {item["preset"]: set(item["loras"]) for item in matrix["preset_pairings"]}
    slots = sorted(policy["slots"])
    result, exclusions, eligible_ids = {}, [], set()
    work = 0
    for preset_id in sorted(request["presets"]):
        preset = presets[preset_id]
        candidates: dict[str, list[str]] = {slot: [] for slot in slots}
        for key in sorted(policy["ids"]):
            lora = loras[key]
            reasons = []
            if lora["status"] != "active":
                reasons.append("inactive")
            if preset["base_model"] not in lora["base_models"]:
                reasons.append("base_model")
            if lora["slot"] not in candidates:
                reasons.append("slot")
            if lora["strength_milli"]["max"] > 100_000:
                reasons.append("loader_strength_range")
            if reasons:
                exclusions.append({"preset": preset_id, "lora": key, "reasons": reasons})
            else:
                candidates[lora["slot"]].append(key)
                eligible_ids.add(key)
        count = math.prod(len(candidates[slot]) for slot in slots)
        work += count
        require(
            count <= MAX_COMBINATIONS and work <= MAX_TOTAL_COMBINATIONS,
            "LoRA combination limit exceeded; narrow requested candidates or slots",
        )
        tuples, weights = [], []
        for ids in product(*(candidates[slot] for slot in slots)):
            if any(frozenset(pair) in forbidden for pair in combinations(ids, 2)):
                continue
            field = "recommended" if policy["strength_mode"] == "recommended" else "min"
            if (
                sum(loras[key]["strength_milli"][field] for key in ids)
                > policy["max_strength_milli"]
            ):
                continue
            weight = Fraction(math.prod(loras[key]["rotation_weight_milli"] for key in ids))
            preferred = pairings.get(preset_id, set())
            weight *= Fraction(policy["preferred_multiplier_milli"], 1000) ** len(
                set(ids) & preferred
            )
            for synergy in synergies:
                if set(synergy["loras"]) <= set(ids):
                    weight *= Fraction(synergy["weight_milli"], 1000)
            require(
                max(weight.numerator.bit_length(), weight.denominator.bit_length())
                <= MAX_WEIGHT_BITS,
                "Selection weights exceed limit",
            )
            tuples.append(ids)
            weights.append(weight)
        result[preset_id] = [
            Stack(ids, weight)
            for ids, weight in zip(tuples, _integer_weights(weights), strict=True)
        ]
    return result, exclusions, eligible_ids


def select_jobs(catalog: dict, request: dict, stacks: dict) -> list[dict]:
    presets = {item["id"]: item for item in catalog["presets"]}
    loras = {item["id"]: item for item in catalog["loras"]}
    policy = request["lora_policy"]
    draws = Draws(request["seed"])
    jobs: list[dict] = []
    used_seeds: set[int] = set()
    soft = sorted(sorted(pair) for pair in catalog["compatibility"]["soft_conflicts"])

    def recent(size):
        return jobs[-size:] if size else []

    for index in range(request["count"]):
        recent_ids = {job["preset"] for job in recent(request["no_repeat_within"])}
        recent_categories = {job["category"] for job in recent(request["category_cooldown"])}
        recent_loras = {
            lora["id"] for job in recent(policy["no_repeat_within"]) for lora in job["loras"]
        }
        available, reasons = {}, {}
        for key in sorted(request["presets"]):
            if key in recent_ids:
                reasons[key] = "preset_cooldown"
            elif presets[key]["category"] in recent_categories:
                reasons[key] = "category_cooldown"
            else:
                options = [
                    stack for stack in stacks[key] if not recent_loras.intersection(stack.ids)
                ]
                if options:
                    available[key] = options
                else:
                    reasons[key] = "no_feasible_stack" if not stacks[key] else "lora_cooldown"
        if not available:
            raise PlanningError(
                "rotation_exhausted",
                "No next pick satisfies the requested constraints",
                index=index,
                details=reasons,
            )
        key = choose(
            list(available), [presets[key]["rotation_weight_milli"] for key in available], draws
        )
        stack = choose(available[key], [stack.weight for stack in available[key]], draws)
        preset = presets[key]
        seed = None
        if preset["seed"] is not None:
            seed = preset["seed"]["base"] + request["seed"] + index * preset["seed"]["step"]
            while seed in used_seeds:
                seed += preset["seed"]["step"]
            if seed > MAX_INTEGER:
                raise PlanningError(
                    "seed_overflow", "Seed exceeds the unsigned 64-bit range", index=index
                )
            used_seeds.add(seed)
        remaining = policy["max_strength_milli"]
        chosen = []
        for position, lora_id in enumerate(stack.ids):
            lora = loras[lora_id]
            strength = lora["strength_milli"]
            if policy["strength_mode"] == "recommended":
                amount = strength["recommended"]
            else:
                reserved = sum(
                    loras[next_id]["strength_milli"]["min"] for next_id in stack.ids[position + 1 :]
                )
                maximum = min(strength["max"], remaining - reserved)
                amount = strength["min"] + draws.below(maximum - strength["min"] + 1)
            remaining -= amount
            chosen.append(
                {
                    "id": lora_id,
                    "slot": lora["slot"],
                    "asset": lora["asset"],
                    "loader_name": policy["loader_names"][lora_id],
                    "strength_milli": amount,
                }
            )
        jobs.append(
            {
                "index": index,
                "preset": key,
                "category": preset["category"],
                "seed": seed,
                "loras": chosen,
                "total_strength_milli": policy["max_strength_milli"] - remaining,
                "soft_conflicts": [pair for pair in soft if set(pair) <= set(stack.ids)],
            }
        )
    return jobs
