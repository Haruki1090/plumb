---
name: principle-experience-first
origin: plumb
description: "Apply when a product, UX, or feature-scope trade-off comes up. Take the experience of the person using it over what is convenient to implement, and ship fewer polished features rather than many rough ones."
---

# Experience First

**When what is convenient to implement collides with the experience of the person using it,
take the experience.** The procedure for building several options and comparing them is
**principle-exhaust-the-design-space**; the load paid by whoever reads the code is
**principle-minimize-reader-load**. This principle owns **how to rule**: which side you drop
when convenience and experience meet head on.

**When to apply it.** Where you decide what to build and how far it goes: leaning toward
cutting in `playbooks/shaping-the-work.md`, picking an option in `playbooks/prototype.md`.
**Once implementation has started, what you would have ruled on is already gone** — all that
is left is working code and the cost of changing it.

**Why this is hard to keep.** There are two asymmetries. **The first**: what is convenient
to implement is visible to you, and the friction the user hits is not. **The second**:
convenience is measurable as hours of work, and a degraded experience is not. Put something
measurable next to something unmeasurable and the measurable one wins every time. So do not
weigh it case by case: **decide which way you fall before the collision.**

## Who the person using it is

**Whoever receives the output of this work** is the person using it. They sit in a different
seat; they get treated the same.

- For a screen, whoever touches that screen
- For a library or an internal API, the colleague who imports it
- For this playbook or this script, whoever runs it next
- **Whoever maintains this code next is also a person using it** — but counting the load on that seat is **principle-minimize-reader-load**, not this principle

**When you state the impact, state it from that seat.** Not "this makes the implementation
complex" but what happens to the person using it.

## How to rule

- **Narrow the count and polish.** Three finished features beat ten rough ones
- **Keep only the features, settings and options that won their seat.** "It does no harm to have it" did not win one
- **When the fork is about how something feels, build it and watch before you ask.** If an implementation you plan to throw away settles it, that is the cheapest way to decide (`playbooks/prototype.md`)
- **Do not drop the details.** Transitions, alignment, spacing, responsiveness, what shows when it fails. **The failure state is sometimes the screen people see most**

**You lay the foundation first in order to deliver the experience.** What you settle first is
answered by **principle-foundational-thinking**; **what you settle it toward** is answered
here. Once the convenience of the foundation starts choosing the destination, the ordering
has replaced the goal.
