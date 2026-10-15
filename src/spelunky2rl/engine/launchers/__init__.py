import os
import sys
from typing import Optional, Union

from .base import Launcher, PlaylunkyCache

LAUNCHERS = ("docker", "wine")


def make_launcher(launcher: Union[str, Launcher], game_dir: Optional[str], renderer: str = "auto",
                  options: Optional[dict] = None, cpu_threads: Optional[int] = None,
                  gpu_memory_mb: Optional[int] = None) -> Launcher:
    """Build the launcher named by `launcher` ("auto", "docker", "wine"), or pass an instance through."""
    if isinstance(launcher, Launcher):
        return launcher
    if launcher == "windows" or sys.platform == "win32":
        raise NotImplementedError("Running the game on Windows is not implemented yet; use Linux (Docker)")
    options = dict(options or {})
    name = launcher
    if name == "auto":
        name = os.environ.get("SPELUNKY2RL_LAUNCHER") or "docker"
    game_dir = game_dir or os.environ.get("SPELUNKY2RL_GAME_DIR")
    if not game_dir:
        raise ValueError("Where is Spelunky 2? Pass game_dir= (the folder with Spel2.exe) or set SPELUNKY2RL_GAME_DIR")

    if name == "docker":
        from .docker import DockerLauncher

        return DockerLauncher(game_dir, renderer=renderer, cpu_threads=cpu_threads, gpu_memory_mb=gpu_memory_mb,
                              **options)
    if name == "wine":
        from .wine import WineLauncher

        return WineLauncher(game_dir, renderer=renderer, cpu_threads=cpu_threads, gpu_memory_mb=gpu_memory_mb,
                            **options)
    raise ValueError(f"launcher must be 'auto', one of {LAUNCHERS}, or a Launcher instance; got {launcher!r}")


__all__ = ["LAUNCHERS", "Launcher", "PlaylunkyCache", "make_launcher"]
