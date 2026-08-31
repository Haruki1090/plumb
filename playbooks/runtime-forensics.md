# Live-process forensics

**You hold the diagnosis. Measure the running process. Do not infer it from the source.**

"Why does it leak / spin / run slow at runtime". A heap snapshot, a process that is busy while
idle, a defect that will not reproduce. **What you produce is a diagnosis, not a fix.**

1. Capture a live signal from the real thing. A CPU profile if it is spinning, a heap snapshot
   if it is leaking, a trace if the rendering is wrong. **One real artifact, not a guess**
   (**principle-prove-it-works**). Capturing takes tens of seconds, so run it in a pane
   (`pane.driver`; unset: run it in the foreground).
2. Cut the artifact down to a single decisive point: the function on the hot path, the
   retention chain from the leaked object to a GC root, the loop that keeps firing with no
   input. **Hand analysis of a large artifact to the explorer role** and keep only the cut-down
   result in the main session (**principle-guard-the-context-window**).
3. Prove the mechanism before you believe it. Inject instrumentation into the running process,
   or patch it in place without reloading, and buy the answer cheaply.
   **A plausible but unconfirmed cause can be consistently supported even while the real one
   sits in the layer next door.**
4. Take the point you found back to the source: the file, the symbol, the line that allocates
   or holds the reservation.

Do not fix it (**principle-fix-root-causes**). Once the cause is known, hand debugging to
`playbooks/fixing-a-bug.md`, or to `playbooks/shaping-the-work.md` if it needs a rebuild.

**What you return:** the signal you captured, the cut-down result, how you proved the
mechanism, the location in the source, the artifact paths.
