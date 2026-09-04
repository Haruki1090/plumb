---
name: plumb-codex
description: Use the Claude-first plumb engineering harness from Codex without changing its canonical playbooks or principles.
---

# plumb runtime entry

This is a thin execution adapter. Do not restate or fork the harness here.

1. Read `../../SKILL.md`; it remains the source of truth for routing, playbooks, principles, artifacts,
   and the visible judge line.
2. Read `../../docs/openai-runtime.md`; it translates runtime-specific roles, tools, return values,
   command lookup, and model placement.
3. Apply the canonical playbook selected by the root router, with only the execution substitutions in
   the runtime adapter.

When the two documents appear to disagree about product mechanics, the runtime adapter wins only for
those mechanics. It never overrides the acceptance criteria, review standard, or named principles.
