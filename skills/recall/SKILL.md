---
name: recall
description: Rebuild the context of a topic that spans several sessions - what was done, where each piece stands now, what is still open, and what to do next. Use when asked "what did we do on X last week", "remind me where X stands", "pull together everything about X", "what's the history of X", or in Japanese "X wo senshu nani shita ka", "X no genjo wo omoidashite", "X ni kansuru koto wo zenbu matomete". Read-only. Not for continuing one interrupted session (playbooks/session-pickup.md) or what happened since the owner's last message (plumb:catch-up).
---

# Recall a topic across sessions

**A transcript says what was meant. The repository says what happened.** Rebuild the topic from both,
and where they disagree the repository wins.

## Start condition

Fix **the topic** and **the period** before reading anything. Without both, **ask once**, naming
what is missing, and stop until you have the answer. Do not guess a period.

This skill is read-only: it changes no file, opens no pull request and sends nothing.

## Two sweeps, both required

**1. Own history.** The session transcripts of the period, and what they cost.

- Resolve transcripts through `docs/path-map.md`; pin the project's slug first and never glob across
  projects. Pick sessions by date, then by the topic's words.
- **Split the reading and hand it to the explorer role** (`role.explorer.model`, `docs/role-map.md`),
  one session or slice per call, and take back rows of thread, what was tried, what was concluded and
  where in the transcript. Do not load a transcript whole into this context
  (**principle-guard-the-context-window**).
- Cost: `plumb-ledger records --since <day> --until <day>` lists every request of the period with its
  repository, branch and cost. Keep the rows that match the topic's branches. If the ledger holds
  nothing for the period, say so.

**2. The shared record.** What the repository and the forge hold: commits (`git log --since` with the
topic's paths and words, all branches), pull requests, issues and their review threads, read through
the forge. Read by number, not by title.

If a sweep cannot run (the forge is unreachable, transcripts are gone), say which, and carry on with
the other. A recall with one sweep says so in its first line.

## One state per thread

A thread is one line of work: a change, a bug, a decision. Give each **exactly one tag**, set from a
fact you checked now with git or the forge. **Never set a tag from what a transcript said.**

| Tag | Fact that sets it |
|---|---|
| `[merged #N]` | The pull request is merged, and its merge commit is on the base branch |
| `[open PR #N]` | The pull request is open |
| `[reverted #N]` | A later commit or pull request reverts it |
| `[branch only]` | Commits exist on a branch with no pull request |
| `[abandoned]` | A pull request closed unmerged, or a branch with no activity since the period and no pull request |
| `[unknown]` | The transcript names it and neither git nor the forge shows it |

An `[unknown]` stays `[unknown]`. Do not promote it to a finished thread because the transcript
sounded finished.

## Output

Four parts, in this order.

**Capsule.** At most 5 lines: what this topic was about, in plain words.

**Threads.** One bullet each: the tag, then one line of what it did. Order them by when they began.

**Problems.** At most 5, only those **still open now**, each with the evidence that it is open. A
problem a later pull request fixed is a thread, not a problem.

**Next move.** One. If the evidence points to two, pick one and say why; do not hand over a list.

When `plumb-ledger records` could say what the topic cost, end with one line: the total, the period,
and which requests it counted. When it could not, say that instead; do not estimate.
