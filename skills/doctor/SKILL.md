---
name: doctor
description: Check whether the environment plumb claims still exists on this machine. Use when asked to "run doctor", "check plumb's health", "is the harness broken", and after you change the environment, when you come back to plumb after a while, or at the end of a batch.
---

# doctor

```bash
plumb-doctor
```

**The script holds the judgment. This document holds only when to run it, and what to suspect when it fails.**
Copy the steps here and one copy goes stale (**principle-encode-lessons-in-structure**).

## Why it is needed

plumb is **a bundle of documents that assert facts about the environment**:
which command exists, which skill exists, which path exists.

**Unlike code, those assertions say nothing when they break.**
A document happily survives the disappearance of what it points at, and sends the next reader somewhere that is not there.

Two of them turned up in a single session on 2026-08-29.

```
~/.<tool>-worktrees/    a carry-over note named it; the path did not exist
the pr-review skill     six agents introduced themselves as "called from stage N of the
                        pr-review skill", but that skill had been moved aside and was not live
```

**Neither shows up under grep or lint.** "Something that should be there is not"
is only knowable by going and checking that it is. So it became a tool (**principle-build-the-lever**).

## When to run it

- **At the end of a batch.** As part of the termination condition.
- **After you change the environment.** A skill added, removed or moved aside; an extension installed; a CLI swapped.
- **When you come back to plumb after a while.** When you do not know what moved since last time.
- **When you followed a pointer out of the `plumb` index and it was not there.** Do not fix that one item; look at the whole first.

## Reading a failure

| Where it failed | What to suspect |
|---|---|
| Inside (cross-cutting rules) | an edit to plumb itself. Run `plumb-check` directly and read what it says |
| Inside (script behavior) | selftest.sh's own premises may be broken. Run `plumb-selftest` directly and read what it says |
| Routing targets | PATH and the extension install. The premises of `docs/role-map.md` have collapsed |
| Bundled agents | one of `agents/` was deleted or renamed. Cross-check the names `skills/pr-review/SKILL.md` calls against what is actually in `agents/` |
| The agents on your side (your own copy) | the same cause, showing up on your own `~/.claude/agents/` side. Either put the skill back, or fix the agent's description |
| Paths | `docs/path-map.md`'s claim is out of date. **Measure first, then fix the table. Do not rewrite it from a guess** |
| Loading | check the plugin list for the selected runtime in a new session; use the runtime adapter for command mapping |

**Do not bury a failing item.** Loosening the expectation to get doctor to pass is
killing the verifier (**principle-prove-it-works**).
If you cannot fix it, write "this is broken right now" into `docs/` and leave it there.
