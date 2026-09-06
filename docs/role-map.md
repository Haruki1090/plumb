# Where roles run

**`~/.claude/plumb/config` decides where a role runs, not this document.**
Do not write a command name in prose. Write one and the document turns into a lie for anyone
who does not have that tool.

| Role | Key | When unset |
|---|---|---|
| Main session | — (the Claude Code you are running in) | — |
| Implementer role | — (`Task`. Do not write `model`) | — |
| Explorer role | `role.explorer.model` (`Task`. Produces no diff; the key sets its `model`) | Inherits the main session's model |
| Judge role | `role.judge` | **The main session stands in.** Say out loud that no other family's eyes are on it, and go on |
| Bulk role | `role.bulk` | The main session works through it in order |
| Driving a pane | `pane.driver` | Run it in the foreground |
| Stack operations | `stack.tool` | Drops to "Land it with bare gh" in `playbooks/landing-a-stack.md` |

How to ask:

    plumb-config role.judge ""

**Unset is not a fault.** It returns empty and exits 0.
Even with the judge role unset, **the todo line for the judge role does not disappear**
(**visible skip**). Leave it there reading `skip: role.judge unset`.

## Where effort goes up

**Effort is a per-call setting, not a session default.** The default is medium
(**principle-spend-on-the-outcome**: output tokens are billed at a multiple of input, and
`thinking %` in `plumb-session-audit` is the term this moves). Raise it only for the roles below.

| What the role does | Effort |
|---|---|
| Extraction, classification, mechanical transformation, a bounded exploration | low |
| Implementation, investigation, a review whose target is still wide | medium (the default; do not set it) |
| Verification, arbitration, final integration, a review narrowed to a few paths | high |

Lower it and verification slips through; raise it and only the cost goes up. **Do not buy back a
target you failed to narrow with effort** — narrow first, then raise it once.

## Observable terminal execution

When `pane.driver` is configured, use its installed instructions to run long checks, builds, and
investigation sweeps in a visible pane. Keep the caller's working directory and preserve the user's
focus. Record the returned pane ID, log path, and command exit status; a visible process or a completed
wait is not evidence that its command passed. Preserve pipeline failures when capturing logs with
`tee`. Reuse only panes created for this task and never close another session's pane.

If the driver requires a managed-session marker, check it before controlling panes. From outside that
session, use foreground execution and record the visibility limitation. Do not attach to whichever
unrelated session happens to be focused. Routing configuration selects a driver; it does not authorize
starting extra agents, publication, or other external actions.
