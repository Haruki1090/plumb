# Investigation

**You hold the answer. You assemble it, decide the route, and write it.**

"How does X work." "Why was Y built this way." "Is Z really safe." "Which of X and Y do we take."
Work that returns an explanation or a recommendation with grounds, without changing code.

1. Declare up front that this is a read-only investigation. Do not let it run on into a code change.
2. If you need broad coverage, hand it to the explorer role in `Explore`. **Do not pull the full text
   into the main session** (**principle-guard-the-context-window**). What comes back is pointers to
   files and a summary, and nothing else.
3. On an "is it really safe" question, **try to refute rather than to support**.
   If the premise itself is wrong, say so. Do not lean toward the conclusion you were asked for.
4. Decide the shape of the output first. For an explanation: "the whole picture / the main concepts /
   how it moves / where it lives / the traps". For a decision: a comparison table of the options, and
   one recommendation of your own with the reason attached.
5. Always cite as `path:line`. **Do not write a claim nobody can trace.**

No design happens here, so you do not call `playbooks/shaping-the-work.md`.
If the investigation ends in a code change, stop your hands there, hand it back to the owner, and
re-enter through `playbooks/shaping-the-work.md`. Do not slide into implementation on the momentum of
the investigation.

**What you return:** the output of the investigation itself. For an "is it safe" question, your real
judgment with the reason attached.
