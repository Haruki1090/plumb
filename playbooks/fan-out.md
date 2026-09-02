# Fan independent work out at once

**The role is `role.bulk` in `docs/role-map.md`.**
If `plumb-config role.bulk ""` returns empty, **the main session works through it in order** — say so
before you go (**a visible skip**). That is slower, not wrong.

There are only two reasons to fan out. **To fold up waiting time**, and **to push bulky things out of
the main session** (**principle-guard-the-context-window**).
If it is neither, do not fan out. **Handing it out costs more than doing it.**

## 1. Do not settle independence by assumption

**Do not create two writers on the same thing** (**principle-separate-before-serializing-shared-state**).

Before you hand anything out, list what each job writes to: files, branches, where the artifacts land,
external state. **One overlap and it is not independent.**

When they do overlap, the default is to **remove the sharing itself**. Split the write targets per job
and **join them only on read**. If you cannot split them, do not fan out; do it in order.
Writing "take turns touching this" and handing that over is not concurrency control.

**Do not fan out jobs whose causes are connected, either.** Failures where fixing one makes the rest
disappear finish sooner shown to one worker together. The same holds while you still do not know what
is broken. If you need isolation, `playbooks/worktree-setup.md`.

## 2. Build what you hand over, yourself

**Do not hand over your own history.** Hand over only the context you assembled for that job.
Hand over the history and the worker starts reading the trail of your thinking instead of the work.

Every brief carries:

- **The range.** Which files, which area. "Fix everything" is the signal for getting lost
- **The material to judge on, itself.** The failing output, the repro steps, the lines involved. Do not settle for "that bug"
- **What must not be touched.** Leave it out and a refactor of the surroundings comes back
- **The shape of the answer.** What you want back, and at what granularity

## 2a. Hand it to the cheapest role that can do it

**A job you can brief precisely is a job that does not need the frontier.** Decomposition and
judging stay in the main session; execution of the bounded brief goes to `role.bulk`.

**An unset `role.bulk` is a visible skip.** Say `skip: role.bulk unset` and run the job in the main
session. Do not call that a fan-out.

**Section 2 is the four-part bulk-ready test.** A brief with the range, the material, what not to
touch and the shape of the answer is ready for `role.bulk`. Leave a part out because you do not
know it yet and the job is exploration, which stays with you. The `model (sidechain)` line of
`plumb-session-audit` shows where handed-out work actually ran.

## 3. Put them all out in one reply

**Only what you line up in the same reply runs at the same time.** One brief per reply is fanning out
in series.

Let the count come from the number of jobs. **Do not add more because you have capacity.**
The time to read what comes back is a finite resource on your side too.

## 4. Look at what comes back as a diff

**A summary is a claim, not evidence** (**principle-prove-it-works**).
What comes back is a write-up of what they meant to do, so **look at what actually changed yourself**.

    git status --porcelain -uall
    git diff --stat <the commit before you fanned out>

The order to look in:

1. **Whether what they wrote stayed inside the range you handed them.** Overrun shows up first
2. **Whether two of them touched the same lines.** If they did, your step 1 judgment was wrong
3. **Run the whole check once, after integration.**
   Each one can be green and the combination red (**principle-sequence-verifiable-units**)

**If the same mistake came back from all of them, the mistake is in how you handed it out.** Do not fix
them one at a time: fix the brief and fan out again (**principle-encode-lessons-in-structure**).

**What you return:** the units you handed out and the grounds for their independence, how many actually
ran, the range each one touched, the check result after integration, **what was wrong on the
handing-out side** (if anything).
