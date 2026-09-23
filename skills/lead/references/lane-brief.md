# Lane brief

Write one file per lane from this template. **Keep the headings exactly** — `plumb-lead-grade`
checks for them, and a missing heading is the first sign of a brief that will come back wrong.
Do not paste coordinator history; hand over only what this lane needs.

```markdown
# Lane <item>: <short title>

## Range
Files and areas this lane may change. Anything else is out of range.

## Material
The failing output, repro steps, lines involved, issue text, the base SHA read.

## Do not touch
Surfaces other lanes own, shared files held back for a later barrier, public interfaces.

## Acceptance
Observable conditions for done, and the exact checks to run.

## Return
- Commit locally on this branch. Do not push, open a PR, or create spec or plan files.
- Do not open extra panes or tabs.
- Write the report to <absolute path>: what changed, checks run with exit status, open caveats.
- Reply with the report path only.
```
