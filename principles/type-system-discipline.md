---
name: principle-type-system-discipline
origin: plumb
description: "Make invalid states unrepresentable: brand your types so values with different meanings cannot be swapped, parse external data at the boundary, do not lie to the compiler, let the checker exhaust your variants, and derive a shape from its one source of truth. Use when designing types, reading a function signature, or when asked \"should this be a union\", \"is this cast safe\", or \"how strict should these types be\"."
---

# Type system discipline

**The type checker is the only reviewer that runs for free, every time.**
Human review misses things, gets tired, and does nothing for whoever picks the code up
next. **Only what you made the types prove is still working next month.**

**Why this is hard to keep.** A loose type never once hurts the person who wrote it. The
bill arrives as the question "can this combination actually occur", and **it is charged to
whoever reads the code later and to the production system that fell over.** At the moment
of writing, "this is fine as it stands" is always true. Self-restraint will not hold this.
**Catch it by the signs.**

## The signs, and what each one needs

- **The combinations of fields split into valid and invalid.** Hold "approved" and "sent
  back" as two separate booleans and a state with both set is constructible. **Make that
  state unconstructible**: hold one value for the state and derive both from it
- **You are imposing the constraint after the fact.** Do not narrow it with a check;
  **build it so it holds by construction.** A weighted candidate set is a sequence of
  candidate-and-weight pairs, not "a sequence of candidates and a sequence of weights, plus
  a promise that the lengths match"
- **Values with different meanings sit side by side in the same bare type.** Arguments you
  can swap and still compile get swapped eventually. Give the bare type a name of its own,
  and **validate once where it is constructed, then trust it from there**
- **Something from outside is being handled as an inside type as it arrived.** Outside has
  no type until you parse it. Where those checks live belongs to
  **principle-boundary-discipline**
- **There is a cast, or an assertion that this case can never arrive.** That is a written
  record of lying to the checker. If you cannot prove it, either prove it (validate,
  narrow, reshape the type) or **admit the danger is still there.** The line you swallowed
  is the cause field of an incident report someone writes later
- **Adding a variant does not break the compile.** Exhaustiveness is the checker's work,
  not human attention. Written so it does not break, the next person has no way to notice
- **The same shape is hand-written in two places.** If the source of truth for the shape is
  somewhere else, derive it from there (**principle-encode-lessons-in-structure**). A shape
  copied by hand always drifts

## Do not make it stronger than it needs to be

**Strengthen a type only when a place shows up whose answer exists only at runtime.** Lift
the check or the assertion that appeared there into the type, and **stop right there.** A
type made precise while nothing was failing buys nothing but friction in reuse and
ceremony at the call site. The number of entries in a ledger is 0 when it is empty, so take
an ordinary sequence. An operation that returns the most recent entry has no answer when
the ledger is empty, so require a non-empty one. **That difference is the entire reason to
strengthen a type.**

## How to tell afterwards

- **Did you want to explain in a comment when this combination of fields is valid?** —
  the shape is loose
- **Which boundary did the value inside this coercion come from?** — trace it back and
  validate it there
- **When someone adds a variant next month, will the next person be told where to fix it?**
- **What does the type you are about to strengthen stop from failing?** — if you cannot
  answer, put it back

The names of the tools differ per language. **What this principle looks at is not the name;
it is what you made the checker prove.**
