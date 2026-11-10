# plumb in a cloud session

A cloud session (Claude Code on the web, a cloud agent) runs in a container that is created for the
session and reclaimed after it. Nothing you set up by hand survives: plumb, its config and its
records must come from the environment's **setup script**, and the records must leave before the
container does. This page is the setup script's lines and what each one is for.

## What a cloud container is like

Measured on 2026-10-30. Each fact changes what plumb does there.

| Fact | What plumb does about it |
|---|---|
| The setup script runs before the session and **cannot read the environment's saved variables or secrets** | Config values are written as literals by `plumb-bootstrap`; none of them is a secret |
| An environment can cache the container's files once the setup script finishes; later sessions start from that cache and skip the script until it is edited | plumb stays at the version installed then, so a session-start command updates it (below) |
| The container is reclaimed after the session goes idle, with no reliable "session ended" event | Records leave at the end of each turn (`ledger.export = on-stop`), not at the end of the session |
| The git proxy accepts pushes to branches only | The store keeps one branch per session (`refs/heads/plumb-ledger/<runtime>/<session>`) |
| The proxy refuses GitHub's numeric-id paths, so `gh api --paginate` fails (HTTP 403), and GraphQL is blocked | Every plumb tool pages REST lists by number and never uses GraphQL |
| A private repository is reachable only when it is attached to the environment (Repositories in its settings) or to the session | The cost store must be attached for exports to land |
| No panes, no `gh-stack` | `pane.driver` and `stack.tool` stay unset; `plumb:lead` runs lanes as isolated subagents and stacks land with bare `gh`, one pull request at a time (`playbooks/landing-a-stack.md`) |

## The setup script lines

Add these to the environment's setup script (the cloud environment menu in the session's title bar,
then Edit, then Setup script). Replace the store URL with your own private repository, or leave
`--store` out to keep records in the container only.

```bash
# plumb: install, then configure (the setup script cannot read saved variables; nothing here is secret)
claude plugin marketplace add Haruki1090/plumb
claude plugin install plumb@plumb
PLUMB_ROOT_DIR=$(claude plugin list --json | python3 -c 'import json,sys; print(next(p["installPath"] for p in json.load(sys.stdin) if p["id"] == "plumb@plumb"))')
"$PLUMB_ROOT_DIR/bin/plumb-bootstrap" \
  --store https://github.com/<you>/<private-store>.git \
  --capture on --export on-stop \
  --judge "codex exec --sandbox read-only"
```

What each line does:

- **Install.** The marketplace and the plugin, with the commands any installation uses. This
  installs the current version on `main` when the script runs; in a cached environment, that is
  the version every later session starts with.
- **`plumb-bootstrap`** writes the keys it is given into `~/.claude/plumb/config`, inside a block it
  owns (it replaces only that block, and running it twice changes nothing). Then it checks, one line
  each: plumb is installed, the judge's command resolves and, for Codex, is logged in, the store
  answers, and `plumb-doctor` passes. It reports problems and exits 0, so a missing login never
  fails the environment; `--strict` makes problems fail the script.
- **`--capture on --export on-stop`** records each request at the end of every turn and sends that
  session's records to the store in the background. Leave `--export` at `manual` to run
  `plumb-ledger export` yourself.
- **`--judge`** routes the judge role (`docs/role-map.md`) to another model family. The judge's own
  login cannot be done by a setup script: if `plumb-bootstrap` reports it missing, log in from the
  session (for Codex, `codex login --device-auth`).

## Route the subagents

`plumb-bootstrap` takes three more flags, each written into the same managed block. Add the ones you
want to the `plumb-bootstrap` command above (leave one out and its key leaves the block on the next
run):

- **`--explorer-model <alias>`** writes `role.explorer.model`. The alias is `sonnet`, `opus`, `haiku`
  or `fable`; anything else is a usage error (exit 2). A PreToolUse hook gives it to an `Explore`
  call that names no model, which nothing else can do: the built-in `Explore` ignores
  `CLAUDE_CODE_SUBAGENT_MODEL` and otherwise runs on the main session's model (`docs/role-map.md`).
- **`--implementer-model <model>`** writes `role.implementer.model`, the model of the implementer's
  `Task` fallback.
- **`--bulk "<command>"`** writes `role.bulk`, the command the bulk role runs.

A subagent that names no model and is not `Explore` takes its model from the environment variable
`CLAUDE_CODE_SUBAGENT_MODEL`, and the bootstrap cannot set it (it never reads or writes environment
variables). **Set it as a real environment variable of the session**: the environment's own
variables in its settings. Its value is a non-secret model name.

The `env` object of `~/.claude/settings.json` does not work for this variable. Measured in a cloud
session on Claude Code 2.1.322: other names in that object reach the session, this one does not
(neither the shell nor the subagent's model changes, from the user settings file or from
`--settings`), while the same value passed in the process environment does. A cloud session cannot
add it to its own environment either (the name is reserved there), so the owner adds it in the
environment's settings.

`plumb-doctor` shows the three keys and the variable under "routing targets".

## Codex and OpenCode in a cloud session

The Stop hook captures Codex and OpenCode at the end of each Claude turn. A run that is still going
when the turn ends, or that the container's reclaim cuts short, needs the two commands of
`docs/ledger.md` ("Runs that outlive a turn"). Add these lines to the setup script after the ones
above. Each is safe to run twice.

```bash
# plumb-ledger on PATH, resolved at each call (an update moves the plugin's install path)
cat > /usr/local/bin/plumb-ledger <<'SH'
#!/bin/sh
root=$(claude plugin list --json 2>/dev/null | python3 -c 'import json,sys; print(next(p["installPath"] for p in json.load(sys.stdin) if p["id"] == "plumb@plumb"))' 2>/dev/null)
[ -n "$root" ] || { echo "plumb-ledger: plumb is not installed" >&2; exit 127; }
exec "$root/bin/plumb-ledger" "$@"
SH
chmod +x /usr/local/bin/plumb-ledger

# A session-start hook that keeps one `watch` running: a reclaimed container loses at most 5 minutes
python3 - <<'PY'
import json, pathlib
path = pathlib.Path.home() / ".claude" / "settings.json"
data = json.loads(path.read_text()) if path.exists() else {}
command = "setsid nohup plumb-ledger watch --interval 300 >/dev/null 2>&1 </dev/null &"
groups = data.setdefault("hooks", {}).setdefault("SessionStart", [])
if not any("plumb-ledger watch" in h.get("command", "") for g in groups for h in g.get("hooks", [])):
    groups.append({"hooks": [{"type": "command", "command": command}]})
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(data, indent=2) + "\n")
PY

# How Claude starts Codex and OpenCode, in the user CLAUDE.md (replaced, not duplicated, on a re-run)
python3 - <<'PY'
import pathlib, re
path = pathlib.Path.home() / ".claude" / "CLAUDE.md"
begin, end = "<!-- plumb:ledger-run -->", "<!-- /plumb:ledger-run -->"
block = f"""{begin}
## Starting Codex and OpenCode
- Wrap them: `plumb-ledger run -- codex ...`, `plumb-ledger run -- opencode ...`, so what they use is recorded when they end.
- Run them in the foreground or as a background task of the Bash tool, never detached with `nohup` or a trailing `&`.
{end}
"""
text = path.read_text() if path.exists() else ""
text = re.sub(re.escape(begin) + r".*?" + re.escape(end) + r"\n?", "", text, flags=re.S)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(text + ("\n" if text and not text.endswith("\n") else "") + block)
PY
```

- The shim asks Claude Code where plumb is installed each time, so it follows plugin updates.
- The hook starts `watch` in its own session (`setsid`), so it outlives the hook, and returns at once. The hook fires again on resume,
  clear and compaction; the lock keeps one `watch` running.
- The setup script itself must not start `watch`: it runs before the session and has no cloud
  session id to record.
- Check it in a new session: `pgrep -af '[l]edger.py watch'` shows one process (`plumb-ledger` runs as
  `python3 .../scripts/ledger.py`, so the name `plumb-ledger` is not in the process list), and after a short Codex
  or OpenCode run `plumb-ledger report --since <today> --until <today>` lists its rows.

## Keep a cached environment current

Run this at the start of each session, from whatever the environment already runs there (a
session-start command or hook):

```bash
claude plugin marketplace update plumb && claude plugin update plumb@plumb
```

The running session keeps the version it loaded: run `/reload-plugins` to apply the update, or it
applies from the next session. Without this, a cached environment stays on its first version until
the setup script is edited.

## Attach the store

Exports reach the private store only when it is attached to the environment: add it under
Repositories in the environment's settings (where the environment offers it), or select it when
starting the session. Without that, `plumb-bootstrap` reports the store `NG`, records stay pending in
the container and are lost with it, and every report says that cloud sessions are not covered.

## Check a new session

Start a new session and run `plumb-doctor`. Expect `ok` for plumb's install, the routed judge (for
Codex, `ok` means it is also logged in) and
`ledger.store`, and `ok on-stop` for the export. After the first turn, the store has a branch for
the session (`git ls-remote <store> 'refs/heads/plumb-ledger/*'`).

## What stays manual

- Logging the judge in (a person must approve a device login).
- Attaching the store repository.
- Updating a cached environment (above). On your own machine, auto-update is in `/plugin`,
  Marketplaces, `plumb`, Enable auto-update (README, Updating).
