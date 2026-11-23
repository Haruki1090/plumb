"""Read a lane specification and render or check its Markdown brief."""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath

from cockpit import Invalid, ROOT, identifier, kind_info, nonempty, store_name

SECTIONS = ("Kind", "Range", "Material", "Do not touch", "Acceptance", "Report path",
            "Forbidden means", "Return")
ACCEPTANCE_ITEM = re.compile(r"- \[([A-Za-z0-9][A-Za-z0-9_.-]*)\] .+")
WORKER_INSTRUCTION = re.compile(r"Read (.+) before anything else\.")
WORKER_REFERENCE = Path("skills/cockpit/references/worker.md")


def brief_path(directory, lane, rev):
    suffix = f".{rev}" if rev else ""
    return directory / "briefs" / f"{lane}{suffix}.md"


def worker_instruction():
    return f"Read {ROOT / WORKER_REFERENCE} before anything else."


def recognized_worker(worker):
    if not worker.is_absolute() or not worker.is_file():
        return False
    if worker.parts[-4:] != WORKER_REFERENCE.parts:
        return False
    root = worker.parents[3].resolve()
    if worker.resolve() != root / WORKER_REFERENCE:
        return False
    if root == ROOT and (root / ".git").exists():
        return True
    try:
        manifest = json.loads((root / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(manifest, dict) and manifest.get("name") == "plumb"


def one_line(value, field):
    text = nonempty(value, field)
    if len(text.splitlines()) != 1 or any(char in value for char in "\r\n"):
        raise Invalid(f"{field} must be one line")
    return text


def text_list(value, field):
    if not isinstance(value, list):
        raise Invalid(f"{field} must be a list")
    return [one_line(item, field) for item in value]


def read_spec(path):
    spec = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict):
        raise Invalid("the brief spec must be a JSON object")
    kind = identifier(spec.get("kind"), "kind")
    info = kind_info(kind)
    paths = text_list(spec.get("allow_paths"), "allow_paths")
    for value in paths:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or path.as_posix() == "." or path.as_posix() != value.removesuffix("/"):
            raise Invalid(f"allow_paths needs a repository-relative file or directory ending in '/': {value!r}")
    if paths and info["read_only"] == "true":
        raise Invalid(f"{kind} requires an empty allow_paths list")
    spec["allow_paths"] = paths
    spec["title"] = one_line(spec.get("title"), "title")
    spec["material"] = nonempty(spec.get("material"), "material")
    for field in ("do_not_touch", "forbidden_means"):
        spec[field] = text_list(spec.get(field), field)
        if not spec[field]:
            raise Invalid(f"{field} must list at least one entry")
    report = one_line(spec.get("report_path"), "report_path")
    if not Path(report).is_absolute():
        raise Invalid("report_path must be absolute")
    spec["report_path"] = report
    locks = spec.get("locks", [])
    if not isinstance(locks, list):
        raise Invalid("locks must be a list")
    spec["locks"] = sorted({store_name(name, "lock name") for name in locks})
    items = spec.get("acceptance")
    if not isinstance(items, list) or not items:
        raise Invalid("acceptance must list at least one item")
    ids = set()
    for item in items:
        if not isinstance(item, dict):
            raise Invalid("each acceptance item needs id, description and check")
        ac = identifier(item.get("id"), "acceptance id")
        if ac in ids:
            raise Invalid(f"duplicate acceptance id: {ac}")
        ids.add(ac)
        for field in ("description", "check"):
            item[field] = one_line(item.get(field), f"{ac} {field}")
    return spec


def bullets(items):
    return "\n".join(f"- {item}" for item in items)


def render(lane, spec):
    acceptance = "\n".join(f'- [{item["id"]}] {item["description"]}\n  Check: {item["check"]}'
                           for item in spec["acceptance"])
    contents = {
        "Kind": spec["kind"],
        "Range": bullets(spec["allow_paths"]) or "Read-only. No file changes.",
        "Material": spec["material"],
        "Do not touch": bullets(spec["do_not_touch"]),
        "Acceptance": acceptance,
        "Report path": spec["report_path"],
        "Forbidden means": bullets(spec["forbidden_means"]),
        "Return": "Write the report with changes, the commands run, exit statuses, and open caveats.\n"
                  "Reply with the report path.",
    }
    opening = f'{worker_instruction()}\n\n# Lane {lane}: {spec["title"]}\n'
    return opening + "".join(f"\n## {heading}\n\n{contents[heading]}\n" for heading in SECTIONS)


def brief_sections(brief):
    sections = {}
    issues = []
    heading = None
    # Material can include command transcripts. A heading inside a fenced block is literal.
    fence = None
    for line in brief.splitlines():
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence:
            if marker and marker[1].startswith(fence) and not marker[2].strip():
                fence = None
        elif marker:
            fence = marker[1]
        elif line.startswith("## "):
            heading = line[3:].strip()
            if heading in sections and heading in SECTIONS:
                issues.append(f"duplicate section: {heading}")
            sections[heading] = []
            continue
        if heading is not None:
            sections[heading].append(line)
    return sections, issues


def do_not_touch_paths(brief):
    sections, _ = brief_sections(brief)
    for line in sections.get("Do not touch", []):
        if line.startswith("- "):
            value = line[2:].strip()
            yield value[1:-1] if value.startswith("`") and value.endswith("`") else value


def problems(brief):
    sections, issues = brief_sections(brief)
    opening = WORKER_INSTRUCTION.fullmatch(brief.partition("\n")[0])
    worker = Path(opening[1]) if opening else None
    if worker is None or not recognized_worker(worker):
        issues.insert(0, "first line must refer to the cockpit worker.md in a recognized plumb installation")
    for heading in SECTIONS:
        if heading not in sections:
            issues.append(f"missing section: {heading}")
        elif not any(line.strip() for line in sections[heading]):
            issues.append(f"empty section: {heading}")
    report = "\n".join(sections.get("Report path", [])).strip()
    if not report or len(report.splitlines()) != 1 or not Path(report).is_absolute() or "\x00" in report:
        issues.append("missing absolute report path")
    acceptance = [line for line in sections.get("Acceptance", []) if line.strip()]
    if not acceptance:
        return issues
    ids = set()
    seen_check = False
    ac = None
    for line in acceptance:
        if item := ACCEPTANCE_ITEM.fullmatch(line):
            if ac and not seen_check:
                issues.append(f"acceptance item {ac} has no check command")
            ac, seen_check = item[1], False
            if ac in ids:
                issues.append(f"duplicate acceptance id: {ac}")
            ids.add(ac)
        elif ac and line.startswith("  Check:"):
            seen_check |= bool(line.removeprefix("  Check:").strip())
        else:
            issues.append("acceptance items must use '- [id] description' followed by '  Check: command'")
    if ac and not seen_check:
        issues.append(f"acceptance item {ac} has no check command")
    return issues
