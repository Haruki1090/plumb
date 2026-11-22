"""Reduce cockpit events to lane state, acceptance evidence and guard decisions."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from cockpit import Invalid

COLUMNS = ("lane", "work", "kind", "state", "role", "attempt", "head", "last_check", "stop_code", "next")
NEXT = {"ready": "start", "running": "collect", "collected": "observe or adjudicate",
        "reviewed": "guard or close", "held": "inspect guard", "closed": ""}


@dataclass
class Attempt:
    seq: int
    role: str
    worktree: str = ""
    base: str = ""
    head: str = ""
    verdict: str = ""
    observations: dict[str, str] = field(default_factory=dict)
    progress: bool = False
    uncommitted: bool = False
    outside: list[str] = field(default_factory=list)


@dataclass
class Lane:
    name: str
    work: str
    kind: str
    allow_paths: list[str]
    acceptance: list[str]
    locks: list[str]
    brief: str
    report: str = ""
    brief_digest: str = ""
    attempts: list[Attempt] = field(default_factory=list)
    last_check: str = ""
    closed: bool = False

    @property
    def current(self):
        return self.attempts[-1] if self.attempts else None

    @property
    def state(self):
        attempt = self.current
        if self.closed:
            return "closed"
        if not attempt:
            return "ready"
        if attempt.verdict:
            return "reviewed"
        return "collected" if attempt.head else "running"


@dataclass
class Work:
    holds: dict[str, str] = field(default_factory=dict)
    unclassified: set[tuple[int, str]] = field(default_factory=set)
    passed: dict[str, int] = field(default_factory=dict)
    failed: dict[str, int] = field(default_factory=dict)
    causes: dict[str, int] = field(default_factory=dict)
    completed: list[Attempt] = field(default_factory=list)
    last_resume: dict = field(default_factory=dict)

    def reasons(self):
        reasons = dict(self.holds)
        if self.unclassified:
            reasons.setdefault("unclassified", "a failing observation needs a cause")
        latest = sorted(self.completed, key=lambda attempt: attempt.seq)[-3:]
        if len(latest) == 3 and not any(attempt.progress for attempt in latest):
            reasons.setdefault("no-progress", "three attempts finished without a newly passing acceptance item")
        return reasons

    def observe(self, lane, attempt, data):
        ac, result = data["ac"], data["result"]
        previous_pass = self.passed.get(ac)
        key = (attempt.seq, ac)
        attempt.observations[ac] = result
        lane.last_check = f"{ac}={result}"
        if result == "pass":
            attempt.progress |= previous_pass is None
            self.passed[ac] = min(attempt.seq, previous_pass) if previous_pass is not None else attempt.seq
            if self.failed.get(ac, 0) > attempt.seq:
                self.holds.setdefault("regression", f"{ac} failed in a later attempt")
            return
        self.failed[ac] = max(self.failed.get(ac, 0), attempt.seq)
        if previous_pass is not None and previous_pass < attempt.seq:
            self.holds.setdefault("regression", f"{ac} passed in an earlier attempt")
        cause = data.get("cause")
        if not cause:
            self.unclassified.add(key)
        else:
            self.unclassified.discard(key)
            first = self.causes.setdefault(cause, attempt.seq)
            if first != attempt.seq:
                self.holds.setdefault("same-cause", f"{cause} was observed in two attempts")

    def adjudicate(self, attempt, verdict):
        attempt.verdict = verdict
        self.completed.append(attempt)


def outside_range(paths, allowed):
    return sorted(path for path in paths if not any(
        path.startswith(rule) if rule.endswith("/") else path == rule for rule in allowed
    ))


def replay(events):
    lanes, works = {}, {}
    for event in events:
        name, work_id, data, event_type = (event[key] for key in ("lane", "work", "data", "type"))
        try:
            if event_type == "lane-added":
                if name in lanes:
                    raise Invalid(f"lane already exists: {name}")
                lanes[name] = Lane(name, work_id, data["kind"], data["allow_paths"], data["acceptance"],
                                   data.get("locks", []), data["brief"], data.get("report", ""),
                                   data.get("brief_digest", ""))
                works.setdefault(work_id, Work())
                continue
            lane = lanes[name]
            if lane.work != work_id or lane.closed:
                raise Invalid(f"event cannot change lane {name}")
            work = works[work_id]
            if event_type == "attempt-started":
                if lane.state not in ("ready", "reviewed") or data["attempt"] != len(lane.attempts) + 1:
                    raise Invalid(f"invalid attempt start for {name}")
                lane.attempts.append(Attempt(event["seq"], data["role"], data.get("worktree", ""), data.get("base", "")))
                lane.last_check = ""
            elif event_type in ("attempt-collected", "observed", "adjudicated"):
                attempt = lane.current
                if not attempt or data["attempt"] != len(lane.attempts):
                    raise Invalid(f"event does not refer to the current attempt of {name}")
                if event_type == "attempt-collected":
                    if attempt.head:
                        raise Invalid(f"attempt already collected for {name}")
                    attempt.head = data["head"]
                    attempt.uncommitted = data.get("uncommitted", False)
                    attempt.outside = outside_range(data["changed_paths"], lane.allow_paths)
                    if attempt.outside:
                        work.holds.setdefault("out-of-range", "paths outside the brief: " + ", ".join(attempt.outside))
                        work.adjudicate(attempt, "miss")
                elif not attempt.head:
                    raise Invalid(f"collect the attempt before adding evidence for {name}")
                elif event_type == "observed":
                    if data["ac"] not in lane.acceptance or data["result"] not in ("pass", "fail"):
                        raise Invalid(f"invalid observation for {name}")
                    work.observe(lane, attempt, data)
                else:
                    if attempt.verdict or data["verdict"] not in ("hit", "miss", "inconclusive"):
                        raise Invalid(f"invalid adjudication for {name}")
                    work.adjudicate(attempt, data["verdict"])
            elif event_type == "held":
                work.holds[data["code"]] = data["reason"]
            elif event_type == "resumed":
                work.holds.clear()
                work.completed.clear()
                work.last_resume = data
            elif event_type == "closed":
                if not lane.current or data["head"] != lane.current.head:
                    raise Invalid(f"invalid closing head for {name}")
                lane.closed = True
            else:
                raise Invalid(f"unknown event type: {event_type}")
        except (TypeError, KeyError, AttributeError) as exc:
            raise Invalid(f"invalid {event_type} event for {name} at sequence {event['seq']}") from exc
    return lanes, works


def rows(lanes, works):
    result = []
    for lane in lanes.values():
        attempt = lane.current
        reasons = works[lane.work].reasons() if not lane.closed else {}
        state = "held" if reasons else lane.state
        result.append(dict(zip(COLUMNS, (lane.name, lane.work, lane.kind, state, attempt.role if attempt else "",
                                         len(lane.attempts), attempt.head if attempt else "", lane.last_check,
                                         next(iter(reasons), ""), NEXT[state]))))
    return result


def tsv(view):
    buffer = io.StringIO()
    table = csv.DictWriter(buffer, fieldnames=COLUMNS, delimiter="\t", lineterminator="\n")
    table.writeheader()
    table.writerows(view)
    return buffer.getvalue()
