#!/usr/bin/env python3
"""plumb-upstream-diff: what moved upstream since the commit NOTICE records, and what has no recorded decision.

    plumb-upstream-diff [--unrecorded] [--json] [--notice <file>] [--scope <file>]

plumb began as a port of a plugin that lives in a subdirectory of a public GitHub repository. NOTICE names it
and carries one machine-readable line, written by a person after reading the upstream:

    Upstream last read: <owner>/<repo>@<commit> path <dir> version <version> on <YYYY-MM-DD>

Default run: ask the forge for the compare between that commit and the default branch head, and list the files
under `<dir>/` that changed, as `status<TAB>path` rows (added, modified, removed; a rename shows `old -> new`),
grouped skills, playbooks, principles, agents, docs, other, then one summary line with the counts and the
upstream head SHA. Nothing changed prints `upstream: no changes under <dir> since <commit>`.

`--unrecorded`: of the upstream skill directory names, playbook file stems, agent file stems and guide page
stems at the upstream head, list those whose name does not occur anywhere in docs/scope.md (principle names
are compared with their `principle-` prefix stripped). That is how a new upstream item with no recorded
decision is found. The match is a whole-name match anywhere in the text, so a name that is also an ordinary
word ("how") counts as recorded as soon as the word appears.

A compare lists at most 300 files: at that count the summary line and the JSON (`"truncated": true`) say the list
was truncated by the forge and the rest has to be read in a clone, and a list that may be cut short is never
shown as complete.

`--json` prints JSON for either view. It never writes, never edits NOTICE (moving the recorded commit forward
is a person's edit after reading) and never fails the caller: a missing, unreachable or rate-limited gh gives
`remote: unavailable` and exit 0. Exit 2 is for a missing or malformed NOTICE line, or an unreadable file.
`parse_notice`, `changes_from_files` and `unrecorded_names` are pure functions of parsed data; `main()` only
asks the forge and prints. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
sys.path.insert(0, str(HERE))
from run_view import run_gh  # noqa: E402

BUDGET_SECONDS = 30.0
PAGE_SIZE = 100
MAX_PAGES = 30
FILES_CAP = 300  # the compare endpoint lists at most 300 files, however many changed, and in practice on the first page
TRUNCATED_NOTE = f"list truncated by the forge at {FILES_CAP} files; read the rest in a clone"
MARKER = "Upstream last read:"
NOTICE_LINE = re.compile(
    r"Upstream last read: (?P<repo>[A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*)@(?P<commit>[0-9a-f]{7,40})"
    r" path (?P<path>[A-Za-z0-9_.][\w./-]*) version (?P<version>[0-9][\w.+-]*) on (?P<date>\d{4}-\d{2}-\d{2})")
GROUPS = ("skills", "playbooks", "principles", "agents", "docs", "other")
KINDS = ("skill", "playbook", "principle", "agent", "guide")
STATUSES = {"added": "added", "copied": "added", "removed": "removed", "renamed": "renamed",
            "modified": "modified", "changed": "modified", "unchanged": "modified"}
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


class NoticeError(ValueError):
    """The NOTICE line is missing or malformed."""


def plain(text: Any) -> str:
    """A forge string made safe for a terminal: every control character is `?`."""
    return CONTROL.sub("?", str(text))


# ---------------------------------------------------------------- NOTICE

def parse_notice(text: str) -> dict[str, str]:
    """{repo, commit, path, version, date} from the one `Upstream last read:` line. NoticeError when the
    line is absent, appears more than once, or does not match the format exactly."""
    lines = [line for line in text.splitlines() if line.startswith(MARKER)]
    if not lines:
        raise NoticeError(f"NOTICE has no `{MARKER}` line")
    if len(lines) > 1:
        raise NoticeError(f"NOTICE has {len(lines)} `{MARKER}` lines; exactly one is expected")
    found = NOTICE_LINE.fullmatch(lines[0])
    if not found:
        raise NoticeError("the `Upstream last read:` line in NOTICE is malformed; expected "
                          "`Upstream last read: <owner>/<repo>@<commit> path <dir> version <version> on <YYYY-MM-DD>`")
    info = found.groupdict()
    try:
        datetime.strptime(info["date"], "%Y-%m-%d")
    except ValueError:
        raise NoticeError(f"the date {info['date']} in the `Upstream last read:` line is not a calendar date") from None
    info["path"] = info["path"].strip("/")
    if not info["path"] or ".." in info["path"].split("/"):
        raise NoticeError("the path in the `Upstream last read:` line must be a plain subdirectory")
    return info


# ---------------------------------------------------------------- changed files

def relative(path: str, root: str) -> str | None:
    """`path` below the directory `root`, or None when it is not below it."""
    prefix = root + "/"
    return path[len(prefix):] if path.startswith(prefix) and len(path) > len(prefix) else None


def classify(rel: str) -> str:
    """The group of a file, from its path below the upstream directory."""
    parts = rel.split("/")
    if "playbooks" in parts[:-1]:
        return "playbooks"
    if parts[0] == "skills" and len(parts) >= 3:
        return "principles" if parts[1].startswith("principle-") else "skills"
    if parts[0] == "agents" and len(parts) >= 2:
        return "agents"
    if parts[0] == "docs" and len(parts) >= 2:
        return "docs"
    return "other"


def changes_from_files(files: list[Any], root: str) -> list[dict[str, Any]]:
    """The entries of the forge's compare `files` that touch `root/`, as rows {group, status, path, previous_path},
    grouped in GROUPS order and sorted by path inside a group. A rename counts when either name is under `root`;
    it is grouped by the new name when that is under `root`, else by the old one."""
    rows = []
    for raw in files:
        if not isinstance(raw, dict) or not isinstance(raw.get("filename"), str):
            continue
        name = raw["filename"]
        old = raw.get("previous_filename") if isinstance(raw.get("previous_filename"), str) else None
        status = STATUSES.get(str(raw.get("status")), "modified")
        rel = relative(name, root) or (relative(old, root) if old else None)
        if rel is None:
            continue
        rows.append({"group": classify(rel), "status": status, "path": name,
                     "previous_path": old if status == "renamed" else None})
    rows.sort(key=lambda r: (GROUPS.index(r["group"]), r["path"]))
    return rows


def build_changes(notice: dict[str, str], head: str | None, files: list[Any] | None) -> dict[str, Any]:
    """The whole default answer. `files` is None when the forge did not answer."""
    doc: dict[str, Any] = {"remote": "ok" if files is not None and head else "unavailable", "repo": notice["repo"],
                           "path": notice["path"], "since": notice["commit"], "version": notice["version"],
                           "read_on": notice["date"]}
    if doc["remote"] != "ok":
        return doc
    rows = changes_from_files(files or [], notice["path"])
    doc["head"] = head
    doc["changes"] = rows
    doc["counts"] = {group: sum(1 for r in rows if r["group"] == group) for group in GROUPS}
    doc["total"] = len(rows)
    doc["truncated"] = len(files or []) >= FILES_CAP  # the forge stops listing here: what is missing is unknown
    return doc


def render_changes(doc: dict[str, Any]) -> str:
    if doc["remote"] != "ok":
        return "remote: unavailable"
    note = f"; {TRUNCATED_NOTE}" if doc["truncated"] else ""
    if not doc["changes"]:
        if doc["truncated"]:
            return f"upstream: no changes under {doc['path']} since {doc['since']} in the files listed{note}"
        return f"upstream: no changes under {doc['path']} since {doc['since']}"
    lines: list[str] = []
    for group in GROUPS:
        rows = [r for r in doc["changes"] if r["group"] == group]
        if not rows:
            continue
        lines.append(f"# {group} ({len(rows)})")
        for r in rows:
            shown = f"{plain(r['previous_path'])} -> {plain(r['path'])}" if r["previous_path"] else plain(r["path"])
            lines.append(f"{r['status']}\t{shown}")
    counts = ", ".join(f"{group} {doc['counts'][group]}" for group in GROUPS)
    lines.append(f"upstream: {doc['total']} files changed under {doc['path']} since {doc['since']} ({counts}); head {doc['head']}{note}")
    return "\n".join(lines)


# ---------------------------------------------------------------- names with no recorded decision

def unrecorded_names(tree: list[Any], root: str) -> list[dict[str, str]]:
    """Every upstream item the harness names, as {kind, name, label}, from the forge's tree entries. `name` is the
    string looked up in scope.md (a principle without its `principle-` prefix); `label` is the upstream name.
    Order: KINDS, then name."""
    found: dict[tuple[str, str], str] = {}
    for entry in tree:
        if not isinstance(entry, dict) or entry.get("type") != "blob" or not isinstance(entry.get("path"), str):
            continue
        rel = relative(entry["path"], root)
        if rel is None:
            continue
        parts = rel.split("/")
        stem = parts[-1][:-3] if parts[-1].endswith(".md") else None
        if "playbooks" in parts[:-1]:
            if stem:
                found[("playbook", stem)] = stem
        elif parts[0] == "skills" and len(parts) >= 3:
            if parts[1].startswith("principle-"):
                found[("principle", parts[1][len("principle-"):])] = parts[1]
            else:
                found[("skill", parts[1])] = parts[1]
        elif parts[0] == "agents" and len(parts) == 2 and stem:
            found[("agent", stem)] = stem
        elif parts[:2] == ["docs", "guide"] and len(parts) == 3 and stem and stem != "README":
            found[("guide", stem)] = stem
    return [{"kind": kind, "name": name, "label": label}
            for (kind, name), label in sorted(found.items(), key=lambda kv: (KINDS.index(kv[0][0]), kv[0][1]))]


def mentioned(name: str, text: str) -> bool:
    """Whether `name` occurs in `text` as a whole name (not as part of a longer word or hyphenated name)."""
    return re.search(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", text) is not None


def build_unrecorded(notice: dict[str, str], head: str | None, tree: list[Any] | None, scope_text: str) -> dict[str, Any]:
    doc: dict[str, Any] = {"remote": "ok" if tree is not None and head else "unavailable", "repo": notice["repo"],
                           "path": notice["path"]}
    if doc["remote"] != "ok":
        return doc
    names = unrecorded_names(tree or [], notice["path"])
    missing = [n for n in names if not mentioned(n["name"], scope_text)]
    doc["head"] = head
    doc["checked"] = len(names)
    doc["unrecorded"] = [{"kind": n["kind"], "name": n["label"]} for n in missing]
    doc["counts"] = {kind: sum(1 for n in missing if n["kind"] == kind) for kind in KINDS}
    return doc


def render_unrecorded(doc: dict[str, Any]) -> str:
    if doc["remote"] != "ok":
        return "remote: unavailable"
    if not doc["unrecorded"]:
        return f"upstream: every one of {doc['checked']} names under {doc['path']} is in docs/scope.md (head {doc['head']})"
    lines = [f"{n['kind']}\t{plain(n['name'])}" for n in doc["unrecorded"]]
    counts = ", ".join(f"{kind} {doc['counts'][kind]}" for kind in KINDS)
    lines.append(f"upstream: {len(doc['unrecorded'])} of {doc['checked']} names under {doc['path']} are not in docs/scope.md "
                 f"({counts}); head {doc['head']}")
    return "\n".join(lines)


# ---------------------------------------------------------------- the forge

def api_json(gh, args: list[str], deadline: float) -> Any:
    """The parsed JSON of one `gh api` call; ValueError when gh failed or the answer is not JSON."""
    done = gh(["api", *args], str(PLUGIN), max(deadline - time.monotonic(), 0.1))
    if done.returncode != 0:
        raise ValueError("gh api failed")
    return json.loads(done.stdout)


def fetch_head(repo: str, deadline: float, gh=run_gh) -> str:
    """The SHA of the default branch head (`HEAD` resolves to it), or ValueError."""
    done = gh(["api", "-H", "Accept: application/vnd.github.sha", f"repos/{repo}/commits/HEAD"], str(PLUGIN),
              max(deadline - time.monotonic(), 0.1))
    sha = done.stdout.strip() if done.returncode == 0 else ""
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("no head SHA")
    return sha


def fetch_files(repo: str, base: str, head: str, deadline: float, gh=run_gh) -> list[Any]:
    """The files of the compare `base...head`; ValueError when the first page fails or is not a file list. The
    forge serves the list on the first page and stops at FILES_CAP files, so a later page with no `files` (or an
    empty list) is the normal end, not a failure. At FILES_CAP files it stops asking: whatever is missing is
    unknowable here, and `build_changes` says the list is truncated."""
    files: list[Any] = []
    for page in range(1, MAX_PAGES + 1):
        data = api_json(gh, [f"repos/{repo}/compare/{base}...{head}?per_page={PAGE_SIZE}&page={page}"], deadline)
        if not isinstance(data, dict):
            raise ValueError("the compare answer is not an object")
        chunk = data.get("files")
        if page > 1 and (chunk is None or chunk == []):
            break
        if not isinstance(chunk, list):
            raise ValueError("no files in the compare answer")
        files += chunk
        if len(chunk) < PAGE_SIZE or len(files) >= FILES_CAP:
            break
    return files


def fetch_tree(repo: str, head: str, deadline: float, gh=run_gh) -> list[Any]:
    """The recursive tree at `head`; ValueError when the forge did not answer or the answer was cut short."""
    data = api_json(gh, [f"repos/{repo}/git/trees/{head}?recursive=1"], deadline)
    tree = data.get("tree") if isinstance(data, dict) else None
    if not isinstance(tree, list) or data.get("truncated"):
        raise ValueError("no complete tree")
    return tree


# ---------------------------------------------------------------- command line

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="plumb-upstream-diff", description=__doc__.splitlines()[0])
    parser.add_argument("--unrecorded", action="store_true",
                        help="list upstream names (skills, playbooks, principles, agents, guide pages) absent from docs/scope.md")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    parser.add_argument("--notice", default=str(PLUGIN / "NOTICE"), help="the file holding the `Upstream last read:` line")
    parser.add_argument("--scope", default=str(PLUGIN / "docs" / "scope.md"), help="the file `--unrecorded` looks names up in")
    args = parser.parse_args(argv)
    try:
        notice = parse_notice(Path(args.notice).read_text(encoding="utf-8"))
        scope_text = Path(args.scope).read_text(encoding="utf-8") if args.unrecorded else ""
    except NoticeError as error:
        print(f"plumb-upstream-diff: {error}", file=sys.stderr)
        return 2
    except (OSError, UnicodeDecodeError) as error:
        print(f"plumb-upstream-diff: cannot read {getattr(error, 'filename', None) or 'a file'}: {error.__class__.__name__}",
              file=sys.stderr)
        return 2

    deadline = time.monotonic() + BUDGET_SECONDS
    head: str | None = None
    payload: list[Any] | None = None
    try:
        head = fetch_head(notice["repo"], deadline, gh=run_gh)
        if args.unrecorded:
            payload = fetch_tree(notice["repo"], head, deadline, gh=run_gh)
        else:
            payload = fetch_files(notice["repo"], notice["commit"], head, deadline, gh=run_gh)
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        head = payload = None
    if args.unrecorded:
        doc = build_unrecorded(notice, head, payload, scope_text)
        text = render_unrecorded(doc)
    else:
        doc = build_changes(notice, head, payload)
        text = render_changes(doc)
    print(json.dumps(doc, indent=2, ensure_ascii=False) if args.json else text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
