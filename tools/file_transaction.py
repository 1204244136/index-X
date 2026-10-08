"""Exception-safe filesystem writes; no publication or EPUB policy."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".extract-write-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _cleanup(path: Path) -> None:
    try:
        shutil.rmtree(path)
    except OSError as exc:
        # Cleanup failure must not turn an already committed operation into failure.
        print(f"Transaction cleanup retained {path}: {exc}", file=sys.stderr)


@contextmanager
def rollback_paths(paths):
    """Snapshot explicit, non-overlapping targets; restore bytes and metadata.

    Backups live beside targets (same filesystem). On rollback failure, keep
    recovery copies and report their paths. This is not a crash-safe journal
    or a lock against concurrent writers.
    """
    targets = list(dict.fromkeys(Path(p).absolute() for p in paths))
    for index, path in enumerate(targets):
        if path.is_symlink():
            raise OSError(f"Transaction target must not be a symlink: {path}")
        if any(path.resolve().is_relative_to(other.resolve())
               or other.resolve().is_relative_to(path.resolve())
               for other in targets[:index]):
            raise OSError(f"Overlapping transaction targets: {path}")
    snapshots = []
    try:
        for path in targets:
            path.parent.mkdir(parents=True, exist_ok=True)
            directory = Path(tempfile.mkdtemp(prefix=".extract-transaction-", dir=path.parent))
            snapshots.append((path, directory))
            backup = directory / "original"
            if path.is_dir():
                shutil.copytree(path, backup, symlinks=True)
            elif path.exists():
                shutil.copy2(path, backup)
    except BaseException:
        for _, directory in snapshots:
            _cleanup(directory)
        raise

    try:
        yield
    except BaseException as original_error:
        failures = []
        for path, directory in reversed(snapshots):
            backup, displaced = directory / "original", directory / "failed"
            try:
                if path.exists():
                    os.replace(path, displaced)
                if backup.exists():
                    os.replace(backup, path)
            except OSError as exc:
                # Retain the old version even if the filesystem refuses recovery.
                failures.append(f"{path}: {exc}; recovery={directory}")
                if displaced.exists() and not path.exists():
                    try:
                        os.replace(displaced, path)
                    except OSError:
                        pass
            else:
                _cleanup(directory)
        if failures:
            raise OSError("Rollback incomplete: " + "; ".join(failures)) from original_error
        raise
    else:
        for _, directory in snapshots:
            _cleanup(directory)
