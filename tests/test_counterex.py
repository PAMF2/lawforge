from solver.counterex import (
    App,
    Var,
    collect_vars,
    eval_term,
    parse_eq,
    satisfies,
    search_counterex,
    violates,
)


def test_parse_reflexive():
    lhs, rhs = parse_eq("x = x")
    assert isinstance(lhs, Var) and isinstance(rhs, Var)
    assert lhs.name == rhs.name == "x"


def test_parse_product():
    lhs, rhs = parse_eq("x = (x*y)")
    assert isinstance(rhs, App)
    assert rhs.left.name == "x"
    assert rhs.right.name == "y"


def test_eval_const_table():
    lhs, rhs = parse_eq("x = (x*y)")
    # 2x2 table where * collapses to identity on x
    table = [[0, 0], [0, 1]]
    # at x=0,y=0: x=0, x*y=0  -> equal
    assert eval_term(lhs, table, {"x": 0, "y": 0}) == eval_term(
        rhs, table, {"x": 0, "y": 0}
    )


def test_satisfies_trivial_reflexive():
    eq = parse_eq("x = x")
    assert satisfies(eq, [[0, 0], [0, 0]], 2)
    assert not violates(eq, [[0, 0], [0, 0]], 2)


def test_search_finds_obvious_counterex():
    # Eq1: x = x  (trivially true everywhere)
    # Eq2: x = (x*y)  (forces right-absorbtion; fails in most magmas)
    ce = search_counterex("x = x", "x = (x*y)", max_order=2)
    assert ce is not None
    assert ce.order >= 2


def test_collect_vars():
    lhs, rhs = parse_eq("x = (x*y)")
    assert collect_vars(lhs) == {"x"}
    assert collect_vars(rhs) == {"x", "y"}
