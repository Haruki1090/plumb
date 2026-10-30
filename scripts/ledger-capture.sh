#!/usr/bin/env bash
# The Stop hook: record this session's new requests, in the background, when the owner opted in.
#
# It reads ledger.capture through plumb-config.sh and returns before starting Python unless the
# value is `on`. When on, it saves the hook JSON (session_id, transcript_path, cwd) to a temporary
# file and starts `ledger.py capture --hook-input <file>` detached (output discarded; the capture
# keeps its own log under the run root), then returns. It never fails a turn: no `set -e`, every
# step is allowed to fail, and the exit status is always 0.
dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd) || exit 0

[ "$(bash "$dir/plumb-config.sh" ledger.capture off 2>/dev/null)" = on ] || exit 0
[ -t 0 ] && exit 0
command -v python3 >/dev/null 2>&1 || exit 0

tmp=$(mktemp "${TMPDIR:-/tmp}/plumb-ledger-hook.XXXXXX" 2>/dev/null) || exit 0
cat > "$tmp" 2>/dev/null || { rm -f "$tmp"; exit 0; }

# The subshell and the redirections keep the hook's pipes from being held by the capture.
( nohup python3 "$dir/ledger.py" capture --hook-input "$tmp" </dev/null >/dev/null 2>&1 & ) >/dev/null 2>&1
exit 0
