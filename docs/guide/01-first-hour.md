# A first hour

By the end of this page you will have checked that plumb is healthy, made the three settings that matter
most, and watched one small task go from your prompt to evidence you can read.

## 1. Install

Follow the Install section of the [README](../../README.md#install) and start a new session in your
repository. Nothing else is required; plumb works with nothing configured. This page covers what to
do next.

## 2. Run the doctor

The doctor checks that the tools and paths plumb's documents describe exist on your machine. The plugin's
commands are on your agent's path, not on your own shell's (the README explains why), so ask the agent:

> Run plumb-doctor and tell me what each line that is not ok means for my setup.

It takes a minute or two. The output is a list under headings such as `inside`, `routing targets`,
`contract`, `ledger` and `loading`. Each line starts with one of three marks:

```
  ok   git
  --   role.judge: unset (the main session stands in)
  NG   ledger.store: ...
```

- `ok` means present and working.
- `--` means unset, optional, or not checkable here. It is never a fault. plumb does not report a tool you
  chose not to install as broken.
- `NG` means broken, and the doctor exits with status 1. Fix every `NG` before anything else; the line says
  what is wrong.

A fresh install shows mostly `--`. That is the starting point, not a problem.

## 3. Make three settings

Settings live in `~/.claude/plumb/config`, one `key = value` per line. Read one back with
`plumb-config <key>`; an empty answer means unset. The full format is in the README under Claude
configuration. These three change the most.

| Setting | What it gives you | What plumb does without it |
|---|---|---|
| `role.judge = <command>` | An adversarial review by a different model family from the one that wrote the code | The main session reviews its own work. The todo line reads `skip: role.judge unset`, and the work is never reported as independently verified |
| The project contract, `.plumb/project.toml` | Facts only your repository knows: how to start it, who must write a `Fixes-PR:` line | Everything still runs. The doctor prints `contract: none`, and `plumb:verify` answers `absent` and reports your tests as tests, not as verification |
| `pane.driver = <command>` | Long work in panes you can see | Work runs in the foreground. A queue run says `skip: pane.driver unset — lanes are not visible` |

Pick the judge command so that it starts a different family's coding agent from your terminal; the doctor
checks that the first word resolves on your path. Run `plumb-path project` to see where the contract
file belongs, and read [docs/project-contract.md](../project-contract.md) for its schema. You do not have to
write the contract by hand: Recipe 7 in the [recipes](03-recipes.md) has the agent write the verify part.

Run the doctor again. The `--` lines for the settings you made should now read `ok`.

## 4. One small task, end to end

Choose something real and small: a failing test, a wrong message, a one-line bug you already understand.
Avoid anything large for now. Paste this, with your own failure in place of the example:

> The test `test_parse_empty_record` fails with "IndexError: list index out of range". Fix it. Done means
> that test passes and the rest of the suite passes. Show me the command and its output before the fix and
> after it, and the root cause in one sentence.

The Japanese version:

> `test_parse_empty_record` が「IndexError: list index out of range」で落ちます。直してください。完了条件は、
> そのテストと既存のテスト全体が通ることです。修正の前後でコマンドとその出力を見せ、根本原因を一文で書いてください。

This lands on `playbooks/fixing-a-bug.md`. You should see, in order:

1. The failure restated in the agent's words, and a repro it can run again.
2. The trace from where it fell to where it broke.
3. One change, and the same command run again, with output.
4. The repro kept as a test, or a plain statement that no good test could be written.
5. A judge line: either the independent review ran, or it reads `skip: <reason>`.

Read the before and after output yourself. That pair is the claim; a sentence saying "fixed" is not.

When it is done, move on to [how to ask](02-asking.md) so the next request goes as smoothly as this one.
