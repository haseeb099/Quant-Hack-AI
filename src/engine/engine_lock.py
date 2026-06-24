"""Single-instance lock for live trading engine processes."""

from __future__ import annotations

import atexit
import os
import sys
from pathlib import Path

_LOCK_PATH = Path(__file__).resolve().parents[2] / "data" / "engine.lock"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        synchronize = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_lock_pid(path: Path) -> int | None:
    try:
        first = path.read_text(encoding="utf-8").strip().split()[0]
        return int(first)
    except (OSError, ValueError, IndexError):
        return None


class EngineProcessLock:
    """Prevent multiple live engines from trading the same MT5 account."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _LOCK_PATH
        self._fd: int | None = None

    def acquire(self, *, mode: str) -> None:
        if mode != "live":
            return

        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            existing = _read_lock_pid(self.path)
            if existing is not None and _pid_alive(existing):
                raise RuntimeError(
                    f"Live engine already running (PID {existing}). "
                    f"Stop all other `python main.py --mode live` processes before starting."
                )
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass

        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            self._fd = os.open(str(self.path), flags)
        except FileExistsError as exc:
            existing = _read_lock_pid(self.path)
            if existing is not None and _pid_alive(existing):
                raise RuntimeError(
                    f"Live engine already running (PID {existing}). "
                    "Stop duplicate engines before restarting."
                ) from exc
            raise RuntimeError(
                f"Could not acquire engine lock at {self.path}. "
                "Remove stale lock only if no live engine is running."
            ) from exc

        payload = f"{os.getpid()} live\n"
        os.write(self._fd, payload.encode("utf-8"))
        atexit.register(self.release)

    def release(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        if not self.path.exists():
            return
        owner = _read_lock_pid(self.path)
        if owner == os.getpid():
            try:
                self.path.unlink()
            except OSError:
                pass


def acquire_live_engine_lock(mode: str) -> EngineProcessLock:
    lock = EngineProcessLock()
    lock.acquire(mode=mode)
    return lock
