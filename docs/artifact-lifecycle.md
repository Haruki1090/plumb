# Artifact lifecycle

## Where the artifacts go

**Do not assemble paths. Ask the tool.**

`plumb-*` are thin wrappers in `bin/`. Claude Code puts every plugin's `bin/` on PATH at
install time, so you can call them by bare name from anywhere.

```bash
plumb-path spec      # approved designs
plumb-path plan      # plans being executed
plumb-path history   # finished plans
plumb-path run       # ledgers, decision logs, briefs
plumb-path spec --mkdir   # create it if it is missing
```

The default is `<repo root>/.plumb/`. Override it with `PLUMB_ROOT`, or with `root=` in
`.plumb/config`. **Spell a path out in prose and one of the two copies goes stale**
(**principle-encode-lessons-in-structure**).

## spec and plan are not the same rank

| | What it is | Lifetime |
|---|---|---|
| **spec** | End state, acceptance criteria, why this approach, what you rejected | **The source of truth.** It is what gets approved; changing it needs re-approval. Tracked |
| **plan** | Files, signatures, **test code**, how to slice the commits | **Disposable.** Stale the moment execution starts. Tracked, but retired when it is done |

**"What has to pass for this to be done" is the spec. "Which tests, written how" is the plan.**
Same tests, two documents: the bar for judging goes in one, the implementation in the other.

`run/` is not tracked (`.plumb/.gitignore`). Ledgers and decision logs are traces of the work,
not the source of truth. **Conversely, specs and plans are always tracked.** A source of truth
that disappears with the working tree is not a source of truth.

## Retire a finished plan by freezing it

**Do not leave a completed plan in `plans/`.** In batch 1, a `docs/plan.md` frozen back at
Task 1 sat 18 lines out of date, still flying a header that said "execute these in order" —
and **anyone who came along and executed it would have rolled back every fix from that day**.

Move it to `history/` and put this at the top:

```markdown
> **This is history. Do not execute it.**
> The current source of truth is <path>. **If this document disagrees with it, the source of
> truth wins.** Do not sync this back up — syncing it revives the second source of truth.
```

**What stops the damage is the header, not the directory name.** Moving it is not enough.

## An existing `docs/superpowers/`

Repositories that have used `superpowers` still carry `docs/superpowers/specs|plans`.
**Do not migrate them wholesale.** Decide per repository. In a repository you have not
migrated, **assume the old material is under `docs/superpowers/`** when you go looking.
