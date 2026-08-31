# Close out a branch

**Every playbook ends by coming through here.**

Being done building and having somewhere for the work to go are two different things.
**What you decide here is only where it goes**; what to build was settled already. So you do not
produce a `plumb:decision-brief`: a branch whose choice does not change what gets built needs no
comparison board.

If it goes out, it goes to `playbooks/opening-a-pr.md`. **The discipline for folding up the isolation
belongs to `playbooks/worktree-cleanup.md`** and is not copied here
(**principle-encode-lessons-in-structure**).

## 1. Take green again, now

**Run the check on the tree you are about to integrate.**
A record of it passing earlier in the session is evidence about the tree at that moment and nothing
else (**principle-gate-claims-on-evidence**).

If it is red, stop there. **Do not start the conversation about where it goes.** Show what failed and
go back to fixing.

## 2. Confirm the base

**Do not fill in where this branch forked from by guessing.**
It is written in the plan, in the conversation, or in the upstream. If it is in none of them,
**ask the owner**.

    git log --oneline --graph -20
    git rev-parse --abbrev-ref '@{upstream}' 2>/dev/null

Do not hard-code the name of the default branch. **A merge into the wrong base costs more to undo
than it did to make.**

## 3. Put the three options up, and wait

**Integration is the owner's call.** You stop at laying the options out.

- **Merge into the base locally**
- **Push it and open a PR**
- **Leave it as a branch** (the owner handles it later)

**Do not add a fourth one yourself.** "Throw it away" in particular does not belong in this list
(see "When you are told to throw it away" below).

**A workspace carrying no branch name loses the first option.** Give it a name first, or give it one
at push.

## 4. Execute what was chosen

**Merge locally**

Step outside the isolation, advance the base, merge, and **run the check again on the merged result**.
Some failures appear only once things are joined (**principle-sequence-verifiable-units**).

If it goes red, **stop there**. Keep the branch and keep the workspace. Nothing has gone outside yet,
so there is no shortage of places to go back to. If it is green, fold up the workspace and then drop
the branch ref.

**Push it and open a PR**

Push, and enter `playbooks/opening-a-pr.md`. **Keep the workspace.**
Answering findings happens there. "The PR is out, so the workspace is garbage" is not how this reads.

**Leave it**

Say the branch name and the workspace path, and stop. **Delete nothing.**

## 5. When you are told to throw it away

**This route exists only when the owner has explicitly said to throw it away.**

List what disappears — the branch, the commits on it, **the untracked and ignored files left in the
workspace** — show the list, and **take confirmation one more time** before you go.

    git -C <workspace> status --porcelain -uall
    git -C <workspace> status --porcelain --ignored

**A `.env`, a local DB, notes you have not written up yet: none of them come back from Git.**
Do not fire on "they said it was more or less fine to throw away" (**principle-prove-it-works**:
what you judge on is the owner's own words).

**What you return:** when you ran the check and what it said, the name of the base and how you
confirmed it, the destination the owner chose, the operations you ran, **what you kept**
(the branch, the workspace path, the PR URL).
