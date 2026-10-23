"""Serialize cache transactions while every live participant holds an OS lock.

A short admission lock protects membership changes. Explicitly launched children
join their parent's token and hold their own member locks for their whole critical
section, so killing a parent cannot expose a still-running child to a new writer.
"""
from __future__ import annotations

import argparse
import contextvars
import errno
import json
import os
import re
import subprocess
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

from cli_output import configure_output
from file_transaction import atomic_write_bytes

LOCK_FILENAME = ".sync.lock"
MEMBER_PREFIX = ".sync-participant-"
LEASE_ENV = "INDEX_X_SYNC_LOCK"
_active = contextvars.ContextVar("sync_lock_leases", default={})


class SyncLockBusy(RuntimeError):
    """Another synchronization transaction owns this cache."""


def _cache_key(cache: Path) -> str:
    return os.path.normcase(str(cache.resolve()))


def _busy(cache: Path) -> SyncLockBusy:
    return SyncLockBusy(f"缓存正在由另一个同步进程使用：{cache}；请等待其完成后重试。")


def _environment_leases() -> dict[str, str]:
    try:
        value = json.loads(os.environ.get(LEASE_ENV, "{}"))
    except (TypeError, ValueError):
        return {}
    if not isinstance(value, dict):
        return {}
    return {key: token for key, token in value.items()
            if isinstance(key, str) and isinstance(token, str)}


def lock_environment() -> dict[str, str]:
    """Build the environment for a child that joins the current transaction."""
    environment = dict(os.environ)
    leases = _environment_leases()
    leases.update(_active.get())
    if leases:
        environment[LEASE_ENV] = json.dumps(leases)
    return environment


def _try_lock(handle) -> bool:
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
            return False
        raise
    return True


def _unlock(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _admission(cache: Path):
    # Keep this file so every process always locks the same inode.
    with (cache / LOCK_FILENAME).open("a+b") as handle:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"\0")
            handle.flush()
        if not _try_lock(handle):
            raise _busy(cache)
        try:
            yield
        finally:
            _unlock(handle)


def participant_paths(cache: Path, participant: str) -> tuple[Path, Path]:
    """Paths shared with the PowerShell native handle holder."""
    if re.fullmatch(r"[0-9a-f]{32}", participant) is None:
        raise ValueError("参与者标识必须为 32 位小写十六进制 UUID")
    base = cache / f"{MEMBER_PREFIX}{participant}"
    return base.with_suffix(".lock"), base.with_suffix(".json")


def _live_participants(cache: Path, *, exclude: str | None = None,
                       cleanup: bool = False) -> list[str | None]:
    """Probe member locks; anonymous live candidates also block admission.

    Cleanup is only called under admission. A PS candidate locks its file before
    registration; until its metadata exists it must block unrelated newcomers.
    """
    tokens = []
    for lock_path in sorted(cache.glob(f"{MEMBER_PREFIX}*.lock")):
        if lock_path.stem == f"{MEMBER_PREFIX}{exclude}":
            continue
        metadata = lock_path.with_suffix(".json")
        try:
            handle = lock_path.open("r+b")
        except FileNotFoundError:
            continue
        with handle:
            if _try_lock(handle):
                _unlock(handle)
                inactive = True
            else:
                inactive = False
        if inactive:
            if cleanup:
                try:
                    lock_path.unlink(missing_ok=True)
                    metadata.unlink(missing_ok=True)
                except PermissionError:
                    # An open Windows PS handle may precede its Lock call.
                    # Treat that pending participant as busy, never as absent.
                    tokens.append(None)
            continue
        try:
            owner = json.loads(metadata.read_text(encoding="utf-8"))
            token = owner.get("token") if isinstance(owner, dict) else None
        except (OSError, ValueError):
            token = None
        tokens.append(token if isinstance(token, str) and token else None)
    return tokens


def _choose_token(cache: Path, tokens: list[str | None]) -> str:
    if tokens:
        inherited = _environment_leases().get(_cache_key(cache))
        if inherited is None or any(token != inherited for token in tokens):
            raise _busy(cache)
        return inherited
    # An expired inherited lease cannot resurrect a transaction. Start a fresh
    # one only when admission confirms that every previous participant is gone.
    return uuid.uuid4().hex


def _register(cache: Path, participant: str, token: str) -> None:
    _, metadata = participant_paths(cache, participant)
    atomic_write_bytes(metadata, json.dumps(
        {"token": token, "pid": os.getpid()}).encode("utf-8"))


def inherited_lock_held(cache: Path) -> bool:
    """Read-only diagnostic; joining always requires a real participant lock."""
    cache = cache.resolve()
    inherited = _environment_leases().get(_cache_key(cache))
    if not inherited:
        return False
    try:
        tokens = _live_participants(cache)
    except OSError:
        return False
    return bool(tokens) and all(token == inherited for token in tokens)


def join_participant(cache: Path, participant: str) -> str:
    """Register a native caller that already holds its own member OS lock.

    PowerShell retains that handle until its finally block. This helper owns
    only admission, so its exit cannot release the PowerShell participant.
    The result is the exact LEASE_ENV value for the native caller's children.
    """
    cache = cache.resolve()
    lock_path, _ = participant_paths(cache, participant)
    with _admission(cache):
        with lock_path.open("r+b") as handle:
            if _try_lock(handle):
                _unlock(handle)
                raise ValueError("参与者尚未持有 OS 锁，拒绝登记同步事务")
        token = _choose_token(cache, _live_participants(
            cache, exclude=participant, cleanup=True))
        _register(cache, participant, token)
    leases = _environment_leases()
    leases[_cache_key(cache)] = token
    return json.dumps(leases)


@contextmanager
def cache_lock(cache: Path):
    """Hold a participant lock from baseline observation through state writes."""
    cache = cache.resolve()
    key = _cache_key(cache)
    active = _active.get()
    if key in active:
        yield
        return
    participant = uuid.uuid4().hex
    lock_path, metadata = participant_paths(cache, participant)
    handle = None
    try:
        with _admission(cache):
            token = _choose_token(cache, _live_participants(cache, cleanup=True))
            handle = lock_path.open("x+b")
            handle.write(b"\0")
            handle.flush()
            if not _try_lock(handle):
                raise _busy(cache)
            _register(cache, participant, token)
        reset = _active.set({**active, key: token})
        try:
            yield
        finally:
            _active.reset(reset)
    finally:
        if handle is not None:
            # Closing the handle releases its OS lock even after an exception.
            handle.close()
            try:
                with _admission(cache):
                    lock_path.unlink(missing_ok=True)
                    metadata.unlink(missing_ok=True)
            except (SyncLockBusy, OSError):
                # A later admission also removes inactive participants.
                pass


def main(argv: list[str] | None = None) -> int:
    configure_output()
    parser = argparse.ArgumentParser(description="持缓存锁运行同步子命令。")
    parser.add_argument("--cache", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check-held", action="store_true",
                      help="只读检查继承事务是否存活；不能替代参与者登记")
    mode.add_argument("--join-participant", metavar="ID",
                      help="登记已持 OS 锁的原生参与者，输出子进程环境 lease")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.check_held:
        return 0 if inherited_lock_held(args.cache) else 1
    try:
        if args.join_participant:
            print(join_participant(args.cache, args.join_participant))
            return 0
        command = args.command
        if command and command[0] == "--":
            command = command[1:]
        if not command:
            parser.error("必须在 -- 后提供要运行的命令")
        args.cache.mkdir(parents=True, exist_ok=True)
        with cache_lock(args.cache):
            return subprocess.run(command, env=lock_environment(), check=False).returncode
    except (SyncLockBusy, ValueError, OSError) as exc:
        print(f"[阻断] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
