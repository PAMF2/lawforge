# Lawforge Cheatsheet

Lean 4 tactic-body patterns for SAIR Stage 2 equational implications
over magmas. Harness wraps each body inside
`def submission : Goal := by intro G _ h\n  <body>`.

Magma operator is `◇` (U+25C7), NEVER `*`. Hypothesis name is `h`.

Karpathy loop edits this file. `## PATTERN` lines auto-indexed by
`arms.arm_cheatsheet_inject` and selected by similarity to the problem.

## PATTERN: identity (eq1 ≡ eq2)

When two equations are syntactically identical, hypothesis IS the goal.

```lean
exact h
```

## PATTERN: direct rewrite

Goal follows by single rewrite using hypothesis.

```lean
intro x y z
rw [h]
```

## PATTERN: simp closure

Throw hypothesis at simp.

```lean
intro x y
simp [h]
```

## PATTERN: lambda-style (ETP idiom)

Many ETP proofs are pure lambda. Equivalent to intro + exact.

```lean
fun x y z w => h x y z w w
```

## PATTERN: have + rw chain

Build intermediate equality then rewrite. Common when single rw misses.

```lean
intro x y z
have h1 := h x y z
rw [h1]
```

## PATTERN: multi-step have ladder

Apply hypothesis to several arg permutations, chain rewrites.

```lean
intro x y z w
have h1 := h x y z w
have h2 := h y z w x
have h3 := h z w x y
rw [h1, h2, h3]
```

## PATTERN: simp_all + aesop

Goal closes after simplifying ALL hypotheses then auto-search.

```lean
intro x y z
have h1 := h x y z
simp_all
aesop
```

## PATTERN: nth_rewrite targeted

When `rw [h]` rewrites wrong occurrence. Use `nth_rewrite N [h]`.

```lean
intro x y z
nth_rewrite 1 [← h]
apply h
repeat assumption
```

## PATTERN: symm + rewrite

Symmetric direction of hypothesis.

```lean
intro x y z
symm
nth_rewrite 1 [h]
symm
apply h
repeat assumption
```

## PATTERN: calc chain (multi-step magma)

Long equation chains. Each step justified separately.

```lean
intro x y z w u
calc x ◇ (y ◇ z)
    = y ◇ ((y ◇ z) ◇ w) := by rw [h]
  _ = (y ◇ w) ◇ w       := by rw [h]
```

## PATTERN: have+rw with explicit substitution

When you need a specific instance with renamed vars.

```lean
intro x y z w u
have h1 : x ◇ y = (z ◇ w) ◇ z := h x y z w u
have h2 : y ◇ z = (x ◇ w) ◇ x := h y z x w u
rw [h1, ← h2]
```

## PATTERN: refine for partial proof

When you can sketch structure but need holes filled.

```lean
intro x y z
refine ?_
exact h x y z
```

## PATTERN: <;> combinator

Apply tactic to all subgoals.

```lean
intro x y z
constructor <;> (rw [h]; rfl)
```

## PATTERN: aesop fallback

When sequence isn't obvious, let aesop search.

```lean
intros
aesop
```

## PATTERN: counterexample emit (FALSE only)

FALSE certificates emitted by counterex.py, NOT by LLM. Use:

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

## TACTIC GLOSSARY

| Tactic | Use when |
|--------|---------|
| `intro G _ h` | wrapper does this, don't repeat |
| `intro x y z` | bind universally quantified body vars |
| `exact h x y z` | finish with explicit hypothesis instance |
| `rw [h]` | rewrite goal using h left-to-right |
| `rw [← h]` | rewrite using h right-to-left |
| `nth_rewrite N [h]` | rewrite Nth occurrence only |
| `simp [h]` | normalize with h in simp set |
| `simp_all` | simplify goal AND all hypotheses |
| `have h1 := h x y z` | bind specialization of h |
| `calc a = b := ... _ = c := ...` | multi-step equality |
| `apply h` | reduce goal via h conclusion |
| `refine ⟨..., ?_⟩` | partial constructor proof |
| `aesop` | general automated search |
| `assumption` | close by existing hypothesis |
| `repeat assumption` | finish multiple goals same way |
| `<;> tac` | apply tac to all subgoals |
| `symm` | swap LHS/RHS of equality goal |
| `rfl` | close trivially reflexive goal |
| `tauto` | propositional automation |
| `decide` | decidable propositions |
