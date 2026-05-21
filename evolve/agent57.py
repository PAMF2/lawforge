"""Agent57-style meta-controller over hypothesis arms.

Inspired by Badia et al. 2020 (Never-Give-Up / Agent57): a meta-bandit selects
which policy/hypothesis to roll out next, based on observed return statistics.
Here, "arm" = one hypothesis from program.md; "return" = delta in val_solved_rate.

Adaptive: cold-start uniform, then UCB1-tuned with windowed reward to track
non-stationarity (current train.py state changes the response surface).
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class Arm:
    name: str
    apply: Callable[[Path], None]  # mutates train.py / agent.py / prompt
    pulls: int = 0
    rewards: list[float] = field(default_factory=list)
    last_used_gen: int = -1

    def mean(self) -> float:
        return sum(self.rewards) / max(1, len(self.rewards))

    def windowed_mean(self, w: int = 8) -> float:
        tail = self.rewards[-w:]
        return sum(tail) / max(1, len(tail))


class Agent57Meta:
    def __init__(self, arms: list[Arm], c: float = 1.5, novelty_bonus: float = 0.1):
        self.arms = arms
        self.c = c
        self.novelty_bonus = novelty_bonus
        self.t = 0

    def select(self) -> Arm:
        self.t += 1
        # cold start
        unpulled = [a for a in self.arms if a.pulls == 0]
        if unpulled:
            return random.choice(unpulled)
        # UCB1-tuned + novelty (gens since last use)
        scored = []
        for a in self.arms:
            mu = a.windowed_mean(w=8)
            ucb = self.c * math.sqrt(math.log(self.t) / a.pulls)
            novelty = self.novelty_bonus * math.log(1 + (self.t - a.last_used_gen))
            scored.append((mu + ucb + novelty, a))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]

    def update(self, arm: Arm, reward: float):
        arm.pulls += 1
        arm.rewards.append(reward)
        arm.last_used_gen = self.t

    def save(self, path: Path):
        state = {
            "t": self.t,
            "arms": [
                {"name": a.name, "pulls": a.pulls, "rewards": a.rewards,
                 "last_used_gen": a.last_used_gen}
                for a in self.arms
            ],
        }
        path.write_text(json.dumps(state, indent=2))

    def load(self, path: Path):
        if not path.exists():
            return
        state = json.loads(path.read_text())
        self.t = state["t"]
        by_name = {a.name: a for a in self.arms}
        for s in state["arms"]:
            a = by_name.get(s["name"])
            if a:
                a.pulls = s["pulls"]
                a.rewards = s["rewards"]
                a.last_used_gen = s["last_used_gen"]
