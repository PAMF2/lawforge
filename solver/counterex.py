"""Deterministic finite-magma counterexample search (Mace4-style, lite).

For a pair (Eq1, Eq2) where we suspect Eq1 does NOT imply Eq2, enumerate small
magmas (order n = 2..MAX_ORDER) and check whether the magma satisfies Eq1 but
violates Eq2. If found, emit the Cayley table as a Lean witness.

Uses pure Python — no SAT solver, no external deps. Targets orders 2..5
(2^4=16, 3^9=19683, 4^16=4.3e9, 5^25=3e17). At order 4 we sample randomly
(MAX_SAMPLES) rather than exhaust.

Equation language: terms over variables {x, y, z, w} with binary op `*`.
Examples:
  "x = x*y"        -> AST: Var(x) eq App(Var(x), Var(y))
  "x*(y*z) = (x*y)*z"  -> associativity
"""
from __future__ import annotations

import itertools
import random
import re
from dataclasses import dataclass
from typing import Iterable


# ---------- equation parser ----------

@dataclass(frozen=True)
class Var:
    name: str


@dataclass(frozen=True)
class App:
    left: object
    right: object


Term = object  # Var | App


def tokenize(s: str) -> list[str]:
    return re.findall(r"[A-Za-z_]\w*|[()\*=]", s)


def _parse_atom(tokens: list[str], i: int) -> tuple[Term, int]:
    if tokens[i] == "(":
        node, j = _parse_expr(tokens, i + 1)
        assert tokens[j] == ")", f"expected ), got {tokens[j]} at {j}"
        return node, j + 1
    name = tokens[i]
    assert re.match(r"^[A-Za-z_]\w*$", name), name
    return Var(name), i + 1


def _parse_expr(tokens: list[str], i: int) -> tuple[Term, int]:
    """Left-associative expr := atom ('*' atom)*."""
    left, i = _parse_atom(tokens, i)
    while i < len(tokens) and tokens[i] == "*":
        right, i = _parse_atom(tokens, i + 1)
        left = App(left, right)
    return left, i


def parse_eq(s: str) -> tuple[Term, Term]:
    """Parse 'lhs = rhs'."""
    tokens = tokenize(s.replace(" ", ""))
    eq_pos = tokens.index("=")
    lhs, j = _parse_expr(tokens[:eq_pos], 0)
    assert j == eq_pos, f"unparsed lhs tail at {j}"
    rhs, k = _parse_expr(tokens[eq_pos + 1:], 0)
    assert k == len(tokens) - eq_pos - 1, f"unparsed rhs tail at {k}"
    return lhs, rhs


def collect_vars(t: Term) -> set[str]:
    if isinstance(t, Var):
        return {t.name}
    return collect_vars(t.left) | collect_vars(t.right)


def eval_term(t: Term, table: list[list[int]], env: dict[str, int]) -> int:
    if isinstance(t, Var):
        return env[t.name]
    a = eval_term(t.left, table, env)
    b = eval_term(t.right, table, env)
    return table[a][b]


# ---------- magma enumeration ----------

def all_tables(n: int) -> Iterable[list[list[int]]]:
    """Yield every n×n Cayley table as a flat list of n*n ints in [0,n)."""
    for flat in itertools.product(range(n), repeat=n * n):
        yield [list(flat[i * n:(i + 1) * n]) for i in range(n)]


def random_tables(n: int, k: int, seed: int = 0) -> Iterable[list[list[int]]]:
    rng = random.Random(seed)
    for _ in range(k):
        yield [[rng.randrange(n) for _ in range(n)] for _ in range(n)]


def satisfies(eq: tuple[Term, Term], table: list[list[int]], n: int) -> bool:
    lhs, rhs = eq
    vars_ = sorted(collect_vars(lhs) | collect_vars(rhs))
    for assignment in itertools.product(range(n), repeat=len(vars_)):
        env = dict(zip(vars_, assignment))
        if eval_term(lhs, table, env) != eval_term(rhs, table, env):
            return False
    return True


def violates(eq: tuple[Term, Term], table: list[list[int]], n: int) -> bool:
    return not satisfies(eq, table, n)


# ---------- counterexample search ----------

@dataclass
class CounterEx:
    order: int
    table: list[list[int]]


def search_counterex(
    eq1_src: str, eq2_src: str,
    max_order: int = 4, max_samples_per_order: int = 50_000,
    timeout_per_order: float = 8.0,
) -> CounterEx | None:
    """Find a magma satisfying eq1 but not eq2. Return None if none in budget."""
    import time
    try:
        eq1 = parse_eq(eq1_src)
        eq2 = parse_eq(eq2_src)
    except Exception:
        return None

    for n in range(2, max_order + 1):
        t0 = time.time()
        total = n ** (n * n)
        gen = (all_tables(n) if total <= max_samples_per_order
               else random_tables(n, max_samples_per_order, seed=n))
        for table in gen:
            if time.time() - t0 > timeout_per_order:
                break
            if satisfies(eq1, table, n) and violates(eq2, table, n):
                return CounterEx(order=n, table=table)
    return None


# ---------- Lean emission ----------

def emit_lean_counterex(ce: CounterEx, eq1_src: str, eq2_src: str) -> str:
    """Emit Lean 4 code declaring a finite magma instance witnessing FALSE.

    Skeleton: depends on the exact mathlib4 Magma class and the upstream
    judge's expected schema (see equational-theories-lean-stage2 examples).
    """
    n = ce.order
    # Variables actually present across both equations
    try:
        lhs1, rhs1 = parse_eq(eq1_src)
        lhs2, rhs2 = parse_eq(eq2_src)
        vars_ = sorted(collect_vars(lhs1) | collect_vars(rhs1)
                       | collect_vars(lhs2) | collect_vars(rhs2))
    except Exception:
        vars_ = ["x", "y", "z", "w"]
    vs = " ".join(vars_) or "x"
    rows_match = "\n    ".join(
        f"| {i}, {j} => {ce.table[i][j]}"
        for i in range(n) for j in range(n)
    )
    return f"""-- L2: finite-magma counterexample, order {n}
-- Satisfies Eq1 ({eq1_src}) but violates Eq2 ({eq2_src})
def cex_op : Fin {n} -> Fin {n} -> Fin {n}
  {rows_match}

instance cex_magma : Magma (Fin {n}) := {{ op := cex_op }}

example : (∀ {vs} : Fin {n}, {eq1_src}) ∧ ¬ (∀ {vs} : Fin {n}, {eq2_src}) := by
  refine ⟨?_, ?_⟩
  · decide
  · decide
"""
