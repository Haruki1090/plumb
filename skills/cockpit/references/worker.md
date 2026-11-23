# Working a cockpit lane

- Use the brief as the whole acceptance bar. Stay inside its range.
- Use shared services only when the brief lists them. This includes container sockets, databases
  and other worktrees. Follow the brief's forbidden means.
- Commit locally on the lane branch. Do not push.
- Write the report to the brief's report path. Include the commands actually run, their exit
  statuses and any open caveats.
- Do not loosen a gate to pass it: no raised budget or threshold, no allowlist addition, no disabled
  or soft-failed check. Write the report with the proof the gate is wrong.
- A review blocks only on a problem it can show at this head. A problem the base already had is one
  line in the report.
- If the range or acceptance is unclear or the work needs access outside the brief, stop and
  write the report. Let the main session decide the next step.

These sentences are a courtesy. The main session's `plumb-lane collect` checks the paths
against the brief, and `plumb-lane guard` enforces the stop rules on recorded evidence.
