# Batch chatty tools outside the model

## 1. When this applies

**Use this playbook when one answer needs two or more tool calls, or when the same call runs over many
items.** Submit → poll → fetch, list → get for each, and create → wait → read all raise the audit's
request count before they produce an answer.

**A single call with one response is not a chatty loop.** Three calls with a human decision between
them are not one loop either; keep those human decisions and calls in the main session.

## 2. Run the loop once

**The loop runs in a subprocess and the model sees one request.** Write the script, run it, and read
its summary so the audit's request count records one model round trip instead of every loop step.

**What comes back is the file pointer, the count, and the two or three facts that change the next
decision.** Raw responses stay in the file, the same shape **principle-guard-the-context-window**
asks for, and stdout stays below the 40KB `TOOL-RESULT-OVER` line.

## 3. Make the script judgeable

**Exit non-zero and print the exact step that failed.** A silent zero is the claim without evidence
that **principle-gate-claims-on-evidence** exists to stop.

**Make the operation converge on the same end state every time.** The second run is the common case,
so follow **principle-make-operations-idempotent** instead of trusting a single clean run.

**Cap stdout below 40KB.** Write overflow and every raw response to a file, because stdout crossing
40KB creates the same `TOOL-RESULT-OVER` this subprocess is meant to remove.

## 4. Keep the loop when it repeats

**The second time you write the same loop, it becomes a bundled script or a skill.** That is
**principle-build-the-lever**; writing it as prose instead is what
**principle-encode-lessons-in-structure** forbids.

**Use `scripts/` for plumb's own examples.** `session-audit.py` reads several thousand requests in
one subprocess and returns one summary to the model.

## 5. How to tell

**Measure a before session and a different after session with
`plumb-session-audit --session <uuid>`.** Run the audit once for each UUID; requests per session
and compare `TOOL-RESULT-OVER` alongside completed work and correctness. A zero overflow count
cannot fall further, and lower request count is not a win if the after run completed less work.
Use the same workload and record both results. Do not claim a saving from an external benchmark.
