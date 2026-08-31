# Open a PR

**This playbook is not an entry point.**

What a playbook goes through first at its end is `playbooks/closing-a-branch.md`.
Getting the tests to pass and then **having the owner choose between merging locally, pushing and
opening a PR, and leaving the branch alone** is that playbook's job, and **you do not take the same
decision early here**.

**You enter this playbook once opening a PR has been decided.**
The scope ends at getting it out. Getting it green and landing it is `playbooks/landing-a-stack.md`.

## Isolation

Work in a worktree cut from main. Where they live and how the roots are organised is
`docs/path-map.md`.
**Do not put two implementer roles on the same branch at once**
(**principle-separate-before-serializing-shared-state**).
If the branch is dirty with unrelated work, pull the patch out and re-apply it in a new worktree.

## Commits

**Do not be sparing with commits. Before you open the PR, rebase into small, ordered ones.**
Build each commit as though it were a future PR: it can land on its own, and they stand in the order
of the story. A fix that belongs to the previous commit is an amend; if it can be separated, it is a
new commit.

## The title

Conventional Commits, `type(scope): subject`. The types are `feat` `fix` `docs` `refactor` `test`
`chore` `perf`. The scope is the area you changed. The subject is short and imperative.
**If a real symbol carries the change, name it.** No full stop at the end.

## The body

**These sections, in this order. Drop a section that would be empty.**

| Section | What goes in it |
|---|---|
| `## Why` | The intent, and why this method fits it |
| `## Scope` | **Only facts readable from the diff.** Name real symbols and paths. Write both sides of a rename or a repoint. If a boundary is at issue, write the inside and the outside |
| `## Tradeoffs` | **Only real choices.** If there are none, drop the section entirely |
| `## Blast Radius` | Who and what it touches. Why it is safe, or why it is risky. If main stays red without this fix, write the continuing cost of that |
| `## Verification` | **How you ran each check, and how strict it is.** Name the path you actually ran. Write the result, not the name of the command |

If you have a screenshot or a video that proves the claim, attach it after the section.
**Do not use the `## Summary` and `## Test plan` boilerplate.** A commit body does not restate its
subject.

## Attaching UI screenshots

If you touched UI, **attach a before and an after screenshot**. Whether it came out right is not
readable from the diff.

**Do not touch the baseline.** Even when the before screenshot looks "wrong", do not retake it and do
not tidy it up. If it is wrong, report that and stop.
**The moment you touch the baseline, the comparison stops being a comparison.**

### Making the before

The before no longer exists once the work is implemented. **Shoot it first, or restore it and shoot.**

To restore it, take **only the files you touched** out of the base. Do not restart the dev server; HMR
picks it up. Switch branches or stash and the surroundings move too, and there is nothing left to
compare.

```bash
# Resolve the base. Do not hard-code a remote or a branch name (`playbooks/landing-a-stack.md`):
# a repository whose remote is not origin, or whose default branch is not main, dies on the spot.
base=$(git rev-parse --abbrev-ref '@{upstream}' 2>/dev/null) \
  || base=$(git rev-parse --abbrev-ref "$(git remote | head -1)/HEAD")

git checkout "$(git merge-base HEAD "$base")" -- <touched-file>   # shoot
git checkout HEAD -- <touched-file>                               # put it back after the shot
```

Confirm with `git status` that **nothing was left un-restored** before you go on.

### Shooting

**Make every one of these identical in both screenshots.** Anything that differs on one side is
captured as "the change".

- Window and viewport dimensions (`resize_window` once, first)
- Scroll position, and the account you are logged in as
- **The state of the data** (pins, counts, sort order). A section that exists on one side only is not a comparison
- **The pointer position.** Immediately before shooting, `hover` at coordinates away from the target.
  Otherwise a hover state burns into one side only

**Remove the development overlays.** Next.js's `nextjs-portal` and Claude in Chrome's own
`#claude-agent-glow-border` sit on top of what you are shooting. **Apply the same CSS to both states,
and write in the PR body that you applied it.** Applying it on one side only is touching the baseline.

```js
let s = document.getElementById('__shot-style');
if (!s) { s = document.createElement('style'); s.id = '__shot-style'; document.head.appendChild(s); }
s.textContent = 'nextjs-portal, #claude-agent-glow-border { display:none !important; }';
```

The whole page is `computer`'s `screenshot`; a part of it is `zoom` with a region to cut out (both
with `save_to_disk: true`). **Shoot both the whole and the zoom.**
The whole alone makes the change too small to see; the zoom alone hides how it relates to what is
around it.

### Compositing and hosting

`scripts/host-shots.sh` takes on the side-by-side compositing, the push to **an orphan commit with no
parent**, and printing the Markdown to paste. **It does not shoot.**

```bash
plumb-host-shots --branch assets/<topic>-<yyyymmdd> \
  --pair before-expanded.png after-expanded.png "the expanded state, compared" \
  --file before-full.png "before (whole)" --file after-full.png "after (whole)"
```

It is an orphan so the images stay out of develop / main history and CI does not run on them.
Use only the URL form `https://github.com/<owner>/<repo>/raw/<branch>/<file>`:
**on a private repository, `raw.githubusercontent.com` carries no session cookie and returns 404.**
The remaining options are in `--help`.

### Writing it into the body

**Spell out what changed visually, as a list.** Paste the images alone and the reader is left hunting
for the difference. It is not readable from the diff either: that `px-3` → `px-2` reads as "it got
tighter" is not knowable from the code.

**If the design document holds a contract on real values, check them against each other.**
A test on the color tokens can pass while nobody is looking at the dimensions. If they have drifted
apart, **put it in the body as needing a decision.** Letting it through silently and fixing it in this
PR are both calls you do not make alone.

**A screenshot you looked at is not proof that "the appearance did not change"**
(plumb has no pixel-diff harness. `docs/scope.md`). Anything you believe you did not change, write it
down as reserved.

## Size

**Five narrow ones beat one large one.** Cut from main only work that stands independent.

## Getting it out

**A standalone PR**

```bash
gh pr create --draft=false        # do not open it as a draft
gh pr view <number>               # always read this before you talk about its state
```

**If you are stacking, actually take the stacking steps**

Writing "the rest gets stacked" and lining up `gh pr create` **does not make a stack.**
Neither the base relationships on GitHub's side nor the metadata `gh stack` reads gets created by
anyone. In that state you cannot reach the last step of `playbooks/landing-a-stack.md`.

```bash
gh stack init                     # start a new stack from the default branch
gh stack init b1 b2 b3            # make a stack out of branches that already exist
gh stack add <branch>             # stack one on top
gh stack submit                   # push every branch and create or update its PR
gh stack view --short             # confirm with your eyes that it is stacked
```

**If `gh stack view` cannot find the stack, it is not stacked.**
Do not move on believing you got it out.

**Turning PRs already piled up by a base chain into a stack afterwards**

A row made by lining up `gh pr create` with a base is not a stack on GitHub's side.
`gh stack link` links the existing PRs from the bottom up, **without using local tracking state**.

```bash
gh stack link 421 422 423 424 425 426   # bottom to top. pass existing PR numbers only
gh stack view --short                    # confirm they are linked
```

> **Pass PR numbers and nothing else.** Pass a branch name and **it pushes that branch, and creates a
> new PR if there is none.**
> A numeric argument resolves as "a PR number first, a branch name if there is none", so
> **pass the PR's URL when you want certainty** (a URL always resolves as a PR).
> Putting a stack number first means adding on top of an existing stack.

## What not to do right after you open it

**Opening a PR is not the start of the work of getting it green.** Put the URL out and keep building.
Once a phase or the whole stack is built, run `playbooks/landing-a-stack.md` once, when the owner asks
for it.
**Go green PR by PR and you burn the checks on commits a later wave rebuilds, and the work itself
stops.**

**What you return:** the PR URL, the title, and what you wrote in the verification section.
