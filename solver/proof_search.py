"""BFS rewrite-based proof search for magma equational implications.

Given h: l1 = r1 (universal) and goal: l2 = r2, search for a rewrite chain
that turns l2 into r2 (or vice versa) by applying h forward/backward at any
position. Pure structural search, no AC, no commutativity.

Returns True with proof trace if found; False otherwise.
"""

import time

from solver.counterex import App, Var, parse_eq


def _subterms_with_pos(t, path=()):
    yield path, t
    if isinstance(t, App):
        yield from _subterms_with_pos(t.left, path + ("L",))
        yield from _subterms_with_pos(t.right, path + ("R",))


def _replace_at(t, path, new):
    if not path:
        return new
    head, rest = path[0], path[1:]
    assert isinstance(t, App)
    if head == "L":
        return App(_replace_at(t.left, rest, new), t.right)
    return App(t.left, _replace_at(t.right, rest, new))


def _unify(pattern, term, subst):
    if isinstance(pattern, Var):
        if pattern.name in subst:
            return subst if _term_eq(subst[pattern.name], term) else None
        return {**subst, pattern.name: term}
    if isinstance(pattern, App) and isinstance(term, App):
        s = _unify(pattern.left, term.left, subst)
        if s is None:
            return None
        return _unify(pattern.right, term.right, s)
    return None


def _term_eq(a, b):
    if isinstance(a, Var) and isinstance(b, Var):
        return a.name == b.name
    if isinstance(a, App) and isinstance(b, App):
        return _term_eq(a.left, b.left) and _term_eq(a.right, b.right)
    return False


def _instantiate(t, subst):
    if isinstance(t, Var):
        return subst.get(t.name, t)
    return App(_instantiate(t.left, subst), _instantiate(t.right, subst))


def _rewrite_one(term, lhs, rhs):
    """Yield all rewrites of term applying lhs -> rhs at any subterm."""
    for path, sub in _subterms_with_pos(term):
        subst = _unify(lhs, sub, {})
        if subst is not None:
            new_sub = _instantiate(rhs, subst)
            yield _replace_at(term, path, new_sub)


def _term_key(t):
    if isinstance(t, Var):
        return ("V", t.name)
    return ("A", _term_key(t.left), _term_key(t.right))


def search_proof(
    eq1_src, eq2_src, max_depth=4, time_budget=2.0, max_visited=50000, max_frontier=5000
):
    """BFS: try to rewrite l2 -> r2 using h: l1 = r1 (forward+backward).

    Returns (True, depth) if a chain of length <= max_depth exists,
    else (False, None). Bounded by depth, time, visited size, frontier size.
    """
    try:
        l1, r1 = parse_eq(eq1_src)
        l2, r2 = parse_eq(eq2_src)
    except Exception:
        return (False, None, None)

    t0 = time.time()

    if _term_eq(l2, r2):
        return (True, 0, [])

    visited = {(_term_key(l2), _term_key(r2))}
    frontier = [(l2, r2, 0, [])]
    moves_def = [
        ("L_fwd", l1, r1, True),
        ("L_bwd", r1, l1, True),
        ("R_fwd", l1, r1, False),
        ("R_bwd", r1, l1, False),
    ]

    while frontier:
        if time.time() - t0 > time_budget:
            return (False, None, None)
        if len(visited) > max_visited:
            return (False, None, None)
        next_frontier = []
        for lhs, rhs, depth, trace in frontier:
            if len(next_frontier) > max_frontier:
                break
            if depth >= max_depth:
                continue
            for tag, pat, repl, on_lhs in moves_def:
                src = lhs if on_lhs else rhs
                for new in _rewrite_one(src, pat, repl):
                    new_lhs, new_rhs = (new, rhs) if on_lhs else (lhs, new)
                    if _term_eq(new_lhs, new_rhs):
                        return (True, depth + 1, trace + [tag])
                    k = (_term_key(new_lhs), _term_key(new_rhs))
                    if k not in visited:
                        visited.add(k)
                        next_frontier.append(
                            (new_lhs, new_rhs, depth + 1, trace + [tag])
                        )
        frontier = next_frontier

    return (False, None, None)


def emit_lean_proof(trace):
    """Emit Lean tactic body realizing the rewrite trace.

    Each step uses `first | rw [h] | rw [<-h] | rfl` shotgun since we
    don't track the exact subterm position. The judge accepts if it
    closes the goal.
    """
    if not trace:
        return "by intros; exact h"
    steps = "; ".join("(first | rw [← h] | rw [h])" for _ in trace)
    return f"by intros; {steps}; rfl"
