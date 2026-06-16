"""Structured counterexample database.

Random-sample search at order 4 covers ~0.003% of 4-element magmas. Most
of the false implications that survive that sweep need magmas with
specific algebraic structure. This module enumerates a small zoo of
well-known constructions and tries each against the (h, g) pair.

The zoo:
  - Constant magmas (a*b = c for fixed c)
  - Left projection (a*b = a)
  - Right projection (a*b = b)
  - Cyclic groups Z_n (a*b = (a+b) mod n)
  - Modular multiplication (a*b = (a*b) mod n)
  - XOR magmas at order 4
  - Klein four-group, Z_2 x Z_2
  - Idempotent magmas matching specific rules
  - Famous Latin squares (Steiner, quasigroups)
"""

from itertools import product

from solver.counterex import collect_vars, parse_eq, satisfies, violates


def _const(n, c):
    return [[c] * n for _ in range(n)]


def _left_proj(n):
    return [[i for _ in range(n)] for i in range(n)]


def _right_proj(n):
    return [list(range(n)) for _ in range(n)]


def _cyclic_add(n):
    return [[(i + j) % n for j in range(n)] for i in range(n)]


def _modular_mul(n):
    return [[(i * j) % n for j in range(n)] for i in range(n)]


def _xor(n):
    return [[i ^ j for j in range(n)] for i in range(n)]


def _diff(n):
    return [[(i - j) % n for j in range(n)] for i in range(n)]


def _klein4():
    return [
        [0, 1, 2, 3],
        [1, 0, 3, 2],
        [2, 3, 0, 1],
        [3, 2, 1, 0],
    ]


def _idempotent_zoo(n):
    """Idempotent magmas: a*a = a. Generate by fixing diagonal then varying
    off-diagonal via simple rules."""
    rules = [
        lambda i, j: i if i != j else i,
        lambda i, j: j if i != j else i,
        lambda i, j: (i + j) % n,
        lambda i, j: min(i, j),
        lambda i, j: max(i, j),
        lambda i, j: (i * j) % n if (i * j) % n != 0 else (i + j) % n,
    ]
    return [[[rule(i, j) for j in range(n)] for i in range(n)] for rule in rules]


def _transpose(t):
    n = len(t)
    return [[t[j][i] for j in range(n)] for i in range(n)]


def _latin_squares_4():
    """Generate all Latin squares of order 4 (576 total)."""
    rows = list(range(4))
    from itertools import permutations

    squares = []
    for r1 in permutations(rows):
        for r2 in permutations(rows):
            if any(r1[i] == r2[i] for i in range(4)):
                continue
            for r3 in permutations(rows):
                if any(r3[i] in (r1[i], r2[i]) for i in range(4)):
                    continue
                for r4 in permutations(rows):
                    if any(r4[i] in (r1[i], r2[i], r3[i]) for i in range(4)):
                        continue
                    squares.append([list(r1), list(r2), list(r3), list(r4)])
    return squares


def _s3_left():
    """Symmetric group S_3 = order 6 Cayley table (left compose).
    Elements: e=0, (01)=1, (02)=2, (12)=3, (012)=4, (021)=5."""
    return [
        [0, 1, 2, 3, 4, 5],
        [1, 0, 4, 5, 2, 3],
        [2, 5, 0, 4, 3, 1],
        [3, 4, 5, 0, 1, 2],
        [4, 3, 1, 2, 5, 0],
        [5, 2, 3, 1, 0, 4],
    ]


def _dihedral4():
    """D_4 = order 8 dihedral group."""
    n = 8
    return [
        [(i + j) % n if j < 4 else (i - j + 8) % n for j in range(n)] for i in range(n)
    ]


def _absorb_zero(n):
    """0 absorbs: 0*x = x*0 = 0, else a*b = a."""
    t = [[0 if i == 0 or j == 0 else i for j in range(n)] for i in range(n)]
    return t


def _flip(n):
    """a*b = (n-1) - a."""
    return [[(n - 1) - i for _ in range(n)] for i in range(n)]


def _double(n):
    """a*b = (2*a) mod n."""
    return [[(2 * i) % n for _ in range(n)] for i in range(n)]


def _double_plus(n):
    """a*b = (a + 2*b) mod n."""
    return [[(i + 2 * j) % n for j in range(n)] for i in range(n)]


def _square_mul(n):
    """a*b = (a*a + b) mod n (idempotent on squares)."""
    return [[((i * i) + j) % n for j in range(n)] for i in range(n)]


def _max_op(n):
    return [[max(i, j) for j in range(n)] for i in range(n)]


def _min_op(n):
    return [[min(i, j) for j in range(n)] for i in range(n)]


def _gcd_op(n):
    from math import gcd

    return [[gcd(i, j) if (i or j) else 0 for j in range(n)] for i in range(n)]


def _lcm_op(n):
    from math import gcd

    def lcm(a, b):
        return 0 if a == 0 or b == 0 else (a * b) // gcd(a, b)

    return [[lcm(i, j) % n for j in range(n)] for i in range(n)]


def _quat8():
    """Quaternion group Q_8 = {1, -1, i, -i, j, -j, k, -k}.
    Indexed 0..7 as: 1, -1, i, -i, j, -j, k, -k."""
    # Multiplication table for quaternion group
    t = [
        [0, 1, 2, 3, 4, 5, 6, 7],
        [1, 0, 3, 2, 5, 4, 7, 6],
        [2, 3, 1, 0, 6, 7, 5, 4],
        [3, 2, 0, 1, 7, 6, 4, 5],
        [4, 5, 7, 6, 1, 0, 2, 3],
        [5, 4, 6, 7, 0, 1, 3, 2],
        [6, 7, 4, 5, 3, 2, 1, 0],
        [7, 6, 5, 4, 2, 3, 0, 1],
    ]
    return t


def _self_inverse(n):
    """a*b = (-a-b) mod n (a kind of inversion magma)."""
    return [[(-i - j) % n for j in range(n)] for i in range(n)]


def _shift_left(n, k):
    """a*b = (a + k) mod n (constant shift, ignores b)."""
    return [[(i + k) % n for _ in range(n)] for i in range(n)]


def _zoo():
    yield from (_const(2, c) for c in range(2))
    yield from (_const(3, c) for c in range(3))
    yield from (_const(4, c) for c in range(4))
    yield from (_const(5, c) for c in range(5))
    yield from (_const(6, c) for c in range(6))
    for n in (2, 3, 4, 5, 6, 7, 8, 9):
        yield _left_proj(n)
        yield _right_proj(n)
        yield _cyclic_add(n)
        yield _modular_mul(n)
        yield _diff(n)
        yield _flip(n)
        yield _double(n)
        yield _double_plus(n)
        yield _square_mul(n)
        yield _absorb_zero(n)
        yield _max_op(n)
        yield _min_op(n)
        yield _gcd_op(n)
        yield _lcm_op(n)
        yield _self_inverse(n)
        for k in range(1, n):
            yield _shift_left(n, k)
    yield _xor(2)
    yield _xor(4)
    yield _klein4()
    yield _s3_left()
    yield _transpose(_s3_left())
    yield _dihedral4()
    yield _quat8()
    yield _transpose(_quat8())
    for n in (3, 4, 5):
        for t in _idempotent_zoo(n):
            yield t
    # all order-2 magmas (16 brute)
    for a, b, c, d in product(range(2), repeat=4):
        yield [[a, b], [c, d]]
    # all Latin squares order 4 (576)
    for t in _latin_squares_4():
        yield t
        yield _transpose(t)


def search_structured(eq1_src, eq2_src):
    """Try each structured magma. Return (table, n) if it's a counterexample."""
    try:
        eq1 = parse_eq(eq1_src)
        eq2 = parse_eq(eq2_src)
    except Exception:
        return None
    v1 = sorted(collect_vars(eq1[0]) | collect_vars(eq1[1]))
    v2 = sorted(collect_vars(eq2[0]) | collect_vars(eq2[1]))
    for table in _zoo():
        n = len(table)
        if satisfies(eq1, table, n, v1) and violates(eq2, table, n, v2):
            return table, n
    return None
