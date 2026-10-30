#!/usr/bin/env bash
# plumb-bootstrap — set plumb up inside a cloud environment's setup script, then say what is missing.
#
#   plumb-bootstrap [--store <git URL>] [--capture on|off] [--export manual|on-stop]
#                   [--judge "<command>"] [--strict]
#
# A cloud setup script runs before the session, as root, and cannot read the environment's saved
# variables or secrets. So every value comes from the command line as a literal, non-secret string
# (never from an environment variable), and nothing here reads or prints a credential.
#
# 1. Writes the given keys into ${PLUMB_CONFIG:-~/.claude/plumb/config}, inside one managed block
#    (`# >>> plumb-bootstrap` ... `# <<< plumb-bootstrap`). Only that block is replaced; every other
#    line the owner wrote stays, and a second run with the same arguments leaves the file
#    byte-identical. The block sits at the top of the file because plumb-config.sh returns the first
#    matching line, so the block's value wins over the same key written elsewhere in the file (that
#    is reported with a `--` line). A run replaces the whole block: keys not given this time leave it.
# 2. Checks and prints one ok / -- / NG line each: plumb is installed (claude plugin list --json),
#    the judge command resolves and, for codex, is logged in, the store answers
#    (plumb-ledger export --check), and plumb-doctor's overall line.
#
# Exit 0 even with NG lines (a setup script must not fail the environment for a missing login),
# unless --strict, then 1 on any NG. Exit 2 on a usage error.
set -uo pipefail

usage() {
  cat <<'EOF'
usage: plumb-bootstrap [--store <git URL>] [--capture on|off] [--export manual|on-stop]
                       [--judge "<command>"] [--strict]

Run it from a cloud environment's setup script, after the plugin is installed:
  claude plugin marketplace add Haruki1090/plumb
  claude plugin install plumb@plumb
  plumb-bootstrap --store <git URL> --capture on --export on-stop --judge "codex exec"

Writes the given keys (ledger.store, ledger.capture, ledger.export, role.judge) into
${PLUMB_CONFIG:-~/.claude/plumb/config} between `# >>> plumb-bootstrap` and `# <<< plumb-bootstrap`.
Only that block is replaced; the rest of the file is kept and a second run is a no-op. Values are
literals from the command line: nothing is read from environment variables or secrets, so do not
put a token in --store (use the git credential for that URL).

Then checks, one line each (ok present, -- unset or cannot check, NG broken): plumb is installed,
the judge resolves (codex: logged in), the store answers, plumb-doctor's overall line.
Exit 0 even with NG lines; --strict exits 1 on any NG. Exit 2 on a usage error.
EOF
}

die_usage() { printf 'plumb-bootstrap: %s\n' "$1" >&2; printf 'try: plumb-bootstrap --help\n' >&2; exit 2; }

store="" capture="" export_mode="" judge=""
have_store=0 have_capture=0 have_export=0 have_judge=0 strict=0
while [ $# -gt 0 ]; do
  arg=$1
  case "$arg" in
    -h|--help) usage; exit 0 ;;
    --strict) strict=1; shift; continue ;;
    --store=*|--capture=*|--export=*|--judge=*) name=${arg%%=*}; val=${arg#*=}; shift ;;
    --store|--capture|--export|--judge)
      [ $# -ge 2 ] || die_usage "$arg needs a value"
      name=$arg; val=$2; shift 2 ;;
    *) die_usage "unknown argument: $arg" ;;
  esac
  # Trim surrounding whitespace; the config format would drop it anyway.
  val=${val#"${val%%[![:space:]]*}"}; val=${val%"${val##*[![:space:]]}"}
  [ -n "$val" ] || die_usage "$name needs a non-empty value"
  case "$val" in *$'\n'*|*$'\r'*) die_usage "$name must be a single line" ;; esac
  case "$name" in
    --store)   store=$val; have_store=1 ;;
    --capture) case "$val" in on|off) capture=$val; have_capture=1 ;; *) die_usage "--capture takes on or off" ;; esac ;;
    --export)  case "$val" in manual|on-stop) export_mode=$val; have_export=1 ;; *) die_usage "--export takes manual or on-stop" ;; esac ;;
    --judge)   judge=$val; have_judge=1 ;;
  esac
done

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd) || { echo "plumb-bootstrap: cannot find the plugin root" >&2; exit 2; }
if [ -n "${PLUMB_CONFIG:-}" ]; then
  cfgfile=$PLUMB_CONFIG
elif [ -n "${HOME:-}" ]; then
  cfgfile=$HOME/.claude/plumb/config
else
  die_usage "neither PLUMB_CONFIG nor HOME is set, so there is no config file to write"
fi

fail=0
note() { printf '  %-4s %s\n' "$1" "$2"; }
bad()  { note "NG" "$1"; fail=1; }
# Anything that is printed passes through here: userinfo in a URL is masked.
mask() { sed -E 's#(://)[^/@[:space:]]*@#\1***@#g; s#((access_token|token|password|secret|key)=)[^&[:space:]]+#\1***#g'; }
# timeout is not on a stock macOS; without it the command simply runs unbounded.
bounded() { local secs=$1; shift; if command -v timeout >/dev/null 2>&1; then timeout "$secs" "$@"; else "$@"; fi; }

# A value as plumb-config.sh will read it back: bare unless it would be cut or unquoted wrongly.
config_value() {
  local v=$1
  case "$v" in
    *" #"*|*$'\t#'*|"#"*|\"*|\'*)
      case "$v" in
        *\"*) case "$v" in *\'*) return 1 ;; *) printf "'%s'" "$v" ;; esac ;;
        *)    printf '"%s"' "$v" ;;
      esac ;;
    *) printf '%s' "$v" ;;
  esac
}

BEGIN_MARK='# >>> plumb-bootstrap'
END_MARK='# <<< plumb-bootstrap'

echo "plumb bootstrap: $root"

# ---- 1. config ----
keys_given=()
block_lines=()
add_key() { # <key> <value>
  local q
  q=$(config_value "$2") || die_usage "$1: a value holding both quote kinds and ' #' cannot be written to the config"
  block_lines+=("$1 = $q"); keys_given+=("$1")
}
[ "$have_store" -eq 1 ]   && add_key ledger.store "$store"
[ "$have_capture" -eq 1 ] && add_key ledger.capture "$capture"
[ "$have_export" -eq 1 ]  && add_key ledger.export "$export_mode"
[ "$have_judge" -eq 1 ]   && add_key role.judge "$judge"

if [ "${#keys_given[@]}" -eq 0 ]; then
  note "--" "config: no keys given, $cfgfile is left as it is"
else
  tmp_rest=$(mktemp "${TMPDIR:-/tmp}/plumb-bootstrap.XXXXXX") || { bad "config: cannot create a temporary file"; tmp_rest=""; }
  if [ -n "$tmp_rest" ]; then
    trap 'rm -f "$tmp_rest" "$tmp_rest.new"' EXIT
    if [ -f "$cfgfile" ]; then
      # Everything outside the managed block. A block that starts the file takes the one blank line
      # that separates it from the rest, so that rewriting is stable. An unterminated block is
      # refused (exit 3 from awk): its end is unknown, and guessing would eat the owner's lines.
      awk -v b="$BEGIN_MARK" -v e="$END_MARK" '
        { line = $0; sub(/\r$/, "", line); sub(/[[:space:]]+$/, "", line) }
        inb { if (line == e) { inb = 0; if (lead) skip = 1 } ; next }
        line == b { inb = 1; lead = (NR == 1); next }
        skip { skip = 0; lead = 0; if (line == "") next }
        { print $0 }
        END { if (inb) exit 3 }' "$cfgfile" > "$tmp_rest"
      strip=$?
    else
      : > "$tmp_rest"; strip=0
    fi
    if [ "$strip" -ne 0 ]; then
      bad "config: $cfgfile has '$BEGIN_MARK' without '$END_MARK'; left untouched. Add the closing line or delete the block"
    else
      # Report a given key that the owner also wrote outside the block (the block is first, so it wins).
      for k in "${keys_given[@]}"; do
        if awk -v k="$k" '
            { line = $0; sub(/\r$/, "", line); sub(/^[[:space:]]+/, "", line) }
            index(line, k) == 1 { rest = substr(line, length(k) + 1); sub(/^[[:space:]]*/, "", rest)
                                  if (substr(rest, 1, 1) == "=") { found = 1; exit } }
            END { exit found ? 0 : 1 }' "$tmp_rest"; then
          note "--" "config: $k is also set outside the managed block; the block's value is the one plumb reads"
        fi
      done
      {
        printf '%s\n' "$BEGIN_MARK"
        printf '%s\n' "# written by plumb-bootstrap; the next run replaces everything between these two lines"
        printf '%s\n' "${block_lines[@]}"
        printf '%s\n' "$END_MARK"
        if [ -s "$tmp_rest" ]; then printf '\n'; cat "$tmp_rest"; [ -z "$(tail -c1 "$tmp_rest")" ] || printf '\n'; fi
      } > "$tmp_rest.new"
      if [ -f "$cfgfile" ] && cmp -s "$tmp_rest.new" "$cfgfile"; then
        note "ok" "config: managed block unchanged in $cfgfile (${keys_given[*]})"
      elif mkdir -p "$(dirname "$cfgfile")" 2>/dev/null && cat "$tmp_rest.new" > "$cfgfile" 2>/dev/null; then
        note "ok" "config: managed block written to $cfgfile (${keys_given[*]})"
      else
        bad "config: cannot write $cfgfile"
      fi
    fi
  fi
fi

cfg() { bash "$root/scripts/plumb-config.sh" "$1" "" 2>/dev/null; }

# ---- 2. checks ----
# plumb is installed
if ! command -v claude >/dev/null 2>&1; then
  bad "plumb: claude is not on PATH, so the install cannot be checked"
elif ! plist=$(bounded 60 claude plugin list --json 2>/dev/null); then
  bad "plumb: claude plugin list --json failed"
else
  if command -v python3 >/dev/null 2>&1; then
    pver=$(printf '%s' "$plist" | python3 -c '
import json, sys
try:
    items = json.load(sys.stdin)
except ValueError:
    sys.exit(2)
for item in items if isinstance(items, list) else []:
    if isinstance(item, dict) and item.get("id") == "plumb@plumb":
        print(str(item.get("version") or "unknown")[:40])
        sys.exit(0)
sys.exit(1)' 2>/dev/null)
    pcode=$?
  else
    if printf '%s' "$plist" | grep -q '"id"[[:space:]]*:[[:space:]]*"plumb@plumb"'; then pver=unknown; pcode=0; else pver=""; pcode=1; fi
  fi
  case "$pcode" in
    0) note "ok" "plumb@plumb is installed (version $pver)" ;;
    2) bad "plumb: claude plugin list --json did not return JSON" ;;
    *) bad "plumb@plumb is not installed (claude plugin marketplace add Haruki1090/plumb; claude plugin install plumb@plumb)" ;;
  esac
fi

# the judge resolves and, for codex, is logged in
jv=$(cfg role.judge)
if [ -z "$jv" ]; then
  note "--" "role.judge: unset (the main session stands in)"
else
  set -f; set -- $jv; set +f
  first=$1
  if ! command -v "$first" >/dev/null 2>&1; then
    bad "role.judge: $first is not on PATH"
  else
    case "$first" in
      codex|*/codex)
        # Only the exit status is used: what the command prints may name an account or a token.
        if bounded 30 "$first" login status >/dev/null 2>&1; then
          note "ok" "role.judge: $first resolves and is logged in"
        else
          bad "role.judge: $first is not logged in (run: codex login --device-auth)"
        fi ;;
      *) note "ok" "role.judge: $first resolves" ;;
    esac
  fi
fi

# the store answers
sv=$(cfg ledger.store)
if [ -z "$sv" ]; then
  note "--" "ledger.store: unset (records stay local; cloud sessions are not covered)"
elif ! command -v python3 >/dev/null 2>&1 || ! command -v git >/dev/null 2>&1; then
  note "--" "ledger.store: cannot check (python3 and git are needed)"
else
  scheck=$(bounded 60 bash "$root/bin/plumb-ledger" export --check 2>&1); scode=$?
  scheck=$(printf '%s\n' "$scheck" | awk 'NF{print; exit}' | mask)
  if [ "$scode" -eq 0 ] && [ "${scheck%% *}" = ok ]; then
    note "ok" "ledger.store answers (git ls-remote)"
  else
    bad "ledger.store: ${scheck#NG }"
  fi
fi

# plumb-doctor's overall line
if dout=$(bash "$root/scripts/doctor.sh" "$root" 2>&1); then dcode=0; else dcode=$?; fi
dlast=$(printf '%s\n' "$dout" | awk 'NF{l=$0} END{print l}' | sed -E 's/^[[:space:]]+//; s/^→[[:space:]]*//' | mask)
if [ "$dcode" -eq 0 ]; then
  note "ok" "plumb-doctor: ${dlast:-healthy}"
else
  bad "plumb-doctor: ${dlast:-exit $dcode}"
fi

if [ "$strict" -eq 1 ] && [ "$fail" -ne 0 ]; then exit 1; fi
exit 0
