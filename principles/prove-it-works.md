---
name: principle-prove-it-works
origin: plumb
description: "Verify against the real thing by picking one and looking at it directly: a proxy, a self-report, a summary or hearsay is a claim, not an observation, and a verifier you never watched fail proves nothing when it goes green. Use when deciding what would count as proof - \"what is the real thing here\", \"what would prove this works\", \"is a passing build enough\" - or when asked \"did you actually check that\"."
---

# Prove It Works

**This principle holds the method of checking.** When to check belongs to
**gate-claims-on-evidence**. That one puts a gate immediately before a claim;
**this one decides what you look at once you are standing at it.**

**Why this is hard to keep.** A proxy isn't cheaper — it's *faster to green*. A passing
build, a fresh mtime, a subagent reporting done: each hands back the same feeling of
safety as the real thing, one step early. **Ease of evidence and strength of evidence
run in opposite directions**, so taking the easy reading every time always drifts toward
the weak one. Care does not fix this. **Decide what counts as the real thing before you
need it.**

## Telling the real thing from a proxy

**Anything with even one step of derivation in front of it is a proxy.**

| Proxy | The real thing |
|---|---|
| The build passed | You ran the feature's path and read the value that came out |
| The file has been updated | You opened it and saw the content change |
| The process is up | You sent it a request and saw the reply |
| The role you handed it to said it was done | You looked at the diff and the artifacts yourself |
| The review finding says so | You opened the line it names and checked whether that holds in this codebase |
| "They said we could pretty much throw it away" | You listed every deletion candidate and matched it against the owner's own words |

**What a person said sits on the proxy side too.** A finding, a handover note, a claim
left behind by an earlier session: **take it as a hypothesis and re-check it against the
real thing.**

## See the verifier work, first

**A green you reached without ever watching it fail carries no evidence that the
verifier works.** Write the test before the implementation and **watch it fail once.** If you are
checking with a test that already exists, break the target once and see whether it goes
red.

- **Zero lines is not green.** The likelier reading is that nothing ran at all
- **When the observation disagrees, suspect the observation first.** Looking at the wrong
  place, the wrong time or the wrong environment is more common than the system being
  broken
- **Do not loosen the verifier to make it pass.** Lowering a threshold, excluding the
  target, swallowing a failure: **that is killing the verifier**, and the area stays
  unobserved from then on

## Put it in a form you can re-run

Do not look once and be done. **Make the same comparison something you can run again**: an
equivalence check, a comparison against a baseline, a script that puts before and after
side by side. **Only an observation you can re-run becomes evidence the reviewer can
confirm without you.** How to build that tool belongs to **build-the-lever**.

**What counts as one unit to verify belongs to sequence-verifiable-units, and whether you
are aimed at the cause rather than the symptom belongs to fix-root-causes.** What this
principle owns is the content of each single observation.
