---
name: open-pr
description: Rules the repository sets for a pull request it is about to receive. Use whenever opening, creating or submitting a pull request, or writing or rewriting its body ("open a PR", "make this a PR", "send this fix up", "write the PR description"). Reads the project contract and adds the lines it requires, such as Fixes-PR. Not for reviewing a pull request (plumb:pr-review) or answering review comments (playbooks/being-reviewed.md).
---

# Open a pull request the repository will accept

A repository can require lines in a pull request body that no template shows. They live in its
project contract, so read it before writing the body. These steps come before the title and the
sections; the body's shape is `playbooks/opening-a-pr.md`.

1. **Read the contract** from inside the checkout, and look at the exit status, not only the output:

   ```bash
   plumb-project rework.required_authors; echo "exit=$?"
   ```

   | Exit | Output | What it means |
   |---|---|---|
   | 0 | nothing | No contract, or no one is required. No `Fixes-PR:` line is needed |
   | 0 | logins, one per line | The repository checks the `Fixes-PR:` line. Write it (step 2) |
   | 2 | `plumb-project: invalid: …` on stderr | The contract is broken. **Stop.** Do not open the pull request and do not write a final body. Report the stderr line to the owner. A broken contract is never "no policy" |
   | 3 | `plumb-project: unavailable: …` on stderr | The parser is missing (Python older than 3.11). **Stop** and report it the same way |

2. **Write exactly one `Fixes-PR:` line** when step 1 printed any login, whoever you are: a line
   from an author who is not required is harmless, and a missing one fails the check.
   - `Fixes-PR: #<n>`, with further `, #<n>` items, names the **earlier landed pull requests**
     this one fixes. An issue number does not belong here (close issues the way the repository
     does, for example `Closes #<n>`). When the owner names a number, check what it is: a landed
     pull request in the history or on GitHub belongs on this line, an issue does not.
   - `Fixes-PR: none` when it fixes no earlier pull request.
   - Two lines, a repeated number, or this pull request's own number are errors.

3. **Check the body before you open the pull request.** Pass one of the logins from step 1 as the
   author, so the body is always read:

   ```bash
   plumb-check-fixes --author <a login from step 1> --required-authors "<logins from step 1, comma-separated>" \
     --pr <number> --body-file <body file>
   ```

   Before the pull request exists its number is unknown: pass a number that is not on the line
   (`999999`), and run the check again with the real number once it is open. Exit 0 is required.
   On exit 1 fix the line it names and run it again.

4. Then follow `playbooks/opening-a-pr.md` for the title, the sections and the evidence.

The grammar and the CI side are in `docs/project-contract.md`.
