"""Minimal Knuth-Bendix-style equational prover for magma implications.

Builds rewrite system from h: l1 = r1 by:
  1. Orienting via term-size ordering (heavier -> lighter).
  2. Computing critical pairs (overlap analysis) up to depth K.
  3. Normalizing each derived equation to add only non-redundant rules.

To decide goal l2 = r2:
  - Normalize both sides using the final rule set.
  - Return True if they reduce to the same term.

Pure structural rewriting; no AC, no commutativity baked in.
"""

import time
from collections import deque

from solver.counterex import App, Var, parse_eq


def _size(t):
    if isinstance(t, Var):
        return 1
    return 1 + _size(t.left) + _size(t.right)


def _term_eq(a, b):
    if isinstance(a, Var) and isinstance(b, Var):
        return a.name == b.name
    if isinstance(a, App) and isinstance(b, App):
        return _term_eq(a.left, b.left) and _term_eq(a.right, b.right)
    return False


def _key(t):
    if isinstance(t, Var):
        return ("V", t.name)
    return ("A", _key(t.left), _key(t.right))


def _vars_of(t):
    if isinstance(t, Var):
        return {t.name}
    return _vars_of(t.left) | _vars_of(t.right)


def _unify(p, q, subst):
    if isinstance(p, Var):
        if p.name in subst:
            return subst if _term_eq(subst[p.name], q) else None
        return {**subst, p.name: q}
    if isinstance(q, Var):
        if q.name in subst:
            return subst if _term_eq(subst[q.name], p) else None
        return {**subst, q.name: p}
    if isinstance(p, App) and isinstance(q, App):
        s = _unify(p.left, q.left, subst)
        if s is None:
            return None
        return _unify(p.right, q.right, s)
    return None


def _match(pat, term, subst):
    if isinstance(pat, Var):
        if pat.name in subst:
            return subst if _term_eq(subst[pat.name], term) else None
        return {**subst, pat.name: term}
    if isinstance(pat, App) and isinstance(term, App):
        s = _match(pat.left, term.left, subst)
        if s is None:
            return None
        return _match(pat.right, term.right, s)
    return None


def _instantiate(t, subst):
    if isinstance(t, Var):
        return subst.get(t.name, t)
    return App(_instantiate(t.left, subst), _instantiate(t.right, subst))


def _positions(t, path=()):
    yield path, t
    if isinstance(t, App):
        yield from _positions(t.left, path + ("L",))
        yield from _positions(t.right, path + ("R",))


def _replace_at(t, path, new):
    if not path:
        return new
    head = path[0]
    if head == "L":
        return App(_replace_at(t.left, path[1:], new), t.right)
    return App(t.left, _replace_at(t.right, path[1:], new))


def _rewrite_step(term, rules):
    """Apply leftmost-outermost matching rule. Returns new term or None."""
    for path, sub in _positions(term):
        for lhs, rhs in rules:
            s = _match(lhs, sub, {})
            if s is not None:
                return _replace_at(term, path, _instantiate(rhs, s))
    return None


def normalize(term, rules, max_steps=200):
    cur = term
    for _ in range(max_steps):
        nxt = _rewrite_step(cur, rules)
        if nxt is None:
            return cur
        cur = nxt
    return cur


def _rename_vars(t, suffix):
    if isinstance(t, Var):
        return Var(t.name + suffix)
    return App(_rename_vars(t.left, suffix), _rename_vars(t.right, suffix))


def _critical_pairs(r1, r2):
    """Compute critical pairs: unify subterms of r1.lhs with r2.lhs."""
    l1, r1_rhs = r1
    l2, r2_rhs = r2
    l2_renamed = _rename_vars(l2, "_")
    r2_renamed = _rename_vars(r2_rhs, "_")
    for path, sub in _positions(l1):
        if isinstance(sub, Var):
            continue
        s = _unify(sub, l2_renamed, {})
        if s is None:
            continue
        inst_l1 = _instantiate(l1, s)
        rhs1 = _instantiate(r1_rhs, s)
        rhs2 = _replace_at(inst_l1, path, _instantiate(r2_renamed, s))
        if not _term_eq(rhs1, rhs2):
            yield (rhs1, rhs2)


def _orient(s, t):
    """Pick orientation by term size (bigger -> smaller). None if equal size."""
    ss, ts = _size(s), _size(t)
    if ss > ts:
        return (s, t)
    if ts > ss:
        return (t, s)
    return None


def complete(eq1_src, max_pairs=500, max_rules=80, time_budget=2.0):
    """Run bounded KB-style completion from h: l1 = r1.

    Returns list of rewrite rules. Always includes h's two orientations
    as a fallback so caller can attempt normalization even if no completion
    iterations succeed.
    """
    l1, r1 = parse_eq(eq1_src)
    rules = []
    seen_rule_keys = set()

    def add(lhs, rhs):
        if _term_eq(lhs, rhs):
            return False
        if isinstance(lhs, Var):
            return False
        rhs_vars = _vars_of(rhs)
        lhs_vars = _vars_of(lhs)
        if not rhs_vars.issubset(lhs_vars):
            return False
        k = (_key(lhs), _key(rhs))
        if k in seen_rule_keys:
            return False
        seen_rule_keys.add(k)
        rules.append((lhs, rhs))
        return True

    pair = _orient(l1, r1)
    if pair is not None:
        add(pair[0], pair[1])
    else:
        add(l1, r1)
        add(r1, l1)

    t0 = time.time()
    pairs_done = 0
    queue = deque(range(len(rules)))
    seen_indices = set(queue)
    while queue and pairs_done < max_pairs and len(rules) < max_rules:
        if time.time() - t0 > time_budget:
            break
        i = queue.popleft()
        for j in range(len(rules)):
            if pairs_done >= max_pairs:
                break
            for new_s, new_t in _critical_pairs(rules[i], rules[j]):
                pairs_done += 1
                s_norm = normalize(new_s, rules, max_steps=50)
                t_norm = normalize(new_t, rules, max_steps=50)
                if _term_eq(s_norm, t_norm):
                    continue
                pair = _orient(s_norm, t_norm)
                if pair is None:
                    continue
                if add(pair[0], pair[1]):
                    idx = len(rules) - 1
                    if idx not in seen_indices:
                        seen_indices.add(idx)
                        queue.append(idx)
    return rules


def proves(eq1_src, eq2_src, time_budget=2.0, max_pairs=500, max_rules=80):
    """Decide whether h: eq1 implies goal: eq2 via KB completion.

    Returns True if both sides of eq2 normalize to the same term in the
    completed rewrite system; False otherwise.
    """
    try:
        rules = complete(
            eq1_src,
            max_pairs=max_pairs,
            max_rules=max_rules,
            time_budget=time_budget,
        )
        l2, r2 = parse_eq(eq2_src)
    except Exception:
        return False
    l2_n = normalize(l2, rules)
    r2_n = normalize(r2, rules)
    return _term_eq(l2_n, r2_n)
