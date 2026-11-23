# Properties tests cannot reach

**You hold one promise the system makes, the tool chosen to check it, and the proof that the tool can
fail.**

Example-based tests check the cases somebody thought of. Some promises are about the cases nobody did:
an ordering or interleaving (races, retries, crash recovery), an invariant over every reachable state,
a protocol between components, a boundary over a whole input space. For those, a green suite is
silence, not evidence. **This playbook picks one such promise and builds a check that can reach it.**
Ordinary tests are `playbooks/writing-tests.md`; a single defect in hand is `playbooks/fixing-a-bug.md`.

## 1. Enter only on one of two signals

- **A defect class keeps returning that the tests keep missing.** In `docs/failure-taxonomy.md` that is
  **C01** (a boundary, race or state transition was not handled: empty, first, last, concurrent,
  retried, out of order), often paired with **C08** (the tests do not detect the regression they exist
  for). Count the records: two of the same shape is a class, not bad luck.
- **One promise whose breach is the most harmful thing the system can do.** Lost writes, a double
  charge, data shown to the wrong person. One exists even if no defect has landed yet.

Without either, write tests and stop here.

## 2. Pick ONE promise

**Choose the one that is the most harmful if broken and the least reachable by tests.** Two promises
make two projects, and the second gets the leftover effort.

Write it as **one sentence that a counterexample could contradict**: "A job that was cancelled never
runs, whatever order the cancel and the submit response arrive in." "No sequence of retries leaves
two rows for one order." If you cannot name what a counterexample would look like, it is a wish, not a
promise; sharpen it before you pick a tool.

## 3. The question chooses the tool, never the reverse

| The promise is about | Tool |
|---|---|
| An input space (parsing, ranges, encodings, round trips) | Property-based or generated tests |
| Interleavings or a state machine | A model checker, or an exhaustive enumeration of a small scope (every ordering of N events over M actors) |
| Timing and failure (crashes, timeouts, partial writes) | A stress harness with fault injection |
| An invalid state that can be made impossible | A type-level encoding (**principle-type-system-discipline**) |

**Use what the repository's ecosystem already carries.** If the project has a generator library or a
model checker, use it. Do not add a runtime, a language or a dependency the project does not already
have; a check nobody can run in CI will be deleted. If nothing fits, say so and return `blocked`
(step 8).

## 4. Keep the model or property small, and written from the code

**Write it from what the code does, not from what the design document says.** A model of the intended
design agrees with the design and tells you nothing about the code.

- State only the part the promise needs: the actors, the events, the state variables that decide it.
- **Read the real code path first** and take its actual ordering, retries and error branches. The
  guard you assumed was there is often not.
- A model that needs pages of its own is checking itself. Cut it down or split the promise.

## 5. See it fail first

**Break the thing on purpose and watch the check report it** (**principle-prove-it-works**). Use a
mutated variant of the model, or of the code: remove the lock, drop the idempotency key, reorder two
steps, widen the boundary by one.

- Keep the mutation and the failing output. The output is the evidence, and the counterexample it
  prints should read as a real sequence of events.
- **If the mutated check still passes, the check is the broken part.** Do not go on until it fails.
- A check that has only ever passed proves nothing.

## 6. Record the coverage where the next reader finds it

Put it next to the check, in a header comment or a short file beside it, not in a chat or a PR body.

- **Which code it covers**: the files and functions the model stands for.
- **The commit it was last confirmed in sync with.**
- **What it does not cover.** The scope you cut, the actors you left out. This line is the one that
  stops the next reader from trusting it past its reach.

## 7. When it fails later, decide which of two it is

**Replay the counterexample against the real code.** Do not argue from the model.

- **The real code does it too: the code is wrong.** This is a bug. Hand the counterexample to
  `playbooks/fixing-a-bug.md` as the repro; it is already a machine-judged one.
- **The real code does not do it: the model drifted.** Update the model to match what the code now
  does, and say what changed.

**Never edit the model or the property merely to make it pass.** That is loosening the verifier, and
the area is unobserved from then on.

## 8. The result is one of four

| Result | Meaning |
|---|---|
| **in sync** | The check ran against the current code and held, and the coverage record is current |
| **updated** | The model drifted; it was changed to match the code, and the change is described |
| **bug** | The counterexample reproduces on the real code; it is handed to the fix |
| **blocked** | No tool the repository carries can reach the promise, or the check cannot be made to fail |

**What you return:** the promise (one sentence), the tool and why it fits, the mutation that made the
check fail and its output, the coverage record, and the result.
