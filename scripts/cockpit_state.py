"""Reduce cockpit events to lane state, acceptance evidence and guard decisions."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from cockpit import ROUTE_LOG, Invalid, kinds, nonempty, replace_text, store_name

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
    inventory: dict = field(default_factory=dict)
    collected_untracked: set[str] | None = None
    observation_seq: int = 0
    completion_seq: int = 0
    abandoned: bool = False

    @property
    def window_seq(self):
        return self.observation_seq or self.completion_seq


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
    brief_seq: int = 0
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
    resumes: list[dict] = field(default_factory=list)

    @property
    def last_resume(self):
        return self.resumes[-1] if self.resumes else {}

    def reasons(self):
        reasons = dict(self.holds)
        if self.unclassified:
            reasons.setdefault("unclassified", "a failing observation needs a cause")
        latest = sorted(self.completed, key=lambda attempt: attempt.window_seq)[-3:]
        if len(latest) == 3 and not any(attempt.progress for attempt in latest):
            reasons.setdefault("no-progress", "three attempts finished without a newly passing acceptance item")
        return reasons

    def observe(self, lane, attempt, data, seq):
        ac, result = data["ac"], data["result"]
        attempt.observation_seq = attempt.observation_seq or seq
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
            self.classify(attempt, ac, cause)

    def can_classify(self, attempt, ac, result, cause):
        return result == "fail" and cause and (attempt.seq, ac) in self.unclassified

    def classify(self, attempt, ac, cause):
        self.unclassified.discard((attempt.seq, ac))
        first = self.causes.setdefault(cause, attempt.seq)
        if first != attempt.seq:
            self.holds.setdefault("same-cause", f"{cause} was observed in two attempts")

    def adjudicate(self, attempt, verdict, seq):
        attempt.verdict = verdict
        attempt.completion_seq = seq
        self.completed.append(attempt)


def outside_range(paths, allowed):
    return sorted(path for path in paths if not any(
        path.startswith(rule) if rule.endswith("/") else path == rule for rule in allowed
    ))


def guard_reasons(lane, work):
    return {"closed": "the lane is closed"} if lane.closed else work.reasons()


def string_list(data, field):
    value = data[field]
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise Invalid(f"{field} must be a list of strings")
    return value


def replay(events):
    lanes, works = {}, {}
    known_kinds = kinds()
    for event in events:
        name, work_id, data, event_type = (event[key] for key in ("lane", "work", "data", "type"))
        try:
            if event_type in ("lane-added", "brief-registered"):
                if name != store_name(name, "lane"):
                    raise Invalid(f"noncanonical lane name: {name}")
                previous = lanes.get(name)
                if event_type == "lane-added" and previous:
                    raise Invalid(f"lane already exists: {name}")
                if event_type == "brief-registered" and (
                    not previous or previous.work != work_id or previous.state not in ("ready", "reviewed")
                ):
                    raise Invalid(f"cannot register a brief revision for {name}")
                if not isinstance(data["kind"], str) or data["kind"] not in known_kinds:
                    raise Invalid("invalid kind")
                locks = [store_name(lock, "lock name") for lock in string_list(data, "locks")] if "locks" in data else []
                lanes[name] = Lane(name, work_id, data["kind"], string_list(data, "allow_paths"),
                                   string_list(data, "acceptance"),
                                   locks, nonempty(data["brief"], "brief"), data.get("report", ""),
                                   data.get("brief_digest", ""), event["seq"],
                                   attempts=previous.attempts if previous else [])
                works.setdefault(work_id, Work())
                continue
            lane = lanes[name]
            if lane.work != work_id or lane.closed:
                raise Invalid(f"event cannot change lane {name}")
            work = works[work_id]
            if event_type == "attempt-started":
                if lane.state not in ("ready", "reviewed") or data["attempt"] != len(lane.attempts) + 1:
                    raise Invalid(f"invalid attempt start for {name}")
                if not isinstance(data["role"], str):
                    raise Invalid("role must be a string")
                inventory = data.get("inventory", {})
                if isinstance(inventory, list):
                    # Older starts recorded path names without content fingerprints.
                    inventory = dict.fromkeys(string_list(data, "inventory"))
                elif not isinstance(inventory, dict):
                    raise Invalid("inventory must be an object")
                lane.attempts.append(Attempt(event["seq"], data["role"], data.get("worktree", ""),
                                             data.get("base", ""), inventory=inventory))
                lane.last_check = ""
            elif event_type in ("attempt-collected", "observed", "adjudicated", "abandoned"):
                attempt = lane.current
                if not attempt or data["attempt"] != len(lane.attempts):
                    raise Invalid(f"event does not refer to the current attempt of {name}")
                if event_type == "attempt-collected":
                    if lane.state != "running":
                        raise Invalid(f"collection requires a running attempt for {name}")
                    attempt.head = nonempty(data["head"], "head")
                    attempt.uncommitted = data.get("uncommitted", False)
                    if "untracked" in data:
                        attempt.collected_untracked = set(string_list(data, "untracked"))
                    attempt.outside = outside_range(string_list(data, "changed_paths"), lane.allow_paths)
                    if data.get("verdict") != ("miss" if attempt.outside else None):
                        raise Invalid(f"invalid collection verdict for {name}")
                    if attempt.outside:
                        work.holds.setdefault("out-of-range", "paths outside the brief: " + ", ".join(attempt.outside))
                        work.adjudicate(attempt, "miss", event["seq"])
                elif event_type == "abandoned":
                    if attempt.verdict or data["verdict"] not in ("miss", "inconclusive"):
                        raise Invalid(f"invalid abandonment for {name}")
                    attempt.abandoned = True
                    work.adjudicate(attempt, data["verdict"], event["seq"])
                elif not attempt.head:
                    raise Invalid(f"collect the attempt before adding evidence for {name}")
                elif data.get("head", attempt.head) != attempt.head:
                    raise Invalid(f"evidence does not match the collected head for {name}")
                elif attempt.abandoned or lane.brief_seq > attempt.seq:
                    if event_type != "observed" or not work.can_classify(
                        attempt, data["ac"], data["result"], data.get("cause")
                    ):
                        raise Invalid(f"event cannot add evidence to an inactive attempt for {name}")
                    work.classify(attempt, data["ac"], nonempty(data["cause"], "cause"))
                elif event_type == "observed":
                    if data["ac"] not in lane.acceptance or data["result"] not in ("pass", "fail"):
                        raise Invalid(f"invalid observation for {name}")
                    if "cause" in data:
                        nonempty(data["cause"], "cause")
                    work.observe(lane, attempt, data, event["seq"])
                else:
                    if attempt.verdict or data["verdict"] not in ("hit", "miss", "inconclusive"):
                        raise Invalid(f"invalid adjudication verdict or attempt for {name}")
                    work.adjudicate(attempt, data["verdict"], event["seq"])
            elif event_type == "held":
                work.holds[data["code"]] = data["reason"]
            elif event_type == "resumed":
                for field in ("diagnosis", "hypothesis", "test"):
                    nonempty(data[field], field)
                work.holds.clear()
                work.completed.clear()
                work.resumes.append(data)
            elif event_type == "closed":
                if lane.state != "reviewed" or lane.current.abandoned or data["head"] != lane.current.head:
                    raise Invalid(f"invalid closing head or attempt for {name}")
                lane.closed = True
            else:
                raise Invalid(f"unknown event type: {event_type}")
        except (Invalid, TypeError, KeyError, AttributeError) as exc:
            raise Invalid(f"invalid {event_type} event {event['event_id']} for {name}: {exc}") from exc
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


def sync_view(directory, lanes, works):
    path = directory / "lanes.tsv"
    view = tsv(rows(lanes, works))
    if not path.exists() or path.read_bytes() != view.encode("utf-8"):
        replace_text(path, view)


def reconcile(root, logs):
    states = validate_history(logs)
    for run, (lanes, works) in states.items():
        sync_view(root / run, lanes, works)
    return states


def validate_history(logs):
    if resets := logs.get(ROUTE_LOG):
        known_kinds = kinds()
        for event in resets:
            kind = event["data"].get("kind")
            if (event["type"] != "route-reset" or event["lane"] or event["work"]
                    or not isinstance(kind, str) or kind not in known_kinds):
                raise Invalid(f"invalid route reset event {event['event_id']}")
    return {run: replay(events) for run, events in logs.items() if run != ROUTE_LOG}
