# Lawforge Cheatsheet (seed)

Worked Lean 4 tactic-body patterns for SAIR Stage 2 equational implications
over magmas. The harness wraps each body inside
`def submission : Goal := by intro G _ h\n  <body>`.

The Karpathy loop edits this file. Lines starting with `## PATTERN` are
auto-indexed by `arms.arm_cheatsheet_inject` and selected by similarity to
the problem at hand.

## PATTERN: identity (eq1 ≡ eq2)

When the two equations are syntactically identical, `h` already is the goal.

```lean
exact h
```

## PATTERN: direct rewrite

When `EquationRHS G` follows by a single rewrite using the hypothesis.

```lean
intro x y z
rw [h]
```

## PATTERN: simp closure

Throw the hypothesis at `simp` and let it close the goal.

```lean
intro x y
simp [h]
```

## PATTERN: aesop fallback

For algebraic chains where the exact tactic sequence isn't obvious.

```lean
intros
aesop
```

## PATTERN: existential elim with rewrite

For longer derivations: peel variables, apply hypothesis with explicit args.

```lean
intro x y z
have h1 := h x y z
exact h1
```

## PATTERN: counterexample reminder (FALSE only)

FALSE certificates are emitted by counterex.py, not by the LLM. They use:

```lean
import JudgeProblem
import JudgeDecide.DecideBang
import JudgeFinOp.MemoFinOp
open MemoFinOp

def submission : Goal := by
  let m : Magma (Fin 2) := { op := finOpTable "[[0,0],[1,1]]" }
  refine ⟨Fin 2, m, ?_⟩
  decideFin!
```
