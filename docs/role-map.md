# Where roles run

**`~/.claude/plumb/config` decides where a role runs, not this document.**
Do not write a command name in prose. Write one and the document turns into a lie for anyone
who does not have that tool.

| Role | Key | When unset |
|---|---|---|
| Main session | — (the Claude Code you are running in) | — |
| Implementer role | — (`Task`. Do not write `model`) | — |
| Explorer role | — (`Task`. Produces no diff) | — |
| Judge role | `role.judge` | **The main session stands in.** Say out loud that no other family's eyes are on it, and go on |
| Bulk role | `role.bulk` | The main session works through it in order |
| Driving a pane | `pane.driver` | Run it in the foreground |
| Stack operations | `stack.tool` | Drops to "Land it with bare gh" in `playbooks/landing-a-stack.md` |

How to ask:

    plumb-config role.judge ""

**Unset is not a fault.** It returns empty and exits 0.
Even with the judge role unset, **the todo line for the judge role does not disappear**
(**visible skip**). Leave it there reading `skip: role.judge unset`.
