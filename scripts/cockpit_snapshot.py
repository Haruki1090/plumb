"""Capture Git worktree state without changing the worktree index."""

from __future__ import annotations

import os
import stat
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from cockpit import git


def artifact_path(worktree, store):
    return store.relative_to(worktree).as_posix() if worktree in store.parents else None


def snapshot(worktree, store, *, protected=(), index_dir=None, overrides=None):
    artifact = artifact_path(worktree, store)
    pathspec = ["."]
    with TemporaryDirectory(prefix="snapshot-", dir=index_dir or store) as temp:
        env = {**(overrides or {}), "GIT_INDEX_FILE": str(Path(temp) / "index")}
        git(worktree, "read-tree", "HEAD", overrides=env)
        if artifact:
            git(worktree, "rm", "-qrf", "--cached", "--ignore-unmatch", "--",
                f":(top,literal){artifact}", overrides=env)
            pathspec.append(f":(exclude,top,literal){artifact}")
        git(worktree, "add", "--all", "--", *pathspec, overrides=env)
        tree = git(worktree, "write-tree", overrides=env).decode("ascii").strip()
        ignored = protected_ignored(worktree, protected, artifact, env) if protected else {}
    return tree, ignored


def tree_diff(worktree, before, after, *, artifact=None, status=False):
    pathspec = ["."]
    if artifact:
        pathspec.append(f":(exclude,top,literal){artifact}")
    output = git(worktree, "diff-tree", "-r", "--name-status" if status else "--name-only", "-z",
                 "--no-renames", "--ignore-submodules=none", before, after, "--", *pathspec)
    return os.fsdecode(output).split("\0")[:-1]


def protected_path(worktree, name):
    relative = Path(name)
    if (relative.is_absolute() or not relative.parts or relative.as_posix() != name
            or ".." in relative.parts or ".git" in relative.parts):
        return None
    path = worktree / relative
    return path if path.parent.resolve() == path.parent else None


def protected_ignored(worktree, paths, artifact, env):
    candidates = set()
    for name in paths:
        if artifact and (name == artifact or name.startswith(artifact + "/")):
            continue
        path = protected_path(worktree, name)
        if path and (path.is_symlink() or path.is_file()):
            candidates.add(name)
    if not candidates:
        return {}
    pathspec = [f":(top,literal){path}" for path in sorted(candidates)]
    ignored = git(worktree, "ls-files", "--others", "--ignored", "--exclude-standard", "-z", "--",
                  *pathspec, overrides=env)
    return {name: fingerprint(worktree, name) for name in os.fsdecode(ignored).split("\0") if name in candidates}


def fingerprint(worktree, name):
    try:
        path = protected_path(worktree, name)
        if path is None:
            return None
        info = path.lstat()
        mode = info.st_mode
        value = {"type": stat.S_IFMT(mode), "mode": stat.S_IMODE(mode), "size": info.st_size}
        if stat.S_ISLNK(mode):
            value["target"] = os.readlink(path)
        elif stat.S_ISREG(mode):
            digest = sha256()
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(128 * 1024), b""):
                    digest.update(block)
            value["sha256"] = digest.hexdigest()
        return value
    except (FileNotFoundError, NotADirectoryError):
        return None
