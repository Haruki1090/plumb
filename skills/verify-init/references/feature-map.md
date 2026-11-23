# One feature in the feature map

A template for one feature's entry. Write one entry per feature, and write it from what a run
showed, not from what the code suggests. `lookup` answers from these entries.

## Sub-features

The separate things a user can do inside this feature, one line each, named as the user would name
them. Two or three lines are enough to start. Name only what a scenario can drive; leave out what
you have not seen work.

## How a user gets there

The route from a fresh start to this feature, in the user's terms: the page or command they open,
the role they hold, the data that must exist first. **Never freeze implementation paths here.** A
file path or function name goes stale at the next refactor; the route a user takes survives it.
Which source paths belong to the feature is the data `lookup` reads, and is not copied into this
prose.

## Driving it

What the driver does, in order, to exercise each sub-feature, and what it records: the metric names
and where the artifacts go. Say what the scenario restores afterwards and how that is checked. Keep
it to the steps a run needs.

## Gotchas

What a run tripped on: a wait that must be explicit, a seed that makes two sides differ, a first
load that is slower than the rest. One line each, with the date it was seen. A gotcha nobody saw in
a run is not written here.
