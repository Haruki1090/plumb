# Ask for review, and answer what comes back

**This is the author's playbook.** The side that approves is `plumb:pr-review`.
**Do not do both yourself on the same PR.** A record of you judging your own diff is not evidence.

## Asking

### When

**When you have finished something large, before it lands, and when you are stuck.**
Ask only at the end and the first outside eyes arrive at the moment there is the most to fix.

### Who

**The judge role is `role.judge` in `docs/role-map.md`.**
If `plumb-config role.judge ""` comes back empty the main session stands in, but **say first that no
second pair of eyes was involved** (**a visible skip**). Re-read by the same head in the same context
is not independent verification.

### What you hand over

**Do not hand over the session history.** Hand over the diff and only what it takes to read it.

- **The version.** What range is in scope. Pin it with commits, not with a branch name

        git rev-parse origin/<base> HEAD

- **What you built**, in a few lines. Stay to facts that are readable from the diff
- **What has to pass for it to be right.** A path to the spec or the acceptance criteria. **If there is none, write that there is none**
- **The shape of the answer** (next section)

**Do not paste the diff itself into the body** (**principle-guard-the-context-window**).
Hand over the path and the version, and the reviewer reads it themselves.

### Ask for the answer on two axes

**Do not bring in the single `Critical / Important / Minor` axis.**
Folded onto one axis, "severe but low confidence" and "certain but trivial" sit on the same shelf,
and **whether to stop the landing becomes unreadable.**

Ask on two axes: **confidence** (confirmed, or suspected) and **blocking** (does it stop the landing).
It is the same shape `plumb:pr-review` returns, so **whichever side it comes back from, it goes on
the same table.**

## Answering

### Read all of it before you move on any of it

**If even one finding does not parse, stop there and ask.**
Do not fix the part you understood first. **Findings connect to each other, and a fix made on half
an understanding gets rebuilt the moment you read the other half.**

### Verify it on your side before you fix

**A finding is a hypothesis, not a fact** (**principle-prove-it-works**).
What to look at before you take it in:

- **Whether it is actually so in this codebase.** Check the finding's premise for real
- **Whether there is a reason the implementation is the way it is.** Compatibility, environment, a past ruling
- **Whether it collides with something the owner already ruled on.** If it does, hand it back to the owner instead of fixing it

**When you are told to "implement it properly", count the callers first.**
Making something nobody calls magnificent is work added, not work fixed.

### Do not perform agreement

**Do not write "you're absolutely right", "great catch", "thanks for this".**
Every line of it hides the fact that you did not verify. **If you fixed it, writing that you fixed it
is enough.**

    Fixed. <where, and what changed>

### You may push back, but with technique

**If you can say it is wrong and stand behind that, say so.**
The place it breaks, the test that passes, the version you depend on: **attach something you can
point at.** If you have no way to check, **say you have none.** Do not push "probably fine" through.

When you push back and it turns out you were wrong:
**write one line saying what you checked and where you were wrong, then fix it.**
No long apology, and no defence of why you pushed back.

### The order you fix in

**What stops the landing, then the small ones, then the large ones.**
**Fix one, run the check on that one** (**principle-sequence-verifiable-units**).
Fix in a batch and run in a batch, and you lose which one broke what.

Once they are all in, **run the whole check again before you say done**
(**principle-gate-claims-on-evidence**).

### Where to answer

**A finding attached to a line is answered in that line's thread.**
Collect them at the bottom of the PR instead and nobody can trace which finding an answer belongs to.

    gh api repos/<owner>/<repo>/pulls/<number>/comments/<comment id>/replies -f body='...'

**The findings you did not take in are the ones that need a reason on the record.**
Silence is indistinguishable from an oversight.

**What you return:** how many came in and the breakdown on the two axes, what you fixed and the check
result for each, **what you did not take in and on what grounds**, what you handed back to the owner.
