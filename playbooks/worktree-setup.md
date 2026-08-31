# Setting up an isolated workspace

**This is the playbook for creating one.** Tearing one down is
`playbooks/worktree-cleanup.md`.
**The removal steps are not written here, so that one operation does not get two sources of truth.**

You isolate in order to **keep two or more writers off the same branch**
(**principle-separate-before-serializing-shared-state**).
Work you do alone, in order, has no reason to grow another workspace.

## 1. Check first whether you are already inside one

**Decide where you are before you create anything.** A workspace created twice leaves one copy
that nobody ever looks at again.

    git rev-parse --git-dir --git-common-dir
    git rev-parse --show-superproject-working-tree 2>/dev/null

Two different paths means you are inside an isolated workspace. **But a submodule looks exactly
the same.** If the third line returns anything, that is a submodule, not isolation. Skip this
check and you misjudge "I am already in a worktree" and dirty the main tree.

If you were already inside one, **create nothing and go to step 3.** Report which branch you
are on and where.

## 2. Do not pick the location yourself

**If the harness has a tool for creating workspaces, use it.** The tool holds the location, the
branch and the teardown in one ledger.
**Create one on the side with a bare `git worktree add` and you get a workspace the tool cannot
see** — it is in no listing, no cleanup pass touches it, and only the disk notices.

Create one by hand only when there is no tool. Even then:

- **There is more than one family of roots.** `docs/path-map.md` is the source of truth for
  which one is right. **It is not necessarily created directly under home** (Claude Code
  creates its workspaces inside the repository)
- **If it goes inside the repository, confirm the location is untracked before you create it.**
  Create it without checking and the entire contents of the workspace land in the repository

        git check-ignore -q <location> && echo ignored

  If it is not ignored, **add it to `.gitignore` and commit that first**, then create it
- **Always read the listing from `git worktree list`.** Do not assemble paths by hand
  (**principle-encode-lessons-in-structure**)

If permissions block the creation, say **you are working in the main tree instead** and carry
on. Do not fall back to no isolation silently.

## 3. Put back what does not follow you

**A fresh workspace contains nothing that is untracked.**
When `playbooks/worktree-cleanup.md` says "Git cannot bring an ignored file back", it is
because **this is exactly where they fail to get copied**. Both are looking at the same fact
from opposite sides.

So what is usually missing right after you create one:

- **Dependencies** (if the lockfile matches the main tree, borrowing from it is faster than
  reinstalling)
- **Environment files** — `.env` and its kind. Without them everything that starts up fails
- **Local DBs, generated files, caches.** A check that stands a container up will not produce
  the same result as the main tree because of what is missing here

**Checks that involve starting a container do not agree with the main tree inside an isolated
workspace.** Do not run a check you already know will disagree in the workspace — run it in the
main tree.

## 4. Get the baseline green before you start

**Take the current check results before you change anything.** Without them, you cannot tell
later whether the red is yours or was already there
(**principle-sequence-verifiable-units**).

If it is red, **report it before you touch anything.** Whether to proceed is the owner's call.

**What you return:** the workspace path and branch name, **which route created it** (tool or by
hand), what you put back, and the baseline check results (how many ran, how many failed).
