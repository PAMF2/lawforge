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

import itertools
import json
import random
import re
from dataclasses import dataclass
from typing import Iterable


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
    rhs, k = _parse_expr(tokens[eq_pos + 1 :], 0)
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


def all_tables(n: int) -> Iterable[list[list[int]]]:
    """Yield every n×n Cayley table as a flat list of n*n ints in [0,n)."""
    for flat in itertools.product(range(n), repeat=n * n):
        yield [list(flat[i * n : (i + 1) * n]) for i in range(n)]


def random_tables(n: int, k: int, seed: int = 0) -> Iterable[list[list[int]]]:
    rng = random.Random(seed)
    for _ in range(k):
        yield [[rng.randrange(n) for _ in range(n)] for _ in range(n)]


DEFAULT_VARS = ["x", "y", "z", "w"]


def vars_of(*eq_sources: str) -> list[str]:
    """Union of free vars across any number of equation source strings.
    Falls back to DEFAULT_VARS on parse error."""
    try:
        seen: set[str] = set()
        for s in eq_sources:
            lhs, rhs = parse_eq(s)
            seen |= collect_vars(lhs)
            seen |= collect_vars(rhs)
        return sorted(seen)
    except Exception:
        return list(DEFAULT_VARS)


def satisfies(
    eq: tuple[Term, Term],
    table: list[list[int]],
    n: int,
    vars_: list[str] | None = None,
) -> bool:
    lhs, rhs = eq
    if vars_ is None:
        vars_ = sorted(collect_vars(lhs) | collect_vars(rhs))
    for assignment in itertools.product(range(n), repeat=len(vars_)):
        env = dict(zip(vars_, assignment))
        if eval_term(lhs, table, env) != eval_term(rhs, table, env):
            return False
    return True


def violates(
    eq: tuple[Term, Term],
    table: list[list[int]],
    n: int,
    vars_: list[str] | None = None,
) -> bool:
    return not satisfies(eq, table, n, vars_)


@dataclass
class CounterEx:
    order: int
    table: list[list[int]]


import hashlib  # noqa: E402

_CACHE_DIR = (
    __import__("pathlib").Path(__file__).resolve().parent.parent / "proofs" / "ce_cache"
)


def _ce_cache_key(eq1_src: str, eq2_src: str) -> str:
    return hashlib.sha1(
        (eq1_src.replace(" ", "") + "|" + eq2_src.replace(" ", "")).encode()
    ).hexdigest()[:16]


def _ce_cache_load(key: str) -> "CounterEx | None":
    p = _CACHE_DIR / f"{key}.json"
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    return CounterEx(order=int(d["order"]), table=d["table"])


def _ce_cache_store(key: str, ce: "CounterEx") -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (_CACHE_DIR / f"{key}.json").write_text(
        json.dumps({"order": ce.order, "table": ce.table})
    )


def search_counterex(
    eq1_src: str,
    eq2_src: str,
    max_order: int = 4,
    max_samples_per_order: int = 100_000,
    timeout_per_order: float = 15.0,
) -> CounterEx | None:
    """Find a magma satisfying eq1 but not eq2. Return None if none in budget.

    Cached per (eq1, eq2) hash in proofs/ce_cache/. Subsequent calls on the
    same problem return instantly; saves ~5-30s per FALSE re-eval across gens.
    """
    import time

    cache_key = _ce_cache_key(eq1_src, eq2_src)
    cached = _ce_cache_load(cache_key)
    if cached is not None:
        return cached

    try:
        eq1 = parse_eq(eq1_src)
        eq2 = parse_eq(eq2_src)
    except Exception:
        return None

    v1 = sorted(collect_vars(eq1[0]) | collect_vars(eq1[1]))
    v2 = sorted(collect_vars(eq2[0]) | collect_vars(eq2[1]))
    for n in range(2, max_order + 1):
        t0 = time.time()
        total = n ** (n * n)
        gen = (
            all_tables(n)
            if total <= max_samples_per_order
            else random_tables(n, max_samples_per_order, seed=n)
        )
        for table in gen:
            if time.time() - t0 > timeout_per_order:
                break
            if satisfies(eq1, table, n, v1) and violates(eq2, table, n, v2):
                ce = CounterEx(order=n, table=table)
                _ce_cache_store(cache_key, ce)
                return ce
    return None


def emit_lean_counterex(ce: CounterEx, eq1_src: str, eq2_src: str) -> str:
    """Emit Lean 4 FALSE certificate matching upstream `def submission : Goal`
    contract (Stage 2 baseline solver shape — see equational-theories-lean-
    stage2 examples/solo/demos/baseline/solver.py:make_false_code).

    Goal expands to ∃ (G : Type) (_ : Magma G), EquationLHS G ∧ ¬EquationRHS G.
    We provide Fin n with the searched Cayley table as the witness magma and
    discharge both conjuncts via `decideFin!` (judge-provided macro).
    """
    n = ce.order
    # finOpTable strips non-digits and reads as flat list; nested or flat both
    # work but upstream baseline uses nested `[[r0c0,r0c1],[r1c0,r1c1]]`.
    # Stays valid for n <= 9 (single-digit cells); we never search higher.
    table_str = json.dumps(ce.table)
    return (
        "import JudgeProblem\n"
        "import JudgeDecide.DecideBang\n"
        "import JudgeFinOp.MemoFinOp\n"
        "open MemoFinOp\n\n"
        "def submission : Goal := by\n"
        f"  let m : Magma (Fin {n}) := {{\n"
        f'    op := finOpTable "{table_str}"\n'
        f"  }}\n"
        f"  refine ⟨Fin {n}, m, ?_⟩\n"
        f"  decideFin!\n"
    )
