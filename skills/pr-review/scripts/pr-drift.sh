#!/usr/bin/env bash
# Pin the revision of a PR, and detect drift between body and diff plus holes in branch protection.
#
# Usage: plumb-pr-drift <owner/repo> <PR number>
#
# Timestamps come from the GraphQL API as ISO8601, not from git. They are still parsed into
# datetime before being compared, rather than compared as strings: an offset form and a Z form
# denote the same instant while sorting differently as text, and the failure is silent - the
# ordering just comes out wrong, with nothing to catch it.

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
        totalCount
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
# The query takes the last 250. Past that the oldest are dropped, which is exactly where `base`
# is looked for below, so a big PR would silently lose the diff command instead of reporting it.
truncated = pr["commits"]["totalCount"] - len(commits)

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
    elif truncated:
        print()
        print(f"   !! Cannot pin the base: this PR has {pr['commits']['totalCount']} commits and only")
        print(f"      the last 250 were fetched, so the {truncated} oldest are not here. Get the base")
        print( "      from the PR's own commit list instead of trusting this section.")

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
