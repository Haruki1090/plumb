# Working a cockpit lane

- Use the brief as the whole acceptance bar. Stay inside its range.
- Use shared services only when the brief lists them. This includes container sockets, databases
  and other worktrees. Follow the brief's forbidden means.
- Commit locally on the lane branch. Do not push.
- Write the report to the brief's report path. Include the commands actually run, their exit
  statuses and any open caveats.
- If the range or acceptance is unclear or the work needs access outside the brief, stop and
  write the report. Let the main session decide the next step.

These sentences are a courtesy. The main session's `plumb-lane collect` checks the paths
against the brief, and `plumb-lane guard` enforces the stop rules on recorded evidence.
