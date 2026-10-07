import contextlib
import hashlib
import os
from pathlib import Path
from typing import Iterator, Optional

import psutil

from ..frames import FrameSource, NullFrameSource

PORT_ENV = "Spelunky_RL_Port"  # read by mod/lua/spelunky2rl/protocol.lua


class Launcher:
    """Starts one game instance whose Lua mod connects to 127.0.0.1:port, and tears it down.

    The engine calls, in order: starting() around the whole startup, start(port), polls is_running()
    until the mod connects, and stop() on close. start() may be called again after stop() to retry.
    """

    # (width, height) of the X screen the game draws on, read by start(); the engine sets it from
    # render_resolution
    screen = (640, 360)

    def starting(self, timeout: float) -> "contextlib.AbstractContextManager[None]":
        """Held from before start() until the mod has connected."""
        return contextlib.nullcontext()

    def start(self, port: int) -> None:
        raise NotImplementedError

    def is_running(self) -> bool:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def frame_source(self) -> FrameSource:
        return NullFrameSource(f"{type(self).__name__} does not support render()")

    def diagnostics(self) -> str:
        """Recent launcher output, appended to startup errors."""
        return ""


def check_game_dir(game_dir) -> Path:
    game_dir = Path(game_dir).expanduser().resolve()
    if not (game_dir / "Spel2.exe").is_file():
        raise FileNotFoundError(f"No Spel2.exe in {game_dir}: pass the Spelunky 2 folder as game_dir "
                                f"or set SPELUNKY2RL_GAME_DIR")
    return game_dir


_exe_hashes = {}


def game_version_hash(game_dir: Path) -> str:
    """Short hash of Spel2.exe: Playlunky's cache is only valid for one game build."""
    exe = game_dir / "Spel2.exe"
    key = (str(exe), exe.stat().st_mtime_ns, exe.stat().st_size)
    if key not in _exe_hashes:
        digest = hashlib.sha256()
        with open(exe, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                digest.update(chunk)
        _exe_hashes[key] = digest.hexdigest()[:16]
    return _exe_hashes[key]


def cache_root() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "spelunky2rl"


def find_game_process(port: int) -> Optional[psutil.Process]:
    """The Spel2.exe started for this port. Matched by environment, never by name alone:
    other instances run the same executable."""
    for process in psutil.process_iter(["name"]):
        if not (process.info["name"] or "").lower().startswith("spel2"):
            continue
        try:
            if process.environ().get(PORT_ENV) == str(port):
                return process
        except (psutil.Error, OSError):
            continue
    return None


def terminate(process, timeout: float = 5) -> None:
    """Terminate a subprocess.Popen or psutil.Process, killing it if it does not exit."""
    if process is None:
        return
    try:
        process.terminate()
        process.wait(timeout=timeout)
    except Exception:
        with contextlib.suppress(Exception):
            process.kill()
            process.wait(timeout=timeout)


class PlaylunkyCache:
    """Playlunky's converted-assets cache (Mods/Packs/.db), shared by every instance of one game build.

    Playlunky builds it on the first start (~825 MB, a few seconds). Several instances starting on an
    empty cache would build it at the same time, so the first one holds an exclusive lock on a file in
    the cache until its game has connected; the others wait. Once built, nobody locks.
    """

    READY = ".spelunky2rl-ready"

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)

    @property
    def ready(self) -> bool:
        return (self.path / self.READY).exists()

    @contextlib.contextmanager
    def building(self, timeout: float) -> Iterator[None]:
        if self.ready:
            yield
            return
        import fcntl
        import time

        with open(self.path.parent / f"{self.path.name}.lock", "w") as lock:
            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() > deadline:
                        raise TimeoutError(f"Waited {timeout} s for another instance to build {self.path}") from None
                    time.sleep(0.2)
            if self.ready:
                # built by the instance we waited for: start without serialising behind the lock
                fcntl.flock(lock, fcntl.LOCK_UN)
                yield
                return
            try:
                yield
                (self.path / self.READY).touch()
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
