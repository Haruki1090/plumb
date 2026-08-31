#!/usr/bin/env bash
# Pin the revision of a PR, and detect drift between body and diff plus holes in branch protection.
#
# Usage: plumb-pr-drift <owner/repo> <PR number>
#
# Always compare timestamps as UTC ISO8601. git's %cI carries a local timezone offset, which breaks
# string comparison, so the comparison happens on the Python side after parsing into datetime.

set -euo pipefail

REPO="${1:?usage: plumb-pr-drift <owner/repo> <pr-number>}"
PR="${2:?usage: plumb-pr-drift <owner/repo> <pr-number>}"
OWNER="${REPO%%/*}"
NAME="${REPO##*/}"

meta="$(gh api graphql -f query="
{
  repository(owner: \"${OWNER}\", name: \"${NAME}\") {
    pullRequest(number: ${PR}) {
      title
      headRefOid
      baseRefName
      createdAt
      lastEditedAt
      additions
      deletions
      changedFiles
      commits(last: 250) {
        nodes { commit { oid committedDate messageHeadline } }
      }
    }
  }
}")"

rules="$(gh api "repos/${REPO}/rules/branches/$(printf '%s' "$meta" | python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["repository"]["pullRequest"]["baseRefName"])')" 2>/dev/null || echo '[]')"

META="$meta" RULES="$rules" python3 <<'PY'
import json, os
from datetime import datetime

pr = json.loads(os.environ["META"])["data"]["repository"]["pullRequest"]
rules = json.loads(os.environ["RULES"])

def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))

head = pr["headRefOid"]
edited = pr["lastEditedAt"] or pr["createdAt"]
commits = [c["commit"] for c in pr["commits"]["nodes"]]

print("=" * 68)
print(f"  {pr['title']}")
print("=" * 68)
print(f"SHA under review : {head}")
print(f"base branch      : {pr['baseRefName']}")
print(f"size             : {pr['changedFiles']} files  +{pr['additions']} -{pr['deletions']}")
print(f"body last edited : {edited}")

# --- body drift ------------------------------------------------------------
after = [c for c in commits if ts(c["committedDate"]) > ts(edited)]
print()
print("-- Body drift " + "-" * 54)
if not after:
    print("No commits after the body was edited. (Whether the body was incomplete from the start is stage 1's job.)")
else:
    print(f"!! {len(after)} commits landed after the body was written. The body does not describe the current diff.")
    for c in after:
        print(f"   {c['oid'][:8]}  {c['committedDate']}  {c['messageHeadline'][:64]}")
    base = None
    for c in commits:
        if ts(c["committedDate"]) <= ts(edited):
            base = c["oid"]
    if base:
        print()
        print(f"   To see the undeclared changes:  git diff --stat {base[:8]}..{head[:8]}")

# --- when an approval gets dismissed ---------------------------------------
print()
print("-- Approval protection settings " + "-" * 36)
pull = next((r for r in rules if r.get("type") == "pull_request"), None)
strict = next((r for r in rules if r.get("type") == "required_status_checks"), None)

if pull is None:
    print("!! No pull_request rule on the base branch. Review approval is not a condition of merging.")
else:
    p = pull["parameters"]
    risks = [
        ("dismiss_stale_reviews_on_push", p.get("dismiss_stale_reviews_on_push"),
         "an approval survives a push made after it. A different SHA can get merged"),
        ("require_last_push_approval", p.get("require_last_push_approval"),
         "whoever pushed last can merge it themselves"),
        ("required_review_thread_resolution", p.get("required_review_thread_resolution"),
         "it can be merged with review threads still unresolved"),
    ]
    print(f"   required_approving_review_count = {p.get('required_approving_review_count')}")
    for key, val, why in risks:
        mark = "!!" if val is False else "OK"
        print(f"   {mark} {key} = {val}  … {why}" if val is False else f"   {mark} {key} = {val}")

if strict is not None and strict["parameters"].get("strict_required_status_checks_policy") is False:
    print("   !! strict_required_status_checks_policy = False"
          "  … it can be merged without being up to date with base (semantic conflicts go undetected)")

print()
print("Next: stage 1 of SKILL.md (bidirectional inventory). Do not hand the body to the side that reconstructs the diff.")
PY
