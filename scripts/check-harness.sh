#!/usr/bin/env bash
# plumb cross-cutting rule check. Collected here so no lane has to interpret them on its own.
# Usage: scripts/check-harness.sh [plugin-root]
set -uo pipefail

root="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
SKILLS_DIR="$root/skills"
ROOT_SKILL="$root/SKILL.md"
PB_DIR="$root/playbooks"
PR_DIR="$root/principles"
fail=0

note() { printf '  %-4s %s\n' "$1" "$2"; }
check() {
  if [ "$2" -eq "$3" ]; then note "ok" "$1 ($2)"; else note "NG" "$1 (expected $3 / measured $2)"; fail=1; fi
}
# targets  = files that carry frontmatter (the root SKILL.md and everything under skills/)
# bodies   = every body text an agent reads (targets + playbooks). Banned words apply here
# docs/ and .git/ belong to neither set
targets() {
  find "$SKILLS_DIR" -name 'SKILL.md' 2>/dev/null
  [ -f "$ROOT_SKILL" ] && printf '%s\n' "$ROOT_SKILL"
}
playbooks() { find "$PB_DIR" -name '*.md' 2>/dev/null; }
principles() { find "$PR_DIR" -name '*.md' 2>/dev/null; }
# agents_md / skill_refs / skill_scripts: measured on 2026-08-30 as holes in bodies().
# Bundled agents (agents/*.md), a skill's supporting material (skills/*/references/*.md) and
# a skill's bundled scripts (skills/*/scripts/*.{sh,mjs,ts,py}) are body text an agent actually
# reads or executes, yet none of them landed in targets (files required to carry frontmatter),
# in playbooks or in principles, so scans like the banned-word check never saw them
# (I-1's pinned `model: opus` is the clean example).
# The frontmatter rules (3 and 4) still reference targets() directly, so widening here breaks nothing.
agents_md() { find "$root/agents" -name '*.md' 2>/dev/null; }
skill_refs() { find "$SKILLS_DIR" -path '*/references/*.md' 2>/dev/null; }
skill_scripts() { find "$SKILLS_DIR" -path '*/scripts/*' \( -name '*.sh' -o -name '*.mjs' -o -name '*.ts' -o -name '*.py' \) 2>/dev/null; }
bodies() { targets; playbooks; principles; agents_md; skill_refs; skill_scripts; }
# docs_md() and readme() exist for rule 11 alone (bin/ references resolve). Do not add them to
# bodies() — widening what the existing rules scan breaks a different check.
docs_md() { find "$root/docs" -name '*.md' 2>/dev/null; }
readme() { [ -f "$root/README.md" ] && printf '%s\n' "$root/README.md"; }
bin_ref_sources() { bodies; docs_md; readme; }

echo "plumb harness check: $root"

# 0. Always print how many files were scanned, so a run that passes on 0 files cannot slip through
scanned=$(targets | wc -l | tr -d ' ')
pbs=$(playbooks | wc -l | tr -d ' ')
prs=$(principles | wc -l | tr -d ' ')
ags=$(agents_md | wc -l | tr -d ' ')
refs=$(skill_refs | wc -l | tr -d ' ')
scs=$(skill_scripts | wc -l | tr -d ' ')
note "--" "scanned SKILL.md: ${scanned} / playbooks: ${pbs} / principles: ${prs} / agents: ${ags} / references: ${refs} / skill-bundled scripts: ${scs}"

# 1. No model slug in the body text
slug=0
while IFS= read -r f; do
  grep -qIE 'grok-[0-9]|gpt-[0-9]+(\.[0-9]+)?[a-z]*(-[a-z0-9.]+)*|claude-(opus|sonnet|haiku|fable)(-[0-9]+)+|claude-[0-9]+(-[0-9]+)*-(opus|sonnet|haiku|fable)|(^|[^A-Za-z0-9])o[0-9]+-[a-z]+|gemini-[0-9]+(\.[0-9]+)?-[a-z]+(-[a-z]+)*' "$f" \
    && { slug=$((slug+1)); note "NG" "model slug: ${f#$root/}"; }
done < <(bodies)
check "files containing a model slug" "$slug" 0

# 2. No .cursor in the body text
cur=0
while IFS= read -r f; do
  grep -qI '\.cursor' "$f" && { cur=$((cur+1)); note "NG" ".cursor: ${f#$root/}"; }
done < <(bodies)
check "files containing .cursor" "$cur" 0

# 3. Frontmatter carries name and description
missing=0
while IFS= read -r f; do
  head -20 "$f" | grep -q '^name:' || { missing=$((missing+1)); note "NG" "name missing: ${f#$root/}"; }
  head -20 "$f" | grep -q '^description:' || { missing=$((missing+1)); note "NG" "description missing: ${f#$root/}"; }
done < <(targets)
check "frontmatter missing a key" "$missing" 0

# 4. No leftover template TODO
todo=0
while IFS= read -r f; do
  head -20 "$f" | grep -q 'TODO' && { todo=$((todo+1)); note "NG" "TODO left behind: ${f#$root/}"; }
done < <(targets)
check "frontmatter with a leftover TODO" "$todo" 0

# 5. The entry point must be openable by the model. Principles must not be skills.
#    2026-08-29: disable-model-invocation was set on the router, and the whole harness became
#    unreachable. The Skill tool forbids "reaching it by other means" too, so Read is no detour.
dead=0
while IFS= read -r f; do
  grep -q '^disable-model-invocation' "$f" && { dead=$((dead+1)); note "NG" "not a skill, yet the setting is still there: ${f#$root/}"; }
done < <(principles; playbooks)
check "body text carrying a dead setting" "$dead" 0

blocked=0
while IFS= read -r f; do
  grep -q '^disable-model-invocation: *true' "$f" && { blocked=$((blocked+1)); note "NG" "the model cannot open it: ${f#$root/}"; }
done < <(targets)
check "skills the model cannot open" "$blocked" 0

# 6. Every principle carries a written description, and no body text is left un-migrated.
#     This rule used to assert the opposite: a principle's description had to hold a non-ASCII
#     character, which was how "somebody wrote this for plumb" was checked while plumb was
#     written in Japanese. The English cutover killed that proxy — every description is ASCII
#     now, so the old rule would fail all 22 files while proving nothing.
#     What is worth checking survives the language change and splits in two:
#       a. principles/ is the only place a description is required and rule 3 does not reach it
#          (rule 3 walks targets(), which is frontmatter-bearing files only). An empty or
#          placeholder description is invisible to every other rule, so it is checked here.
#          The length floor is a floor, not a style rule: it catches a description that restates
#          the file name and stops.
#       b. A stray CJK character anywhere in the body text means a file the cutover missed.
#          That is exactly the failure the old rule was shaped to catch, pointed the other way.
DESC_MIN=60
thin=0
while IFS= read -r f; do
  desc=$(grep -m1 '^description:' "$f" || true)
  if [ -z "$desc" ]; then
    thin=$((thin+1)); note "NG" "no description: ${f#$root/}"
  elif [ "${#desc}" -lt "$DESC_MIN" ]; then
    thin=$((thin+1)); note "NG" "description too thin to be written for plumb (${#desc} < $DESC_MIN chars): ${f#$root/}"
  fi
done < <(principles)
check "principles with a missing or placeholder description" "$thin" 0

#     Matched as raw bytes rather than with grep -P, which BSD grep does not have. Under
#     LC_ALL=C the lead byte of a UTF-8 sequence is enough: \xe3-\xe9 covers U+3000-U+9FFF
#     (CJK punctuation, kana, and the CJK ideographs), and \xef followed by \xbc or \xbd
#     covers the fullwidth forms. \xe2 is deliberately left out: em dashes and curly quotes
#     live there and are wanted.
cjk=0
while IFS= read -r f; do
  LC_ALL=C grep -qE $'[\xe3-\xe9]|\xef[\xbc\xbd]' "$f" \
    && { cjk=$((cjk+1)); note "NG" "Japanese text left in the body: ${f#$root/}"; }
done < <(bodies)
check "body files still holding Japanese" "$cjk" 0

# 7. No dependency on machinery this environment does not have
#    Upstream assumes Graphite / Cursor cloud / Bugbot / cursor-team-kit. Forget to strip one
#    while rewriting and the document instructs steps nobody here can run
ext=0
while IFS= read -r f; do
  hit=$(grep -oIE 'cursor-team-kit|Bugbot|control-ui|control-cli|/deslop|/no-comments|poteto|`gt`|gt submit|gt restack|gt track|gt sync|gt merge' "$f" | sort -u | tr '\n' ' ')
  [ -n "$hit" ] && { ext=$((ext+1)); note "NG" "depends on absent machinery [${hit%% }]: ${f#$root/}"; }
done < <(bodies)
check "body text naming machinery this environment lacks" "$ext" 0

# 7b. Every script the body text names actually exists
#     "the thing that should be there is missing" shows up in neither grep nor a lint. Stepped
#     on it twice on 2026-08-29.
#     Passing $(bodies) straight into grep's argument expansion word-splits any filename whose
#     root contains a space; grep is then handed a nonexistent file and silently returns 0 hits
#     (a false ok). Loop one file at a time with read and hand grep the quoted path.
#     2026-08-30: the extraction pattern only matched `scripts/...`, so a reference carrying a
#     wrong prefix — `plumb/scripts/...` — had just its `scripts/...` part carved out and passed
#     the existence test (the error in the body text went unseen). Capture the whole
#     alphanumeric/./-/ prefix and test whether the string as written resolves from root.
#     A bare relative reference like `scripts/foo.sh` is still extracted as-is, so passages that
#     name a script as a name (bare `scripts/...`) are unaffected.
miss=0
while IFS= read -r ref; do
  [ -f "$root/$ref" ] || { miss=$((miss+1)); note "NG" "the body text names a script that does not exist: $ref"; }
done < <(
  while IFS= read -r f; do
    grep -ohE '[A-Za-z0-9._/-]*scripts/[a-z0-9._/-]+\.(sh|mjs|ts|py)' "$f" 2>/dev/null
  done < <(bodies) | sort -u
)
check "script references with nothing behind them" "$miss" 0

# 8. The playbooks and the router's index agree (add to one side only and the index is a lie)
orphan=0; dangling=0
while IFS= read -r f; do
  grep -q "playbooks/$(basename "$f")" "$ROOT_SKILL" || { orphan=$((orphan+1)); note "NG" "not in the index: playbooks/$(basename "$f")"; }
done < <(playbooks)
while IFS= read -r name; do
  [ -f "$PB_DIR/$name" ] || { dangling=$((dangling+1)); note "NG" "the index points at nothing: playbooks/$name"; }
done < <(grep -oE 'playbooks/[a-z0-9-]+\.md' "$ROOT_SKILL" | sed 's|playbooks/||' | sort -u)
while IFS= read -r f; do
  n=$(basename "$f" .md)
  grep -q "principle-$n" "$ROOT_SKILL" || { orphan=$((orphan+1)); note "NG" "not in the index: principles/$n.md"; }
done < <(principles)
while IFS= read -r name; do
  [ -f "$PR_DIR/$name.md" ] || { dangling=$((dangling+1)); note "NG" "the index points at a principle that does not exist: principles/$name.md"; }
done < <(grep -oE '\*\*principle-[a-z-]+\*\*' "$ROOT_SKILL" | sed -E 's/\*\*principle-([a-z-]+)\*\*/\1/' | sort -u)
check "files missing from the index" "$orphan" 0
check "index lines with nothing behind them" "$dangling" 0

# 9. No unpublishable proper nouns left behind
#    The tokens to match against live outside the repository. Writing them here as literals
#    would put the very names we are removing into the published artifact.
#    With no list, do not run the check. Do not pass silently either: report it with -- (a visible skip).
# What gets scanned is "what gets published" = what git tracks. An allowlist of paths leaves a
# hole the moment something new is tracked (2026-08-30: .plumb/plans sat inside the exclusion
# and walked straight through).
everything() { git -C "$root" ls-files -z 2>/dev/null | tr '\0' '\n' | sed "s|^|$root/|"; }
tokens="${PLUMB_PRIVATE_TOKENS:-$HOME/.claude/plumb/private-tokens.txt}"
if [ ! -f "$tokens" ]; then
  note "--" "proper-noun check: skipped, no token list (${tokens/#$HOME/~})"
else
  priv=0
  while IFS= read -r f; do
    [ -f "$f" ] || continue
    # git@github.com and noreply are infrastructure notation, not a person's identifier. Drop them
    hit=$(grep -oIEf "$tokens" "$f" 2>/dev/null \
          | grep -vxE 'git@github\.com|[a-z0-9-]+@users\.noreply\.github\.com' \
          | sort -u | tr '\n' ' ')
    [ -n "$hit" ] && { priv=$((priv+1)); note "NG" "unpublishable proper noun [${hit%% }]: ${f#$root/}"; }
  done < <(everything)
  check "files containing an unpublishable proper noun" "$priv" 0
fi

# 10. The body text does not name a routing target directly
#     Name one and the document becomes a lie for anyone who does not have that tool. Where a
#     role runs is decided by `~/.claude/plumb/config`; the body names the key (pane.driver and
#     the rest).
#     Scan portable bodies only. The one exception is skills/plumb-codex/SKILL.md: naming its runtime
#     is the entire purpose of that thin adapter. docs/path-map.md states which tool puts worktrees
#     where — a fact, not an instruction — and scripts/ holds test values plus external skill names.
tool=0
while IFS= read -r f; do
  hit=$(grep -oIE 'herdr|cursor-agent|codex' "$f" | sort -u | tr '\n' ' ')
  [ -n "$hit" ] && { tool=$((tool+1)); note "NG" "names a routing target directly [${hit%% }]: ${f#$root/}"; }
done < <(bodies | grep -vF "$root/skills/plumb-codex/SKILL.md")
check "body text naming a routing target" "$tool" 0

# 11. Every plumb-* command the body text names exists in bin/
#     Same shape as 7b. The variable pointing at the plugin root only expands inside SKILL.md, so
#     the convention is that the body calls the bin/ command by bare name. Name one that is not
#     there and you get exit 127.
#     Scan more than bodies(): README.md and docs/ too — once the README carries command names,
#     leaving just that file outside the machine is indefensible (do not widen bodies() itself;
#     the existing rules use it. bin_ref_sources() is held separately for this rule alone).
BIN_DIR="$root/bin"
nobin=0
skill_names=$(while IFS= read -r f; do
  sed -n 's/^name:[[:space:]]*//p' "$f" | head -1
done < <(targets))
while IFS= read -r cmd; do
  # A skill can legitimately share the plumb-* lexical shape without being a command. This became
  # visible when the additive runtime entry was named plumb-codex. Subtract declared skill names
  # before checking executable references; do not hard-code one exception.
  printf '%s\n' "$skill_names" | grep -Fxq "$cmd" && continue
  [ -f "$BIN_DIR/$cmd" ] || { nobin=$((nobin+1)); note "NG" "the body text names a plumb-* command that does not exist: bin/$cmd"; }
done < <(
  while IFS= read -r f; do
    # Take one following character with the name so a filename is distinguishable from a
    # command. 2026-08-31: `assets/plumb-banner.png` in README.md was being read as a command
    # and rule 11 had been failing on main ever since the banner landed. A bare `\bplumb-[a-z-]+\b`
    # cannot tell `plumb-banner.png` from `plumb-doctor`, and it cannot simply drop every match
    # containing a dot either: `plumb-doctor.` at the end of a sentence is a real reference.
    # So: match an optional extension, drop the ones that are files, strip a sentence period.
    grep -ohE 'plumb-[a-z-]+\.?[a-z]{0,4}' "$f" 2>/dev/null
  done < <(bin_ref_sources) \
    | grep -vE '\.(png|jpe?g|svg|gif|sh|mjs|ts|py|json|md|txt|ya?ml|lock)$' \
    | sed 's/\.$//' | sort -u
)
check "plumb-* command references with nothing behind them" "$nobin" 0

# 12. No bundled agent pins a model in its frontmatter
#     SKILL.md says "do not write a model name in the body text" and docs/role-map.md says "do not
#     write model". This checks that the bundled material itself (agents/*.md) does not break that
#     discipline. Measured on 2026-08-30: all 6 agents/*.md pinned `model: opus` — and rule 1
#     (model slug) passed them, through the old hole in bodies(). The slug check only catches
#     specific slugs shaped like "claude-opus-...", so frontmatter's `model: opus` is caught here.
pinned=0
while IFS= read -r f; do
  head -20 "$f" | grep -q '^model:' && { pinned=$((pinned+1)); note "NG" "agent pinning a model: ${f#$root/}"; }
done < <(agents_md)
check "agent frontmatter pinning a model" "$pinned" 0

# 13. The number of principles NOTICE claims matches what is actually there
#     2026-08-30: one principle had been rewritten from scratch, but NOTICE still said "all 21 are
#     reproduced verbatim" — which reads as "everything in principles/ is a copy of pstack", a lie.
#     Fixing NOTICE by hand every time someone adds a principle is a habit that always breaks
#     (**principle-encode-lessons-in-structure**). Verbatim identity itself cannot be judged
#     without fetching upstream, and a check that goes to the network fails offline and stops
#     being used. So **provenance lives in each file's frontmatter** and NOTICE only claims the
#     tally. A rewritten principle carries `origin: plumb`.
#     A mismatch fires whichever side you forget:
#       - added without the marker -> the verbatim count rises and disagrees with NOTICE
#       - added with the marker    -> the total rises and disagrees with NOTICE
NOTICE_F="$root/NOTICE"
if [ ! -f "$NOTICE_F" ]; then
  note "NG" "NOTICE is missing"; fail=1
else
  authored=0
  while IFS= read -r f; do
    head -20 "$f" | grep -qE '^origin: *plumb *$' && authored=$((authored+1))
  done < <(principles)
  verbatim_actual=$((prs - authored))
  n_total=$(grep -oE 'principles/ holds [0-9]+ files' "$NOTICE_F" | grep -oE '[0-9]+' | head -1)
  n_verb=$(grep -oE '[0-9]+ are reproduced verbatim' "$NOTICE_F" | grep -oE '[0-9]+' | head -1)
  if [ -z "$n_total" ] || [ -z "$n_verb" ]; then
    note "NG" "cannot read the principle counts out of NOTICE ('principles/ holds N files' and 'N are reproduced verbatim' are required)"
    fail=1
  elif [ "$n_total" -ne "$prs" ] || [ "$n_verb" -ne "$verbatim_actual" ]; then
    note "NG" "NOTICE's counts disagree with reality (NOTICE: total ${n_total} / verbatim ${n_verb}; actual: total ${prs} / verbatim ${verbatim_actual}, authored ${authored})"
    fail=1
  else
    note "ok" "NOTICE's principle counts (total ${prs} / verbatim ${n_verb} / authored ${authored})"
  fi
fi

# 14. The counts the README claims match what is actually there.
#     Measured on 2026-08-30: the README said "the 13 playbooks" against 19 real ones, and
#     "Twenty-one principles" against 22. **The README was rotting in exactly the shape it claims
#     plumb prevents — "documentation rots silently".** NOTICE is held by rule 13; nobody was
#     watching the README (**principle-encode-lessons-in-structure**).
#     Spelled-out numbers ("Twenty-one") cannot be read by a machine, so the convention is that
#     the README writes them as digits.
README_F="$root/README.md"
if [ ! -f "$README_F" ]; then
  note "NG" "README.md is missing"; fail=1
else
  r_pb=$(grep -oE '[0-9]+ playbooks' "$README_F" | grep -oE '[0-9]+' | head -1)
  r_pr=$(grep -oE '[0-9]+ principles' "$README_F" | grep -oE '[0-9]+' | head -1)
  if [ -z "$r_pb" ] || [ -z "$r_pr" ]; then
    note "NG" "cannot read the counts out of the README ('N playbooks' and 'N principles', in digits)"
    fail=1
  elif [ "$r_pb" -ne "$pbs" ] || [ "$r_pr" -ne "$prs" ]; then
    note "NG" "the README's counts disagree with reality (README: playbooks ${r_pb} / principles ${r_pr}; actual: ${pbs} / ${prs})"
    fail=1
  else
    note "ok" "the README's counts (playbooks ${pbs} / principles ${prs})"
  fi
fi

# 15. The additive Codex sidecar is complete and parseable. Keep this outside bodies(): model slugs and
#     runtime names belong in adapter configuration, not in Claude's portable playbook prose.
CODEX_MANIFEST="$root/.codex-plugin/plugin.json"
CODEX_CONFIG="$root/.codex/config.toml"
CODEX_AGENTS="$root/.codex/agents"
if [ ! -f "$CODEX_MANIFEST" ]; then
  note "NG" ".codex-plugin/plugin.json is missing"; fail=1
elif [ ! -f "$CODEX_CONFIG" ]; then
  note "NG" ".codex/config.toml is missing"; fail=1
elif [ ! -d "$CODEX_AGENTS" ]; then
  note "NG" ".codex/agents/ is missing"; fail=1
else
  claude_version=$(sed -n 's/^[[:space:]]*"version":[[:space:]]*"\([^"]*\)".*/\1/p' "$root/.claude-plugin/plugin.json" | head -1)
  codex_version=$(sed -n 's/^[[:space:]]*"version":[[:space:]]*"\([^"]*\)".*/\1/p' "$CODEX_MANIFEST" | head -1)
  changelog_version=$(sed -n 's/^## \[\([^]]*\)\].*/\1/p' "$root/CHANGELOG.md" | head -1)
  if [ -n "$claude_version" ] && [ "$claude_version" = "$codex_version" ] && [ "$codex_version" = "$changelog_version" ]; then
    note "ok" "release version agrees across both manifests and CHANGELOG (${codex_version})"
  else
    note "NG" "release version mismatch (Claude ${claude_version:-missing} / Codex ${codex_version:-missing} / CHANGELOG ${changelog_version:-missing})"; fail=1
  fi
  if [ -n "$codex_version" ] && [ -f "$root/docs/releases/v${codex_version}.md" ]; then
    note "ok" "release notes exist (docs/releases/v${codex_version}.md)"
  else
    note "NG" "release notes missing for ${codex_version:-unknown version}"; fail=1
  fi

  codex_agent_count=$(find "$CODEX_AGENTS" -name '*.toml' -type f | wc -l | tr -d ' ')
  if [ "$codex_agent_count" -eq 10 ]; then
    note "ok" "Codex custom agent count (${codex_agent_count})"
  else
    note "NG" "Codex custom agent count (expected 10 / measured ${codex_agent_count})"; fail=1
  fi

  if command -v python3 >/dev/null 2>&1 && python3 -c 'import tomllib' >/dev/null 2>&1; then
    codex_bad=0
    python3 -c 'import json, pathlib, sys, tomllib
root = pathlib.Path(sys.argv[1])
manifest = json.loads((root / ".codex-plugin/plugin.json").read_text())
assert manifest["name"] == "plumb"
assert manifest["skills"] == "./skills/"
config = tomllib.loads((root / ".codex/config.toml").read_text())
assert config["model"] == "gpt-5.6-sol"
assert config["agents"]["default_subagent_model"] == "gpt-5.6-luna"
assert config["agents"]["max_concurrent_threads_per_session"] == 4
names = set()
reasoning = {
    "gpt-5.6-sol": {"low", "medium", "high", "xhigh", "max", "ultra"},
    "gpt-5.6-luna": {"low", "medium", "high", "xhigh", "max"},
}
for path in sorted((root / ".codex/agents").glob("*.toml")):
    agent = tomllib.loads(path.read_text())
    for key in ("name", "description", "developer_instructions", "model", "model_reasoning_effort", "sandbox_mode"):
        assert agent.get(key), f"{path}: missing {key}"
    assert agent["name"] == path.stem.replace("-", "_"), f"{path}: name does not match filename"
    assert agent["name"] not in names, f"{path}: duplicate agent name"
    names.add(agent["name"])
    assert agent["model"] in reasoning, f"{path}: unsupported model"
    assert agent["model_reasoning_effort"] in reasoning[agent["model"]], f"{path}: unsupported reasoning effort"
    assert agent["sandbox_mode"] in {"read-only", "workspace-write"}, f"{path}: unsupported sandbox mode"
    assert "SendMessage" not in agent["developer_instructions"]
' "$root" || codex_bad=1
    check "Codex JSON/TOML files that fail structural validation" "$codex_bad" 0
  else
    note "--" "Codex JSON/TOML parse: skipped, Python 3.11+ with tomllib is unavailable"
  fi
fi

if [ $fail -eq 0 ]; then echo "  → passed (SKILL.md ${scanned} / playbooks ${pbs} / principles ${prs} / agents ${ags})"; else echo "  → failed"; fi
exit $fail
