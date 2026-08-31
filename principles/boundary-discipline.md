---
name: principle-boundary-discipline
origin: plumb
description: "Apply when writing validation, error handling, or the layer that binds to a framework. Concentrate guards at the point where data enters from outside; inside, trust the types and never check the same value twice. Keep the logic in pure functions that know nothing about the framework."
---

# Boundary discipline

**Concentrate the checks at the point where things enter from outside. Inside, trust them.**
This principle decides **where guards go**, not what caused a failure (that is
**principle-fix-root-causes**).

**Why this is hard to keep.** Adding a check where it crashed is always the cheapest move.
Tracing back to the entry point means investigating the path, and the proof that you fixed
anything moves further away. So the defenses **pile up where the crash was, and the entry
point stays thin**. And **a check you scatter can never be taken out**: deciding to delete a
check when nobody knows who put it there or what for costs more than deciding to add it.
**Add one knowing it is a one-way change.**

## What counts as the boundary

**Everything that came from outside the process.** Arguments, environment variables, config
files, network responses, return values from an external API, stored data, the output of
another process, whatever a person typed.
**A value handed to you by code you wrote is not a boundary.**

## The rules

- **Validate once at the entry point and turn the raw input into an inside type.** Do not validate it again after that
- **Inside, trust the types.** If the entry point validated, a nil check partway down the call chain is surplus
- **Change the representation as it crosses.** Do not carry shapes that exist for the outside world (wire formats, storage formats, framework types) inward, and do not put the inside types on your public surface. **What you expose is a domain concept**
- **Put the logic in pure functions that know nothing about the framework.** Keep the layer that binds to the framework thin and mechanical

## How to tell

- **Did this value just come from outside the system?** If not, the check is surplus
- **Which test fails if you delete this check?** If you cannot name one, it is sitting there with nothing behind it
- **How many levels of the call chain check the same value?** Two or more, and the boundary was never decided
- **Which functions take a framework type as a parameter?** Wherever one does, logic has leaked into the binding layer

## Do not scatter checks through every layer

**"Check at every layer, just in case" is the reverse of this principle.**
Thickening the inside while the entry point stays loose lets bad values keep coming in, and
**the only thing that disappears is the visible reason to tighten the entry point.**
When you hit a bug, what you add is not a guard along the path:
**it is a check at the entry point that let the value through, and a regression test that
pins the repro.**
