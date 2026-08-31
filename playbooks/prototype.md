# Prototype

**You hold the design decision, not the code. A prototype is a tool you throw away.**

"Prototype this", "mock it up", "sketch something", "try this layout", or any exploration
before the UI, the interaction, or the arrangement is settled.
Use it also when **an empirical branch you were about to hand the owner** — which behavior,
which timing, which method — is one you can answer yourself by running it and watching.

> **This is a tool used inside the "probe" tier of `playbooks/shaping-the-work.md`, not a replacement for it.**
> The probe's gate stands: **say what you are about to try in two or three sentences, and build nothing until you get a nod.**
> "I can answer this myself, so I won't ask" **does not extend to permission to build.**
> After approval, where the probe says only "keep it cheap", this playbook fills in how.

Inside the gate, **the bar for "smallest change" and for verification inverts.** Speed over
polish. Code quality is not the question. **The rigor lives in choosing the right design
cheaply.** Be bold. Produce variants nobody asked for. Throw one away and try another.

1. **Decide first what this prototype exists to settle.** Which arrangement, which
   interaction, which density. For an empirical branch: which behavior, which timing, which
   method. **No decision means no prototype** — send it to `playbooks/shaping-the-work.md`.
   State the decision and the approach in two or three sentences. **Wait for approval. Stop here.**
2. If the design space is open, gather references. Find prior art, summarize the themes,
   palettes and arrangements, and let the direction be chosen first. Skip this when the
   direction is already fixed.
3. Build it somewhere isolated from the product source, on the assumption you will delete it.
   For a visual decision: plain HTML/CSS/JS, or the lightest setup that can draw the option.
   For a behavior or timing decision: the smallest script that exercises that one question.
   **No product framework, no tests, no abstractions.**
4. When you are comparing options, **put all of them behind one switch**. Label each variant
   so the owner can call it by name. This is **principle-exhaust-the-design-space** done cheaply.
5. Check against the real thing. For visuals, screenshot every variant and actually drive the
   interaction. **Your eye is the test.** For behavior or timing, record the timings, produce
   the output, watch it render. **Here observation is the test**, not an assert.
6. Return the options, the trade-offs, and a recommendation. **The artifact is a decision and
   a disposable implementation, not shippable code.** Hand the chosen direction to
   `playbooks/writing-a-plan.md` and build it again for real.

**What you return:** the variants you explored, the evidence (screenshots for visuals, observed
output or timings for behavior), the trade-offs, the recommendation, and the path to the
scratch work. **Say plainly that the prototype is meant to be thrown away.**
