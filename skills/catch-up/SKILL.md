---
name: catch-up
description: Tell an owner who has been away where things stand - what changed, what waits on them, what keeps moving without them, and what could not be read. Use when asked to "catch me up", "what happened while I was away", "what's waiting on me", "what do I need to decide", "where are we", or in Japanese "tsuite iku tame ni ima doko ka oshiete", "fuzai no aida ni nani ga atta", "watashi no hanshin machi wa nani". Read-only. Not for resuming work in a fresh session (playbooks/session-pickup.md) or the weekly look back (plumb:retro).
---

# Catch the owner up

**The owner comes back to a run that kept going. Say what changed, then put every decision that
needs them in front of them, each one answerable in a word.**

## Boundaries

- **Read-only.** Change no file, start no lane, merge nothing, post nothing, answer no review
  comment. If the report shows work worth starting, name it under "Waiting on you" and stop.
- **The window** is everything since the owner's last message before the one that asked for this,
  or the time they name. The request itself is not the start: a window that opens now is empty. State the window's start in the first line. If neither can be read, say so under "Not
  known" and use the last 12 hours.
- **A self-report is a claim.** A lane saying "done" is not a change until you have matched it to a
  commit or a pull request. Report the claim and the match side by side; an unmatched claim goes under
  "Not known".

## Gather, from facts

Run each from inside the repository. The window's length in hours is `H`.

```bash
plumb-run-view --since H      # lanes of the running queues, what landed by fact, what remains
plumb-run-view --since <a week or more, in hours>   # a second pass, for what waits only
plumb-stalled                 # every open pull request, by how long it has waited and on whom
git log --since="<window start>" --first-parent --format='%h %an %s' <base>
```

- **A decision that was already waiting when the window opened is still waiting.** `--since H`
  drops a queue whose last row is older than `H`, so take `needs_owner` from the wider second pass
  and what changed from the first. A queue older than both passes is named under "Not known".
- The run's decision log is the ledger `plumb-run-view` read; its `ledger` field names the file.
  Open it for the rows behind a state: the `ref` column points at a branch or a pull request. Start
  from the lanes with `needs_owner` true, then read the rest. A `remote` other than `ok` means every
  pull request in the answer is unchecked: say so under "Not known".
- Ask the forge for what moved in the window: pull requests merged, opened or closed, and issues
  closed or newly assigned to the owner. Read each by number, not by title.
- A command that fails, or a forge that cannot be reached, is not an empty answer. Record which
  one under "Not known" and go on with the rest.
- Never read a lane's transcript whole into this context. Hand it to the explorer role
  (`role.explorer.model`, `docs/role-map.md`) and take back the rows
  (**principle-guard-the-context-window**).

## The report

Write four parts, in this order.

**1. What changed.** One paragraph in plain words, written for someone who has not seen the run: what
landed, what is open, what broke. No lane names, no jargon the owner never used.

**2. Waiting on you.** Every decision that needs the owner. **None is dropped to keep the report
short**; a long list is the finding. Each decision carries five things:

| | |
|---|---|
| Decision | One line. What is being decided, not what happened |
| Pick | Your recommendation, stated. "Either" is not a pick |
| Evidence | A path, a SHA or a pull request number the pick rests on |
| If wrong | What it costs when the pick is wrong, and whether it can be undone |
| Answer | The one word or short reply that settles it ("merge", "drop", "B") |

A decision that needs a real comparison of alternatives is named here with its question and goes to
`plumb:decision-brief`. Do not squeeze it into five lines.

**3. Moving without you.** What continues on its own, and when it next reports. A lane with no next
report time is listed as such.

**4. Not known.** What you could not read and why: the forge unreachable, a ledger older than the
window, a claim with no commit behind it, a check whose output you did not see.

## Numbers

**Check each number against its source before you write it.** A count of pull requests comes from
the forge listing, a count of commits from `git log`, a state from the ledger row. Say which. Do not
round a mixed result into "all green"; a check you did not see pass is listed as unseen
(**principle-gate-claims-on-evidence**).

## Stop

The report ends with the four parts. Do not append offers of what you could do next, and do not act
on a pick before the owner answers (**principle-never-block-on-the-human** still applies to the work
already running: do not stop it).
