# Cleaning up worktrees and disk

**You hold the disk and the safety catch.** Prune the worktrees that are merged or abandoned
and get the space back. **Deletion is irreversible, so every step here protects "in use" and
"uncommitted work".**

1. Record and take inventory. Take `df -h /` first.
   **Always read the list of worktrees from `git worktree list`. Do not assemble paths by hand.**
   This machine has more than one family of roots (the list in `docs/path-map.md` is the source
   of truth). A hand-typed `myrepo-worktrees/x` misses the same name living under a different
   root (**principle-encode-lessons-in-structure**).
   ```bash
   plumb-worktree-audit   # read-only. It deletes nothing
   ```

   It classifies by size, last modified, merge state, whether anything is uncommitted,
   **ignored files that cannot be recovered**, and PR state, then lists "what cannot be brought
   back" per worktree at the end (**principle-build-the-lever**). Things that can be rebuilt,
   like `__pycache__` and `node_modules`, are already excluded — **without the exclusion it says
   nothing but "check this" every time, and a real `.env` gets lost in the noise.**
   The scan takes tens of seconds, so run it in a pane (`pane.driver`; unset: run it in the
   foreground).
2. **The classification is advice, not permission.** What is actually open and what is actually
   pinned right now is the real input (**principle-prove-it-works**). Ask the owner for that
   set and cross-check it against every candidate. A worktree the tool marked "safe" has turned
   out to be pinned. **The pinned side wins.**
3. Confirm use before you delete. For anything doubtful, read the most recent session that
   touched it and have it report whether the work is in progress or pinned
   (**principle-guard-the-context-window** — traces are bulky).
   **A running session may have scattered children across sibling worktrees.**
   It is in use even when the name is nowhere on screen.
4. **Stop in front of irreversible loss.** Uncommitted edits under tracking, untracked files,
   **and ignored files too — all of it falls under this gate.**

   ```bash
   git -C <path> status --porcelain -uall        # everything, untracked included
   git -C <path> status --porcelain --ignored    # ignored files too
   ```

   **A `.env`, a local DB, notes that were never generated from anything, ignored artifacts:
   Git cannot restore any of them.** A clean worktree comes back from its branch; these do not
   come back at all. List what is there and ask for a decision. **You may proceed only when it
   is clean, merged and unused.**
5. Prune the set you confirmed. **Fire the first shot without `--force`.**

   ```bash
   git worktree remove <path>
   ```

   **A refusal is the signal that the safety catch worked.** Do not push through with
   `--force`. Show the output of the two commands in step 4 and **ask the owner to decide.**
   This is the same rule as `playbooks/closing-a-branch.md`, and it is matched here **so that
   one operation does not get two sources of truth.**
   Once approved: `--force`, then `rm -rf` if the directory survives, then `git worktree prune`.
   **The branch refs remain, so no commits are lost.** Confirm with `df -h /` and a fresh
   listing.
6. On to the next place to reclaim from. **Do not write down a fixed list** — names go stale.
   Measure, largest first, then go after them.

   ```bash
   du -sh ~/Library/Caches/* ~/Library/Application\ Support/* 2>/dev/null | sort -rh | head -20
   ```

   **Do not delete anything the owner said to keep.**

**This is the one playbook that deletes user state with no code review standing behind it to
catch a slip.** The gates above are the review.

**What you return:** `df -h /` before and after and how much you got back, the worktrees you
pruned, and one line per item you left standing saying why (which session has it, whether
anything is uncommitted).
