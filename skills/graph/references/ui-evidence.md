# Putting screenshots of a UI change in the PR

The practical side of SKILL.md step 10. **A graph that touched frontend or UI pastes the screens into its result (best effort).**

The conclusions first:

1. **Secure the before state first.** It does not exist after implementation. If you forgot, restore it with `git archive`
2. Capture with **headless Chrome**. Take the shots while the node that drives the real thing is already open
3. If it goes into the repository, **convert to WebP**. PNG is heavy
4. **In a private repository, `raw.githubusercontent.com` does not render.** Use `github.com/.../blob/<SHA>/...?raw=true`
5. **GitHub has no API for uploading an image into a PR body.** To automate it there is almost no route but committing to the repository

## What to capture

The minimum that carries the claim of the change. Lining up every screen means nobody reads them.

| What to capture | Why |
| --- | --- |
| Before -> after | one alone does not tell you what changed. Reviewing a UI change is comparison, not diff |
| The branches of state | by role, empty state, error state. What the implementation separates should be shown separated |
| Where the path lands | if you repointed a link, show it arriving where it was meant to. The origin alone verifies nothing |

What you can **skip**: screens that did not change, another resolution of the same change, variations that are decoration only.

## 1. Secure the before state

Capturing it before you start implementing is the cheapest route. If you forgot, expand the pre-change commit and capture that.

```bash
# expand just the target directory from the pre-change commit into /tmp
git archive <before-sha> path/to/app | tar -x -C /tmp/before --strip-components=2
```

Do not rewind the working tree with `git stash` or `git checkout`. **That takes down the nodes running in parallel with it.** Expanding somewhere else is safe.

## 2. Capture

For a static mock, serve it over HTTP and use headless Chrome. Avoid `file://` — localStorage is sometimes unavailable there.

```bash
cd /tmp/before && python3 -m http.server 8942 &
cd path/to/app && python3 -m http.server 8941 &
```

```bash
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
"$CHROME" --headless=new --disable-gpu --hide-scrollbars \
  --force-device-scale-factor=2 --user-data-dir=/tmp/cp_01 \
  --virtual-time-budget=3500 --window-size=1440,1560 \
  --screenshot=/tmp/shots/01.png "http://localhost:8941/page.html"
```

- `--force-device-scale-factor=2` — capture at 2x and downscale afterwards; the type comes out tighter
- The height in `--window-size` — **give it a height the whole page fits into**. Too short and the bottom is cut off. If it is cut, raise the height and reshoot
- Change `--user-data-dir` for every capture. Reuse it and you hang waiting on the profile lock
- `--virtual-time-budget` is the wait for fonts to load

**Headless Chrome sometimes does not exit after the capture.** Waiting on it times the shell out, so start it in the background and kill it once the file exists:

```bash
( "$CHROME" ... --screenshot="$OUT" "$URL" >/dev/null 2>&1 ) &
P=$!; for i in $(seq 1 25); do sleep 1; [ -s "$OUT" ] && break; done
sleep 1; kill $P 2>/dev/null
```

### Capturing a switched state

If the app holds state in localStorage, put a page in the served directory that writes the state and redirects, and nothing else (delete it after the shoot).

```html
<!doctype html><meta charset="utf-8"><script>
var q=new URLSearchParams(location.search);
localStorage.setItem("<key>", JSON.stringify({ role: q.get("role") }));
location.replace(q.get("to"));
</script>
```

`__role.html?role=VIEWER&to=page.html` takes the shot. It is faster and more reproducible than writing localStorage and reloading through a browser automation tool every time.

## 3. Make it light

WebP if it goes into the repository. Measured at one fifth of the PNG.

```bash
sips -Z 1440 shot.png --out shot.png     # bring the 2x capture back to 1x
cwebp -q 82 shot.png -o shot.webp        # roughly 300KB -> 60KB
```

Do not use JPEG for UI screenshots (the type smears). GitHub Markdown renders WebP.

## 4. Where to put them

**GitHub has no public API for uploading an image into a PR body or a comment.** Posting to `user-images.githubusercontent.com` goes through a private, web-UI-only endpoint, so `gh` cannot reach it. Browser automation gets blocked by the tool's own upload restrictions often enough too.

| Route | Works | Notes |
| --- | --- | --- |
| Commit into the repository | yes | to automate it, effectively the only choice |
| Drag and drop into the web UI | yes | fast for a human, and the repository stays clean |
| `gh release upload` | partly | a private repo still needs auth, and cutting a release for screenshots is the wrong shape |
| Gist / external hosting | no | it puts a non-public screen outside |

If you commit them, **a repository with no images in it yet is one where you are setting a new precedent.** Do not do it silently.

- Put them next to the source of that screen (`mocks/<release>/screenshots/` or similar)
- **Put a README in the same directory** — the capture commands and an index. Without it, whoever comes next sees binaries of unknown origin
- If there is a file-ownership list or a parent README, link from there
- Write "delete these if you don't want them" in the PR body, and leave the call to the other side

## 5. Paste them into the body

**In a private repository, `raw.githubusercontent.com` images do not render** (auth does not pass and you get a broken link). Use this:

```markdown
![description](https://github.com/<owner>/<repo>/blob/<commit-sha>/path/to/shot.webp?raw=true)
```

- Put the **commit SHA, not the branch name**, in it. The link survives deleting the branch after the merge
- Order: commit the images -> `git push` -> take the SHA -> `gh pr edit --body-file`. The body update comes last because it needs the SHA

Once pasted, **always check it renders in a browser**. A broken image is still valid Markdown, so nothing tells you.

### A Markdown trap in CJK text

`**` placed directly against a CJK character or a bracket does not turn into bold (CommonMark's flanking rules), so a bold run wrapping a bracketed tab name inside a CJK sentence renders as literal asterisks. Put an ASCII space on both sides of the run.

GitHub autolinks `#11` as an issue or PR number. **When you write a number from some other system — a Figma comment number, say — put it in a code span as `` `#11` ``**, or it becomes a link to an unrelated PR.

## Where this sits on the graph

Do not create a node just for capture. **Fold it into the responsibility of the verification node that drives the real thing** (it only opens the same screen twice).

In the graph definition, under "## How the result is shown", write one line each for the screens to capture, how the before state is secured, and which verification node captures them. **Securing the before state belongs on the barrier side** — before implementation starts — which is the safe place for it.
