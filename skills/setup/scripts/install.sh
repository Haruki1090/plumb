#!/usr/bin/env bash
# Resolve the installed plugin from this setup skill and delegate to the guarded sidecar installer.
set -u

skill_root=$(cd "$(dirname "$0")/.." && pwd)
plugin_root=$(cd "$skill_root/../.." && pwd)

exec "$plugin_root/bin/plumb-codex-install" "$@"
