# Return template

Shaped so it pastes straight into a GitHub review comment. If you visualize it in HTML instead, do not
lose the information in these six sections (visualizing is for readability, not for summarizing).

---

## Review result

**SHA under review**: `<sha>` — this approval is **against this revision**. Anything pushed later is out of scope.
**Time spent**: <n> hours / **Depth**: <which axes were run, and how many>

### Decision

<Approve / Request changes / Comment>

<One sentence of reasoning. "Because n BLOCKs stand" / "No BLOCK; approved having accepted m residual risks">

### Blockers (BLOCK)

| # | Confidence | Where | How it breaks |
|---|---|---|---|
| 1 | CONFIRMED | `path:line` | <input or state → wrong output / loss> |

### Fix before merge (FIX)

| # | Confidence | Where | How it breaks |
|---|---|---|---|

### Recorded only (NOTE)

- <What was decided not to fix this time. The point is to leave the decision on the record>

### Residual risk accepted

In approving, I judged the following to be "possible, and accepted". **Write the first response for each,
in case it happens.**

| Risk | What is left when it happens | First response |
|---|---|---|

> "Probably fine" is not a residual risk. If you cannot write the name and the response, fall to BLOCK.

### What I did not look at

The time budget meant the following went **unread**. This approval guarantees nothing about it.

- <The list cut in stage 2. One line of reasoning per exclusion>

---

## Addendum when the body has drifted

<n> commits landed after the body was last edited (<timestamp>), so the body does not describe the
current diff. The following changes are **not written up in the body**:

- `<sha>` <message> — <what changed>

Decide before approving: either require the body to be updated, or state explicitly that this diff is
inside the scope of the approval.
