# Writing rules

These rules cover prose an agent writes for a person: pull request bodies, commit messages, reports,
documents. Each rule names a habit that makes generated text slower to read and harder to trust, and
says what to write instead. Japanese prose follows [`writing-ja.md`](writing-ja.md), which has its own
numbering.

Rule ids are stable so other files and reviews can cite them ("W7"). A retired rule keeps its id and
its line, marked retired, so a citation never points at a different rule.

Apply the rules to text you write or rewrite now. Do not rewrite an existing file only to apply them.
Code comments are not covered here; a repository limits those through `[code_policy]` in its project
contract (`docs/project-contract.md`).

## Content

- **W1. Name the mechanism.** Write the command, the file, the number or the actor. A sentence that
  could appear unchanged in another project's documents carries nothing; replace it or delete it.
- **W2. Give the number instead of an intensifier.** "From 4.2 s to 0.9 s", not "much faster".
  "Fails on 3 of 40 runs", not "occasionally flaky".
- **W3. Attribute by name or not at all.** "The upstream README says", not "it is widely believed".
- **W4. One hedge per claim, at most.** Prefer the router's labels: measured, inferred, guessed. Two
  hedges on one claim ("may possibly") hide whether anything was checked.
- **W5. End on the last fact or the next action.** No closing summary that restates the body, and no
  "In conclusion, X is a powerful approach".

## Words

- **W6. Use the plain verb.** "Use", not "leverage" or "utilize". "Is" or "has", not "serves as",
  "stands as", "boasts" or "features".
- **W7. One name per thing.** Pick a term and repeat it. Varying it for style makes the reader ask
  whether two things are meant.
- **W8. Drop words that mark machine prose and carry no meaning:** delve, crucial, pivotal, seamless,
  robust, comprehensive, vibrant, testament, underscore, showcase, foster, tapestry, landscape (outside
  its literal sense). Write what the thing does.
- **W9. Literal over figurative.** No metaphor where a literal phrase exists: not "north star",
  "flywheel", "paradigm" or "nexus", and no personified code ("the parser wants a token"). plumb's
  own named terms (a lever in `principle-build-the-lever`, the harness) are names, not figures, and stay.
- **W10. Cut filler.** "In order to" becomes "to". Delete "it is important to note that", "it is worth
  mentioning", "at the end of the day".

## Sentences

- **W11. One idea per sentence.** Split a sentence the reader has to read twice.
- **W12. Name the actor.** Use the active voice unless the actor is unknown or does not matter.
- **W13. No trailing clause that adds no fact.** Cut ", ensuring reliability" and ", highlighting the
  need for care" from the end of a sentence; if the clause holds a fact, make it its own sentence.
- **W14. No "not just X, but Y" and no "it is not X, it is Y" framing.** State the point.
- **W15. Do not round a list to three.** List what there is: two items, or four.
- **W16. Whole sentences.** Keep the articles and the verbs. Spell out arrows and ad hoc abbreviations
  in running prose; code and tables may keep them.
- **W17. A colon introduces a list or an example.** Do not use it as a connector in the middle of a
  sentence.

## Form

- **W18. Bold only what changes a decision.** Not every term, and never a bold label that restates
  its own line ("**Performance:** performance improved").
- **W19. No decorative emoji.** Sentence-case headings.
- **W20. No conversational wrapper.** No opening praise or agreement ("Great question"), and no
  closing offer ("Let me know if you need anything else", "I hope this helps"). Start with the answer.

## Checking

Read the text once for each section above before sending it. A reviewer who finds a breach cites the
rule id. When a rule here turns out to be checkable by a command, move it into that command and keep
its line here pointing at the command (`principle-encode-lessons-in-structure`).
