# Code policy: report what a change newly introduces

Status: approved by the owner on 2026-11-23. Report-only first; a project decides whether to enforce.

## Why

Some rules are cheaper to hold mechanically than to remember: no new comments in application code,
no new effect hooks in a UI framework, no new lint suppressions. Prose rules drift; a repository
with hundreds of existing instances cannot turn such a rule on at once. plumb provides the contract
and the comparator; the project owns the rule set and its scope.

## Contract (`[code_policy]` in `.plumb/project.toml`, optional)

```toml
[code_policy]
mode = "report"                 # off | report | enforce
include = ["src/**/*.ts", "src/**/*.tsx"]
exclude = ["**/*.test.*", "**/generated/**"]
exceptions = ".plumb/code-policy-exceptions.tsv"   # optional: rule<TAB>path<TAB>reason
[[code_policy.rule]]
id = "no-new-comment"           # built-in kinds below, or kind = "pattern" with a regex
kind = "comment"
[[code_policy.rule]]
id = "no-new-effect"
kind = "pattern"
pattern = '\buse(Layout)?Effect\s*\('
[[code_policy.rule]]
id = "no-new-suppression"
kind = "pattern"
pattern = '(eslint-disable|@ts-ignore|@ts-expect-error)'
```

Built-in kind `comment`: a line-local scan of each added line. It reports the line when `//` or `/*`
appears outside a `'…'`, `"…"` or `` `…` `` literal that opens and closes on that same line. It keeps no
state across lines: a template literal or block comment that spans lines, a regex literal, and JSX
text are not understood, so false positives and misses there are expected and documented. One
allowance only: a line that is nothing but a tool directive listed in `allow_directives` (default
`["prettier-ignore"]`; an explicit empty list turns it off). Everything else that a project wants to
keep (license headers, doc comments above exports) goes in the exceptions file.

Why line-local (amended 2026-11-23 after the first review): telling a real comment from
comment-like text in JSX, regex and nested templates needs a real parser, and the standard library
has none for these languages. A hand-written lexer drew eight findings in one review and would keep
drawing them. plumb owns "rule hits x added lines x exceptions"; precise comment detection belongs
to the project's own linter, which already parses the language. A later change may let the
contract name a project command whose `path:line` output is intersected with the added lines.

Diff plumbing (amended 2026-11-23): one `git diff -U0 --find-renames <merge-base>` against the
worktree, with paths read NUL-delimited as bytes; hunks are consumed by their `@@` line counts so a
content line that looks like a header is never mistaken for one; untracked files in scope are added
whole; every path is `lstat`-ed before it is opened, only regular files are scanned, symlinks and
gitlinks are skipped and listed; any enumeration or read failure exits 2 (fail closed), never an
empty scan.

## Command

`plumb-code-policy report [--base REF] [--json] [--paths-from FILE]`

- Reads the contract with the same rules as `plumb-project` (absent → exit 0 with "skip: no
  code_policy"; invalid → exit 2; Python < 3.11 → exit 3).
- "Introduced" = a finding on a line that `git diff -U0 <merge-base REF HEAD>` (plus uncommitted and
  untracked files in scope) marks as added. Moved lines count as added; this is documented as the
  known limitation (report-only makes it acceptable).
- Output: one line per finding `rule<TAB>path:line<TAB>excerpt` (excerpt ≤ 80 chars), then a summary
  per rule. `--json`: `{"schema":1,"outcome":"clean|findings|skip","findings":[{rule,path,line,excerpt}],"counts":{rule:n}}`.
- Exit: `mode=report` → 0 even with findings; `mode=enforce` → 1 with findings; 2 invalid; 3 unavailable.
- An exceptions row suppresses findings of that rule in that path; a row whose reason is empty is invalid.
  Optional 4th/5th columns `expires` (YYYY-MM-DD) and `approved_by`: an expired row stops suppressing
  and is reported as `expired-exception` (reserved id); see docs/project-contract.md.
- `--base` default: `origin/HEAD`'s target, else `main`.

## Acceptance

1. A temp repo fixture: base with existing comments/effects; head adding one comment, one
   `useEffect(`, one `React.useEffect(`, one `// eslint-disable-next-line`, one string containing `//`,
   a URL in a string, a moved block, a file whose name has a space and one whose name is non-ASCII,
   a pure rename and a rename with one added finding. Report lists exactly the added ones (the moved block counted and
   noted), not the string/URL cases.
2. `mode=enforce` exits 1 on findings, 0 when clean; exceptions file suppresses a row; empty reason → exit 2.
3. No contract → exit 0 "skip"; broken contract → 2.
4. `plumb-project` validates `[code_policy]` (types, mode values, rule kinds) instead of warning on it.
5. docs/project-contract.md documents the table; selftest covers the cases; check-harness green
   apart from its 14 pre-existing NG.
