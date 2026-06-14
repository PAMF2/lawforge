from solver.proof_search import emit_lean_proof, search_proof


def test_syntactic_match():
    # x = y is provable from h: x = y in 1 step via L_fwd
    ok, depth, _ = search_proof("x = y", "x = y")
    assert ok and depth <= 1


def test_direct_substitution():
    ok, depth, _ = search_proof("x = y*y", "x*z = (y*y)*z")
    assert ok and depth == 1


def test_two_step_chain():
    ok, depth, _ = search_proof("x*x = x", "x*x*x = x")
    assert ok and depth <= 2


def test_emit_lean_proof_empty():
    assert "exact h" in emit_lean_proof([])


def test_emit_lean_proof_steps():
    out = emit_lean_proof(["L_fwd", "R_bwd"])
    assert "rw" in out and "rfl" in out


def test_depth_zero_budget_unprovable():
    # tiny budget forces termination without finding any rewrite
    ok, depth, trace = search_proof("a*b = c", "(a*b)*c = d", max_depth=0, time_budget=0.1)
    assert not ok and depth is None and trace is None
