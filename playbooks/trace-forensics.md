# Artifact forensics

**You hold the diagnosis that comes out of the artifact. Load it, reshape it, narrow it to a
cause, and take it back to the source.**

When a `.cpuprofile`, a `Trace-*.json.gz`, a `Spindump.txt` or a `.heapsnapshot` arrives
alongside "why is it slow / hanging / leaking / crashing".

**What separates this from "Live-process forensics" is whether you run anything.** Here the
capture is already done. The artifact is a fixed data set, so you read it. You do not recapture
it.

1. Identify the format and open it with the right tool. **Hand analysis of a large artifact to
   the explorer role** and keep only the cut-down result in the main session
   (**principle-guard-the-context-window**).
2. Convert the raw artifact into something you can query. Load the trace or the heap into
   sqlite so that a sample, a frame or a node is one row. **Get it queryable before you start
   reading.**
3. Narrow to a cause. Pull the frames holding the most time and walk the call tree to the hot
   path. For a leak, follow the retention chain to a GC root. For a spindump, the threads
   holding the CPU or being made to wait, and what they are waiting on.
4. Take it back to the source: file, symbol and line, using the artifact's own symbols.
   **A frame whose symbol you cannot resolve is not yet a diagnosis.** Resolve it, or write
   plainly that this artifact does not carry symbols for it.
5. Cross-check against a paired capture if one exists. Diffing a before-and-after artifact
   tells you whether the attribution is a real regression or background noise. With only one
   side, **say explicitly that this is "the strongest hypothesis this artifact supports". Do
   not write it up as a confirmed cause.**

**What you return:** the artifact and its format, the cut-down result, the location in the
source, the artifact paths, and whether a paired capture confirmed it.
