# Refactoring

**You hold the contract. The structure changes. The behavior does not.**

"Refactor this", "rename it", "extract it", "inline it", "kill the duplication", "move this
module", "tidy this area up". Distinct from `playbooks/shaping-the-work.md` and what follows
it, which adds behavior, and from debugging, which repairs behavior.

**A refactor that smuggles in a behavior change loses its safety net.** When the cleanup turns
up a real bug or a missing feature, cut it out and **ship the structural change against a
frozen contract first**. Redesigning is fine, but it goes under a different name to
`playbooks/shaping-the-work.md`.

1. **Pin the behavioral contract first.** Before you move any structure, write the
   characterization tests, snapshots, or equivalence tooling that capture today's behavior.
   This is what turns "I refactored it" into a verifiable claim
   (**principle-prove-it-works**). **If the area has no coverage, write the pin before you
   touch the structure. Type checks and lint are not a pin.**
2. Name the structure the code is missing (**principle-model-the-domain**): a state machine
   instead of scattered booleans, a table or registry instead of a spreading branch, a type
   instead of a repeated shape assumption. **If the shape is already clear and local, leave
   the boring code alone.** A rebuild removes a branch or an invalid state; it does not add
   indirection.
3. Name the target shape. **If you were building it from zero today**, what would the module
   layout, the types and the call graph be (**principle-foundational-thinking**,
   **principle-redesign-from-first-principles**)?
4. Subtract before you add (**principle-subtract-before-you-add**). Delete the dead weight,
   collapse the wrapper with one caller, drop the redundant validation, remove the orphaned
   references — then put the new shape in. What falls out is the smallest change that reaches
   the target shape (**principle-laziness-protocol**).
5. Move in small behavior-preserving steps, keeping the pin green at every one. When you
   rebuild an API, **migrate the callers and delete the old API in the same wave**
   (**principle-migrate-callers-then-delete-legacy-apis**). No compatibility shim, no old and
   new living side by side. **The principle carries an exception — you may keep an
   intermediate layer if you can write down who removes it and when — but this playbook does
   not**: you are rebuilding inside a radius where you can count every caller yourself, so
   there is no reason to keep one. If outside consumers depend on the old API, that is a
   migration, not a rebuild. **Always check a rename against the real files.** Uses inside
   strings, prose and back-references go missing quietly. Hand mechanical edits to the
   implementer role with a narrow scope; the main session reviews the diff.
6. Prove the behavior did not change against the real thing, not against "it compiled"
   (**principle-prove-it-works**). For a large rebuild, run an equivalence check: a script
   that diffs old and new output, a replay of a recorded baseline. **Own the verification
   yourself. Do not take "looks fine" from whoever you delegated to.**
7. Check that the change earns its seat. The measure of success is **less load on the reader**
   (**principle-minimize-reader-load**): fewer layers between question and answer, less hidden
   state, less indirection with no second consumer. **If nothing went down, revert it.**
8. Rebase into small ordered commits that tell a story: subtraction, rebuild, cleanup. Shape
   them so one revert takes back one slice (**principle-sequence-verifiable-units**). Close it
   out with `playbooks/closing-a-branch.md`. **Once a PR is the decision**, go to
   `playbooks/opening-a-pr.md`.

**What you return:** the structure that changed, the contract you pinned, the equivalence
proof, the difference in reader load, what you shipped and what you reverted. No new behavior.
