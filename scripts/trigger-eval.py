#!/usr/bin/env python3
"""Measure whether a skill fires on the prompts it should, and stays quiet on the rest.

Each case runs one headless session in plan mode (no edits) and stops at the first tool call that
is not a Skill call, so a case costs roughly one fixed prompt. The skills invoked up to that point
are the observation. Nothing is persisted as a resumable session.

Cases are a CSV with a header: id,prompt,expect
  expect = the skill that must fire (e.g. plumb:lead), or "-" meaning the skill under test must
  not fire. A case that expects another skill scores against that skill as well.
"""
import argparse, csv, json, os, signal, subprocess, sys, time
from pathlib import Path

PLUGIN = "plumb"


def observe(stream_lines):
    """Return (skills invoked before the first non-Skill tool, first non-Skill tool, usage)."""
    skills, first_other, usage = [], None, None
    for line in stream_lines:
        try:
            e = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if e.get("type") != "assistant":
            continue
        msg = e.get("message") or {}
        if usage is None and msg.get("usage"):
            u = msg["usage"]
            usage = sum(int(u.get(k) or 0) for k in
                        ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
        for c in msg.get("content") or []:
            if c.get("type") != "tool_use":
                continue
            if c.get("name") == "Skill":
                s = (c.get("input") or {}).get("skill")
                if s and s not in skills:
                    skills.append(s)
            else:
                return skills, c.get("name"), usage
    return skills, first_other, usage


def loaded_from(stream_lines, plugin):
    """Where the session loaded the plugin under test from, read off the init event."""
    for line in stream_lines:
        if '"subtype":"init"' not in line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        return next((p.get("path") for p in e.get("plugins") or [] if p.get("name") == plugin), None)
    return None


def run_case(prompt, model, cwd, timeout, raw_path, plugin_dir=None):
    cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose",
           "--permission-mode", "plan", "--no-session-persistence"]
    if model:
        cmd += ["--model", model]
    if plugin_dir:
        cmd += ["--plugin-dir", plugin_dir]
    lines, started = [], time.time()
    with open(raw_path, "w") as raw:
        p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, start_new_session=True)
        try:
            for line in p.stdout:
                raw.write(line)
                lines.append(line)
                if '"tool_use"' in line:
                    _, other, _ = observe(lines)
                    if other:
                        break
                if time.time() - started > timeout:
                    break
        finally:
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGTERM)
            p.wait()
    skills, other, usage = observe(lines)
    return {"skills": skills, "first_tool": other, "first_request_tokens": usage,
            "plugin_path": loaded_from(lines, PLUGIN),
            "seconds": round(time.time() - started, 1)}


def score(rows, skill):
    tp = sum(1 for r in rows if r["expect"] == skill and skill in r["skills"])
    fn = sum(1 for r in rows if r["expect"] == skill and skill not in r["skills"])
    fp = sum(1 for r in rows if r["expect"] != skill and skill in r["skills"])
    tn = sum(1 for r in rows if r["expect"] != skill and skill not in r["skills"])
    other = [r for r in rows if r["expect"] not in (skill, "-")]
    routed = sum(1 for r in other if r["expect"] in r["skills"])
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    return {"skill": skill, "tp": tp, "fn": fn, "fp": fp, "tn": tn, "precision": prec,
            "recall": rec, "near_miss_routed": f"{routed}/{len(other)}"}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cases", required=True, help="CSV with id,prompt,expect")
    ap.add_argument("--skill", required=True, help="skill under test, e.g. plumb:lead")
    ap.add_argument("--model", action="append", default=[], help="repeatable; default: session default")
    ap.add_argument("--cwd", default=os.getcwd(), help="project the sessions start in")
    ap.add_argument("--out", required=True, help="run directory (raw streams + results.jsonl)")
    ap.add_argument("--timeout", type=int, default=180, help="seconds per case")
    ap.add_argument("--only", help="comma-separated case ids")
    ap.add_argument("--plugin-dir", help="load this checkout of the plugin instead of the installed one")
    a = ap.parse_args()

    cases = list(csv.DictReader(open(a.cases, newline="")))
    if a.only:
        keep = set(a.only.split(","))
        cases = [c for c in cases if c["id"] in keep]
    if not cases:
        sys.exit("no cases")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    summary = []
    for model in a.model or [""]:
        rows = []
        for c in cases:
            tag = f"{model or 'default'}-{c['id']}"
            obs = run_case(c["prompt"], model, a.cwd, a.timeout, out / f"{tag}.jsonl", a.plugin_dir)
            if a.plugin_dir and obs["plugin_path"] != str(Path(a.plugin_dir).resolve()):
                sys.exit(f"{tag}: the session loaded {PLUGIN} from {obs['plugin_path']}, not {a.plugin_dir}")
            row = {"model": model or "default", "id": c["id"], "expect": c["expect"], **obs}
            row["pass"] = (c["expect"] in obs["skills"]) if c["expect"] != "-" else (a.skill not in obs["skills"])
            if c["expect"] not in (a.skill, "-"):
                row["pass"] = row["pass"] and a.skill not in obs["skills"]
            rows.append(row)
            with open(out / "results.jsonl", "a") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(f"  {'ok' if row['pass'] else 'NG':4} {tag:28} expect={c['expect']:18} "
                  f"got={','.join(obs['skills']) or '-'} first={obs['first_tool']}", flush=True)
        s = score(rows, a.skill)
        s["model"] = model or "default"
        tok = [r["first_request_tokens"] for r in rows if r["first_request_tokens"]]
        s["first_request_tokens_median"] = sorted(tok)[len(tok) // 2] if tok else None
        summary.append(s)
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    for s in summary:
        p = "-" if s["precision"] is None else f"{s['precision']:.2f}"
        r = "-" if s["recall"] is None else f"{s['recall']:.2f}"
        print(f"{s['model']}: precision {p} recall {r} (tp {s['tp']} fn {s['fn']} fp {s['fp']} "
              f"tn {s['tn']}) near-miss routed {s['near_miss_routed']} "
              f"first-request tokens p50 {s['first_request_tokens_median']}")
    sys.exit(0 if all(s["fp"] == 0 and s["fn"] == 0 for s in summary) else 1)


if __name__ == "__main__":
    main()
