# Asking well

plumb routes a request to a playbook or a skill by reading it. A request that is clear about the outcome
and how you will recognise it gets a run that finishes. A vague one gets a run that stops early or
solves the wrong problem. This page is about writing the first kind.

## What a request carries

Five things. You do not need every one every time, but each one you leave out is a guess the agent makes
for you.

- **The goal, as an outcome.** One sentence about the state you want, not the method. "Signing in with an
  empty e-mail shows a form error" is an outcome. "Add a check in the login handler" is a method.
- **A done-condition that is true or false.** A command and what it should print, a test that should pass,
  a number below a limit. "Works better" cannot be judged by anyone, including the agent.
- **The evidence you want back.** Output of a command, a commit SHA, a pull request number. Without this
  you receive a claim.
- **What is already known.** What you tried, what you ruled out, where the code lives, what changed
  recently.
- **Constraints.** What must not change, which files are off limits, a deadline that matters.

## Two things to leave out

- **The steps.** The playbook already sets them, and a request that dictates the steps overrides a
  playbook that would have done better. If you care about one step, say which outcome it protects.
- **A guessed cause stated as fact.** The agent starts from it and then confirms it. Write "I suspect the
  cache, unverified" or say nothing. A wrong cause stated flatly costs an hour of well-organised work in
  the wrong place.

## Three before and after pairs

**A bug.**

Before: `Login is broken, please fix.`

After:

> Signing in with an empty e-mail returns a 500 instead of a form error. It started after last Tuesday's
> merge of the auth refactor. Done means a request with an empty e-mail returns 422 with the field name,
> a new test covers it, and the existing auth tests still pass. Show me the failing output before the fix
> and the passing output after. I do not know the cause.

**A feature.**

Before: `Add CSV export to the reports page.`

After:

> Finance needs the monthly report as a CSV they can open in a spreadsheet. The report page already builds
> the table in `reports/monthly.py`. I have not decided whether export is a button, a scheduled e-mail or
> an API; show me the options with a recommendation before you build anything. It must not change the
> existing page. Done means I have picked one and you have a plan I can approve.

**A performance complaint.**

Before: `The dashboard is slow, make it faster.`

After:

> The dashboard takes about 9 seconds to load for accounts with more than 2,000 orders, and about 1 second
> for small accounts. Target: under 3 seconds at the 95th percentile for the large account in the seed
> data. Measure it first and show me the baseline, the run count and the spread. Do not change the
> database schema.

The Japanese version of the bug request:

> 空のメールアドレスでログインすると、フォームエラーではなく 500 が返ります。先週火曜の認証リファクタのマージ後から
> 起きています。完了条件は、空のメールアドレスで 422 とフィールド名が返ること、新しいテストがあること、既存の
> 認証テストが通ることです。修正前の失敗出力と修正後の成功出力を見せてください。原因は分かっていません。

## Steering with a principle

plumb keeps a named index of principles, listed in the root `SKILL.md`. Naming one in your request makes
the agent read it in full and apply it to the decision in front of it:

> The last two fixes made the symptom disappear and it came back. Apply principle-fix-root-causes: do not
> touch the code until you can show me the failure on demand.

This helps when you have seen a specific failure mode and a principle names it: a patch on the failing
line (`principle-fix-root-causes`), "it passed" with no output (`principle-gate-claims-on-evidence`), a
measured number nobody can explain (`principle-explain-the-number`), an agent that stops to ask what it
could decide (`principle-never-block-on-the-human`). Use one or two. Naming six turns the request into a
checklist and the agent narrates instead of deciding.

It does not help when the request itself is vague. A principle sharpens a decision; it cannot supply a
goal you did not state. If you are unsure which playbook fits, ask first. `plumb:help` answers which
entry fits a job and hands back the prompt to send, and it does not start the work.
