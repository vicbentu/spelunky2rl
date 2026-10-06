import contextlib
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

from ..assemble import assemble_instance
from ..frames import FrameSource
from .base import (PORT_ENV, Launcher, PlaylunkyCache, cache_root, check_game_dir, find_game_process,
                   game_version_hash, terminate)

WINESERVER_FALLBACK = "/usr/lib/x86_64-linux-gnu/wine/wineserver"  # Ubuntu does not put it on PATH


def default_wine_home() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return Path(base) / "spelunky2rl" / "wine"


class WineLauncher(Launcher):
    """Runs the game under the host's Wine, without Docker. Meant for development.

    Expects the layout made by scripts/setup_wine.sh in wine_home (default
    ~/.local/share/spelunky2rl/wine, or SPELUNKY2RL_WINE_HOME): the assets from
    docker/fetch_assets.sh plus a base Wine prefix with DXVK. Each instance gets its own Xvfb, its own
    game directory, and its own copy of the prefix: instances sharing one wineserver failed to load
    the mod now and then.
    """

    def __init__(self, game_dir, wine_home=None, renderer: str = "auto", dev_mod: Optional[str] = None,
                 wine: str = "wine"):
        if renderer not in ("auto", "gpu", "cpu"):
            raise ValueError(f"renderer must be 'auto', 'gpu' or 'cpu', got {renderer!r}")
        self.game_dir = check_game_dir(game_dir)
        self.home = Path(wine_home or os.environ.get("SPELUNKY2RL_WINE_HOME") or default_wine_home())
        for needed in ("playlunky/playlunky_launcher.exe", "playlunky/PATCHED", "steam_api64.dll", "prefix"):
            if not (self.home / needed).exists():
                raise FileNotFoundError(f"{self.home / needed} is missing: run scripts/setup_wine.sh first")
        self.renderer = renderer
        dev_mod = dev_mod or os.environ.get("SPELUNKY2RL_DEV_MOD")
        self.dev_mod = Path(dev_mod).expanduser().resolve() if dev_mod else None
        self.wine = wine
        self.wineserver = shutil.which("wineserver") or WINESERVER_FALLBACK
        self.cache = PlaylunkyCache(cache_root() / "playlunky" / "wine" / game_version_hash(self.game_dir))
        self.port = None
        self.display = None
        self._slot = None
        self._slot_lock = None
        self._instance_dir = None
        self._xvfb = None
        self._launcher = None
        self._game = None

    def starting(self, timeout: float):
        return self.cache.building(timeout)

    def _acquire_prefix(self) -> Path:
        """Lock a free prefix slot, creating its prefix from the base one the first time."""
        import fcntl

        slots = self.home / "prefixes"
        slots.mkdir(exist_ok=True)
        slot = 0
        while True:
            lock = open(slots / f"{slot}.lock", "w")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                lock.close()
                slot += 1
        self._slot, self._slot_lock = slot, lock
        prefix = slots / str(slot)
        if not prefix.exists():
            partial = slots / f"{slot}.partial"
            shutil.rmtree(partial, ignore_errors=True)
            subprocess.run(["cp", "-a", "--reflink=auto", str(self.home / "prefix"), str(partial)], check=True)
            partial.rename(prefix)
        return prefix

    def start(self, port: int) -> None:
        self.port = port
        self.display = f":{port}"
        prefix = self._acquire_prefix()

        self._instance_dir = Path(tempfile.mkdtemp(prefix=f"spelunky2rl-{port}-"))
        mod = None
        if self.dev_mod is not None:
            mod = self._instance_dir / "devpack"
            mod.mkdir()
            os.symlink(self.dev_mod, mod / "lua")
        game = assemble_instance(self.game_dir, self._instance_dir / "game", self.home / "steam_api64.dll",
                                 mod=mod, cache=self.cache.path)

        self._xvfb = subprocess.Popen(["Xvfb", self.display, "-screen", "0", "640x360x24", "-nolisten", "tcp"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        socket_path = Path(f"/tmp/.X11-unix/X{port}")
        deadline = time.monotonic() + 10
        while not socket_path.exists() and time.monotonic() < deadline and self._xvfb.poll() is None:
            time.sleep(0.05)

        env = dict(os.environ, WINEPREFIX=str(prefix), WINEDEBUG="-all", DISPLAY=self.display,
                   **{PORT_ENV: str(port)})
        if self.renderer == "cpu":
            lavapipe = sorted(Path("/usr/share/vulkan/icd.d").glob("lvp_icd*.json"))
            if not lavapipe:
                raise FileNotFoundError("renderer='cpu' needs Mesa's lavapipe (Ubuntu: apt install mesa-vulkan-drivers)")
            env["VK_DRIVER_FILES"] = env["VK_ICD_FILENAMES"] = str(lavapipe[0])
        exe_dir = "Z:" + str(game).replace("/", "\\")
        playlunky = self.home / "playlunky"
        self._launcher = subprocess.Popen([self.wine, str(playlunky / "playlunky_launcher.exe"),
                                           f"--exe_dir={exe_dir}"],
                                          cwd=playlunky, env=env,
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._env = env

    def is_running(self) -> bool:
        if self._game is None:
            self._game = find_game_process(self.port)
        if self._game is not None:
            return self._game.is_running()
        # the Playlunky launcher exits once the game is up, so only its early exit is a failure
        return self._launcher is not None and self._launcher.poll() is None

    def stop(self) -> None:
        if self._game is None and self.port is not None:
            self._game = find_game_process(self.port)
        terminate(self._game)
        terminate(self._launcher)
        if self._launcher is not None:
            with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                subprocess.run([self.wineserver, "-k"], env=self._env, timeout=15, capture_output=True)
        terminate(self._xvfb)
        if self._instance_dir is not None:
            shutil.rmtree(self._instance_dir, ignore_errors=True)
        if self._slot_lock is not None:
            self._slot_lock.close()
        self._game = self._launcher = self._xvfb = self._instance_dir = self._slot_lock = None

    def frame_source(self) -> FrameSource:
        from ..frames.x11 import X11FrameSource

        return X11FrameSource(self.display)
