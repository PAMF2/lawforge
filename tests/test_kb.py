from solver.kb import proves


def test_one_step():
    assert proves("x*x = x", "x*x*x = x")


def test_false_no_proof():
    assert not proves("x*y = (z*w)*z", "x = ((y*(y*y))*z)*z")


def test_two_step_chain():
    # x*x -> x rule normalizes x*(x*x) -> x*x -> x
    assert proves("x*x = x", "x*(x*x) = x")


def test_budget_termination():
    assert proves("x = x", "x = x")
