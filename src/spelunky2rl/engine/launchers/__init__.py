import os
import sys
from typing import Optional, Union

from .base import Launcher, PlaylunkyCache

def make_launcher(launcher: Union[str, Launcher], game_dir: Optional[str], renderer: str = "auto",
                  options: Optional[dict] = None, cpu_threads: Optional[int] = None,
                  gpu_memory_mb: Optional[int] = None) -> Launcher:
    """Build the launcher named by `launcher` ("auto" or "docker", the same for now), or pass an instance
    through."""
    if isinstance(launcher, Launcher):
        return launcher
    if launcher == "windows" or sys.platform == "win32":
        raise NotImplementedError("Running the game on Windows is not implemented yet; use Linux (Docker)")
    options = dict(options or {})
    game_dir = game_dir or os.environ.get("SPELUNKY2RL_GAME_DIR")
    if not game_dir:
        raise ValueError("Where is Spelunky 2? Pass game_dir= (the folder with Spel2.exe) or set SPELUNKY2RL_GAME_DIR")

    if launcher in ("auto", "docker"):
        from .docker import DockerLauncher

        return DockerLauncher(game_dir, renderer=renderer, cpu_threads=cpu_threads, gpu_memory_mb=gpu_memory_mb,
                              **options)
    raise ValueError(f"launcher must be 'auto', 'docker' or a Launcher instance; got {launcher!r}")


__all__ = ["Launcher", "PlaylunkyCache", "make_launcher"]
