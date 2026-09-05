---
name: decision-brief
description: Hand a branching decision back to the owner as a comparison they can choose from, not as prose. Use when there are 2 or more options and the choice changes what gets built - how many PRs to split into, whether the design doc or the implementation is the source of truth, picking among screen designs, choosing an approach, a library or where to cut scope, ruling between sources of truth that disagree, or a premise collapsing mid-task. Also use when asked to "show me the options", "compare them and let me pick", "put the options side by side". Do not use it for progress reports, for work with one path, or for a plain "is this OK".
---

# Handing over a decision

**Do not hand a branch over as a paragraph of text.** Make it visible, make it selectable, then hand it over.

Long prose makes the reader assemble for themselves what they are being asked to decide.
Assemble it differently from the writer and the answer that comes back is the answer to a different question.

## What you produce

**These three, in this order. Miss one and the decision was not handed over.**

| | What it holds |
|---|---|
| **1. The decision sentence** | one sentence on what is being decided, then one on **what changes with the choice** |
| **2. HTML** | one standalone page with the options side by side; save it under the directory returned by `plumb-path run --mkdir` and link to the file. If the runtime offers an artifact design skill and publishing tool, use them as optional presentation helpers |
| **3. AskUserQuestion** | options carrying **the same labels** as the HTML. Put the real thing in `preview` when supported |

What stays in the terminal is the decision sentence and the link. **Do not write the explanation twice.**

No external skill or publishing service is required. Use the current runtime's supported question
tool and option limit. If it has no `preview` field, the linked HTML holds the evidence. If no question
tool is available, ask one concise question referring to the labels in the HTML. A pending decision
blocks dependent work; elapsed time, a preselected recommendation, and silence are not an answer.

## What goes in the HTML

**Columns are the options, rows are the axes you compare on.** Do not invent the axes — take them from **what actually changes with the choice**.

- **The real thing.** Excerpts of the diff, screenshots, measured numbers, before/after of the file layout.
  Not "easier to maintain" — how many lines maintenance changes by
- **What is left standing if it is not chosen.** Write only the recommendation thickly and it stops being a choice and becomes an approval
- **Your recommendation, and why.** Do not hide it. **But do not starve the other options**
- **The part you cannot decide.** If you have nothing to judge on, say so. Do not fill it in

**Do not ask what you could find out by looking.** Look first, then ask carrying what you found.

## The shape of the AskUserQuestion

- **2 to 4** options. Five or more means there are two axes in there. **Split the question** (up to 4 per call)
- Put the recommendation first, with "(Recommended)" at the end of the label
- `preview` holds **the real thing**, not prose: commands, a directory tree, a diff, a table of dimensions
- **Write the preview for the losing side at the same density.** One thin side is not a choice
- `description` says **what happens if this option is taken**, not a verdict on whether it is good

## When not to fire

| Situation | Instead |
|---|---|
| Reporting progress or completion | a few lines in the terminal |
| Work with one path | build it. Do not ask |
| Nothing but "is this OK" | proceed without asking. If the action needs approval, confirm in one sentence |
| Effectively one option (the rest are plainly worse) | do not dress it as a choice. **Report that, and proceed** — unless what you are reporting is a shape, which still passes the gate in `playbooks/shaping-the-work.md` |
| An investigation report that is long but has no branch | land it as a standalone document (a single HTML report). No AskUserQuestion |

## Once the answer comes back

**Execute the result that was chosen, not the reason it was chosen.** Do not re-argue it.

If the choice has a long reach — ruling on a source of truth, picking an approach, cutting scope —
**record the decision**: `plumb-decision-log`, or memory as `feedback` / `project`.
Without a record, you build the same table again next session.

## How this breaks

| Failure | What to do |
|---|---|
| Writing it all in the terminal with no HTML, then bolting on an AskUserQuestion | the explanation splits in two. **Put the explanation in the HTML** |
| The options are "do it / don't" | that is approval, not a branch. **Re-cut it by how it gets done** |
| One line of preview on everything but the recommendation | the mark of not meaning to let them choose. **Same density on all of them** |
| The HTML labels and the question labels differ | the reader cannot line them up. **Match the strings** |
| Carrying on with the implementation without waiting after handing the decision over | the premise of the choice collapses. **Only advance work that does not depend on the branch** |
