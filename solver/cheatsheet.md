# Lawforge Cheatsheet (seed)

Worked Lean 4 patterns for equational implications over magmas.

The Karpathy loop edits this file. Lines starting with `## PATTERN` are
auto-indexed by `arms.arm_cheatsheet_inject` and selected by similarity to
the problem at hand.

## PATTERN: identity-reflexive

If `Eq1` is `x = x` (always true), every `Eq2` is implied iff `Eq2` is itself
universally true. Try `rfl` first; if it fails, the implication is false.

```lean
theorem implication (G : Type*) [Magma G] (h : ∀ x : G, x = x) :
    ∀ x : G, x = x := by
  intros; rfl
```

## PATTERN: idempotent absorbs

If `Eq1 ≡ x = x*y` (right-absorbing under `*`), then `x*x = x` follows by
specializing `y := x`.

```lean
theorem implication (G : Type*) [Magma G] (h : ∀ x y : G, x = x * y) :
    ∀ x : G, x = x * x := by
  intro x; exact h x x
```

## PATTERN: small finite counterexample

When the implication is FALSE, we ship a finite magma. The counterex.py
search produces a Cayley table; the Lean proof instantiates `Fin n` as the
carrier and proves `Eq1` holds (by `decide`) and `Eq2` fails (by `decide`).

```lean
-- carrier of order 2
example : ∃ (G : Type) (_ : Magma G), (∀ x y : G, ...) ∧ ¬ (∀ x : G, ...) := by
  refine ⟨Fin 2, ⟨fun a b => ...⟩, ?_, ?_⟩
  · decide
  · decide
```

## PATTERN: aesop fallback

For straightforward derivations the model should always attempt:

```lean
theorem implication ... := by intros; aesop
```

`aesop` is allowed and very strong for simple equational rearrangements.

## PATTERN: trans / subst chain

Equational chains can be assembled by `calc` blocks:

```lean
theorem implication ... := by
  intros
  calc lhs = mid1 := by rw [h]
       _ = mid2 := by rw [h]
       _ = rhs  := by ...
```
