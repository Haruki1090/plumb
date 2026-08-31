# Pause safely

**You hold the clean stop.** Leave a checkpoint that can be resumed from cold.

"Stop safely." "I'm going offline." "Shut it down for now." And **when the context is about to be
compacted.**

**Only two things fire this.**

- **An explicit instruction from the owner.** "Carry on as you were", "I'm going to bed, keep going",
  "don't stop" are not a pause. They mean continue.
- **When you judge for yourself that compaction is close.** This one does not wait for an
  instruction. Wait, and what you waited for gets swallowed by the summary. **You write the note and
  then continue**; **you do not stop the work** (skip steps 1 to 3 and run only step 4).

1. Stop at a safe boundary. Finish the atomic step you are on, or back out of it.
   **Do not stop in the middle of a state you know is broken.** Do not start anything new.

   **Collect what is running before you fold it up.**
   Wait for it to finish, drop the output to a file, and **write the IDs a resume needs (pane ID,
   branch, PR number) into the step 4 note before** you close it. Noticing after you closed it does
   not bring the computation back.
   **The only panes you may close are the ones you made.** A tool that owns panes has ownership
   rules. Do not touch another job's pane, running or not.
2. **Do not cross an irreversible line for the sake of pausing.** If it is not already out, do not
   open the PR and do not push.
3. Persist the work. Put the uncommitted edits on the current branch as one `wip:` commit so nothing
   is lost. If the tree is broken, write one line saying so in the commit body.
4. **Write the resume note outside the context.** The intent, what you were doing, how far you got and
   what is verified, the current state, the next move, the key files, the traps.
   If compaction is the trigger, **write it to a file in the scratchpad**: a plan that lives inside
   the context does not survive the summary.
   If a ledger already exists, point at it instead of duplicating it.

**What you return:** where in the loop you are, what is on disk and what exists only in your head (as
paths; do not paste diffs), the commit you made and whether the tree is clean, the first move on
resume.
**This is a pause, not a final report.** Resuming starts where `playbooks/session-pickup.md` reads
this note.
