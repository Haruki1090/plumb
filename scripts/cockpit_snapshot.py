"""Capture Git worktree state without changing the worktree index."""

from __future__ import annotations

import os
import stat
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from cockpit import Invalid, git

PROTECTED_ENTRY_LIMIT = 10_000
TOO_LARGE = {"too_large": True}


def artifact_path(worktree, store):
    return store.relative_to(worktree).as_posix() if worktree in store.parents else None


def is_artifact(name, artifact):
    return artifact and (name == artifact or name.startswith(artifact + "/"))


def sparse_checkout(worktree):
    if git(worktree, "config", "--type=bool", "--get", "core.sparseCheckout", allowed=(0, 1)).strip() == b"true":
        return True
    # Let ls-files read sparse directory entries even when the checkout settings were disabled.
    entries = git(worktree, "-c", "core.sparseCheckout=true", "-c", "core.sparseCheckoutCone=true",
                  "-c", "index.sparse=true", "ls-files", "--sparse", "--stage", "-z")
    return any(entry.startswith(b"040000 ") for entry in entries.split(b"\0"))


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
    if relative.is_absolute() or ".." in relative.parts:
        raise Invalid(f"protected path must be relative and cannot contain '..': {name!r}")
    if not relative.parts or any(part.lower() == ".git" for part in relative.parts):
        return None
    parent = worktree
    for part in relative.parts[:-1]:
        parent /= part
        if parent.is_symlink() or nested_checkout(parent):
            return None
    return worktree / relative


def nested_checkout(path):
    marker = path / ".git"
    return marker.is_symlink() or marker.exists()


def protected_ignored(worktree, paths, artifact, env):
    candidates = set()
    fingerprints = {}
    for name in paths:
        path = protected_path(worktree, name)
        if path is None:
            continue
        name = path.relative_to(worktree).as_posix()
        if name in fingerprints or is_artifact(name, artifact):
            continue
        try:
            info = path.lstat()
        except (FileNotFoundError, NotADirectoryError):
            fingerprints[name] = None
            continue
        if stat.S_ISDIR(info.st_mode):
            if not nested_checkout(path):
                fingerprints[name] = fingerprint(worktree, name, artifact)
        else:
            candidates.add(name)
    if candidates:
        pathspec = [f":(top,literal){path}" for path in sorted(candidates)]
        ignored = git(worktree, "ls-files", "--others", "--ignored", "--exclude-standard", "-z", "--",
                      *pathspec, overrides=env)
        fingerprints.update((name, fingerprint(worktree, name, artifact))
                            for name in os.fsdecode(ignored).split("\0") if name in candidates)
    return dict(sorted(fingerprints.items()))


def protected_fingerprints(worktree, paths, artifact):
    return {name: fingerprint(worktree, name, artifact) for name in paths}


def fingerprint(worktree, name, artifact):
    try:
        path = protected_path(worktree, name)
        if path is None or is_artifact(name, artifact):
            return None
        info = path.lstat()
        value = entry_fingerprint(path, info)
        if stat.S_ISDIR(info.st_mode):
            if nested_checkout(path):
                return None
            entries = directory_entries(worktree, path, artifact)
            if entries is None:
                return TOO_LARGE
            value["entries"] = entries
        return value
    except (FileNotFoundError, NotADirectoryError):
        return None


def directory_entries(worktree, root, artifact):
    pending = [root]
    entries = {}
    while pending:
        with os.scandir(pending.pop()) as scan:
            for entry in scan:
                path = Path(entry.path)
                if entry.name.lower() == ".git" or is_artifact(path.relative_to(worktree).as_posix(), artifact):
                    continue
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode) and nested_checkout(path):
                    continue
                if len(entries) == PROTECTED_ENTRY_LIMIT:
                    return None
                entries[path.relative_to(root).as_posix()] = entry_fingerprint(path, info)
                if stat.S_ISDIR(info.st_mode):
                    pending.append(path)
    return dict(sorted(entries.items()))


def entry_fingerprint(path, info):
    mode = info.st_mode
    value = {"type": stat.S_IFMT(mode), "mode": stat.S_IMODE(mode)}
    if not stat.S_ISDIR(mode):
        value["size"] = info.st_size
    if stat.S_ISLNK(mode):
        value["target"] = os.readlink(path)
    elif stat.S_ISREG(mode):
        digest = sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(128 * 1024), b""):
                digest.update(block)
        value["sha256"] = digest.hexdigest()
    return value
