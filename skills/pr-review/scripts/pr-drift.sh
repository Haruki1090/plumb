#!/usr/bin/env bash
# PR の版を固定し、本文と差分のドリフト・保護設定の穴を検出する。
#
# 使い方: pr-drift.sh <owner/repo> <PR番号>
#
# 日時は必ず UTC の ISO8601 で比較する。git の %cI はローカルタイムゾーン付きで
# 文字列比較が壊れるため、比較は Python 側で datetime に落としてから行う。

set -euo pipefail

REPO="${1:?usage: pr-drift.sh <owner/repo> <pr-number>}"
PR="${2:?usage: pr-drift.sh <owner/repo> <pr-number>}"
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
print(f"レビュー対象 SHA : {head}")
print(f"base ブランチ    : {pr['baseRefName']}")
print(f"規模             : {pr['changedFiles']} files  +{pr['additions']} -{pr['deletions']}")
print(f"本文の最終編集   : {edited}")

# --- 本文ドリフト -----------------------------------------------------------
after = [c for c in commits if ts(c["committedDate"]) > ts(edited)]
print()
print("-- 本文ドリフト " + "-" * 52)
if not after:
    print("本文編集後のコミットなし。（本文が最初から不完全な可能性は別途 1 段で見る）")
else:
    print(f"!! 本文を書いた後に {len(after)} コミット入っている。本文は現在の差分を説明していない。")
    for c in after:
        print(f"   {c['oid'][:8]}  {c['committedDate']}  {c['messageHeadline'][:64]}")
    base = None
    for c in commits:
        if ts(c["committedDate"]) <= ts(edited):
            base = c["oid"]
    if base:
        print()
        print(f"   未申告の変更を見るには:  git diff --stat {base[:8]}..{head[:8]}")

# --- 承認の失効設定 ---------------------------------------------------------
print()
print("-- 承認まわりの保護設定 " + "-" * 44)
pull = next((r for r in rules if r.get("type") == "pull_request"), None)
strict = next((r for r in rules if r.get("type") == "required_status_checks"), None)

if pull is None:
    print("!! base ブランチに pull_request ルールが無い。レビュー承認はマージの条件になっていない。")
else:
    p = pull["parameters"]
    risks = [
        ("dismiss_stale_reviews_on_push", p.get("dismiss_stale_reviews_on_push"),
         "承認後に push しても承認が生き残る。別 SHA がマージされ得る"),
        ("require_last_push_approval", p.get("require_last_push_approval"),
         "最後に push した本人がそのままマージできる"),
        ("required_review_thread_resolution", p.get("required_review_thread_resolution"),
         "未解決のレビュースレッドがあってもマージできる"),
    ]
    print(f"   required_approving_review_count = {p.get('required_approving_review_count')}")
    for key, val, why in risks:
        mark = "!!" if val is False else "OK"
        print(f"   {mark} {key} = {val}  … {why}" if val is False else f"   {mark} {key} = {val}")

if strict is not None and strict["parameters"].get("strict_required_status_checks_policy") is False:
    print("   !! strict_required_status_checks_policy = False"
          "  … base に追従していない状態でマージできる（意味的コンフリクトを検出しない）")

print()
print("次: SKILL.md の 1 段（双方向の棚卸し）へ。差分側の復元には本文を渡さないこと。")
PY
