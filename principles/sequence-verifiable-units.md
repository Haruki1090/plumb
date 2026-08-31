---
name: principle-sequence-verifiable-units
origin: plumb
description: "Slice multi-step work into units that each end in a verifiable state, get one green before starting the next, and run the whole thing again once they are joined, because a green unit is not a green composition: the ordering itself is your proof to the reviewer. Use when asked \"how should I split this up\", \"what order do these land in\", or \"can I just do it all and test at the end\"."
---

# Sequence work into verifiable units

**Never advance further in one go than you can carve up in one go.**

**Why this is hard to keep.** Editing in bulk and checking once at the end always looks
faster. **It is faster only when nothing goes wrong, and that branch is invisible in
advance.** When something does go wrong, you pay the entire cost of picking one cause out
of a wall of red, with several more layers already stacked on top of it. **The expected
values are asymmetric, so choosing by feel picks the losing side every time.**

## Get the starting point green first

**Before you slice, see that the tree you already have is green.** Skip this and you lose
any way to tell whether the first red is yours or was there before you arrived. Right after
you create a workspace, right after you put the work back on the trunk: **run it through
once before you start.**

## How to make a unit

- **Take the smallest chunk that ends in a check.** One edit and the test that watches it;
  a commit that stands on its own
- **Green, then next.** Do not edit in bulk and run once
- **Shape it so that one undo takes back one unit.** A granularity you cannot take back is
  not a slice
- **Do not drop the per-unit check, least of all when a tool is doing the editing for you.**
  However much faster your hands got, that is how much bigger the rewind is when the red
  shows up late

## A green unit is not a green composition

**A failure that only appears once the pieces are joined has passed through no unit check
at all.** A per-unit gate is scoped to that unit, so it is not looking there — it cannot be.

- Even when the work you handed out is green piece by piece, **run the whole thing again
  after integration**
- Before you close out a branch, **look at the branch as a whole, once**
- Answering findings works the same way: **fix one, run one**, and put the whole thing
  through again at the end

## Use the ordering as proof

**How you arrange the units becomes a storyline the reviewer can replay.** The reference
shape is **a failing test first, the fix on top of it**: the first shows the problem is
real (red), the second shows it is solved (green).

There are others. Delete, then rebuild. Capture a baseline, then touch it. Lay the
foundation, then put the feature on top. **Each of them turns "trust me" into "watch the
red go green".**

**Making each single check real belongs to prove-it-works, and making per-unit checks cheap
belongs to build-the-lever.** What this principle owns is the slicing and the ordering.
