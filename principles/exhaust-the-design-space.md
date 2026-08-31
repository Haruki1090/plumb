---
name: principle-exhaust-the-design-space
origin: plumb
description: "Apply when you face a new UI interaction or an architecture decision with no precedent in the codebase. Before you decide, build 2-3 competing options and compare them side by side."
---

# Exhaust the Design Space

**On a decision with no precedent, build 2-3 competing options and line them up before you
decide.** The bar for choosing between them is **principle-experience-first**; the steps for
building one cheap and throwing it away live in `playbooks/prototype.md`. This principle owns
**how many you need before deciding**: the line between when one is enough and when it is not.

**Why this is hard to keep.** The first option you think of becomes the scaffolding for
every thought after it. Told to produce a second, what comes out is a variation on the first,
and **from the inside it feels like you considered an alternative.** On top of that, work has
already gone into the first one, so dropping it now costs something. **Fix the count up front
or the search always ends at one.**

## How to tell a second option is really a second option

**The collapse-together test.** When the assumption the first option rests on breaks, does
this one fall with it? If it does, it is the same option wearing a different face.
**An option resting on a different assumption is the second option.**

- Same way of holding the data, different presentation → the same option
- Same control flow, different names → the same option
- If **either one working makes the other unnecessary**, they are different options

## How to line them up

- **Put them on the same ground.** Same input, same scenario, same axes. Line up options built to different degrees of finish and what you compare is how much work went in, not the options
- **Put them behind one switch and give each a name.** The owner has to be able to call them by name
- **Once you decide, keep the rejected options together with the reason you rejected them.** Without that, the next time this fork comes around you build all of them again

## When not to apply it

- **Mechanical implementation where the shape is already settled.** The same shape appears again and again in the codebase
- **A bugfix or a refactor whose target state is already clear**
- **When the constraints narrow it to one.** But **if you claim they do, name which constraint each of the other options hits and dies on.** If you cannot name it, it is not narrowed
