import collections
import contextlib
import functools
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import List, Optional

from ...version import __version__
from ..frames import FrameSource
from .base import Launcher, PlaylunkyCache, cache_root, check_game_dir, game_version_hash

DEFAULT_IMAGE = f"ghcr.io/vicbentu/spelunky2rl-game:{__version__}"
RENDERERS = ("auto", "gpu", "cpu")
CAPTURE_FILE = "/capture/frame"  # in the container; the Vulkan layer writes each frame there


@functools.lru_cache(maxsize=None)
def docker_has_nvidia(docker: str = "docker") -> bool:
    """True if Docker can pass an NVIDIA GPU into containers: a working driver plus the
    NVIDIA Container Toolkit (its CLI for --gpus, or a registered nvidia runtime)."""
    if shutil.which("nvidia-smi") is None:
        return False
    try:
        if subprocess.run(["nvidia-smi", "-L"], capture_output=True, timeout=10).returncode != 0:
            return False
        if shutil.which("nvidia-container-cli") is not None:
            return True
        runtimes = subprocess.run([docker, "info", "--format", "{{json .Runtimes}}"],
                                  capture_output=True, text=True, timeout=20)
        return runtimes.returncode == 0 and "nvidia" in json.loads(runtimes.stdout or "{}")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return False


_checked_images = set()


def ensure_image(image: str, docker: str = "docker") -> None:
    if image in _checked_images:
        return
    if shutil.which(docker) is None:
        raise FileNotFoundError("Docker is not installed or not on PATH; it is needed to run the game on Linux "
                                "(or use launcher='wine').")
    result = subprocess.run([docker, "image", "inspect", image], capture_output=True, text=True)
    if result.returncode != 0:
        if "permission denied" in result.stderr.lower() or "cannot connect" in result.stderr.lower():
            raise PermissionError(f"Cannot talk to the Docker daemon: {result.stderr.strip()}")
        raise FileNotFoundError(
            f"Docker image {image} not found. Run `spelunky2rl pull`, or build it from the repo root with "
            f"`docker build -f docker/Dockerfile -t {image} .`")
    _checked_images.add(image)


class DockerLauncher(Launcher):
    """Runs each game instance in its own throwaway container (docker run --rm).

    Host networking lets the Lua mod reach Python on 127.0.0.1 with the plain protocol. The game folder
    is mounted read-only; the container assembles a writable instance directory over it.
    """

    def __init__(self, game_dir, image: Optional[str] = None, renderer: str = "auto",
                 dev_mod: Optional[str] = None, cache_dir: Optional[str] = None,
                 docker: str = "docker", extra_args: Optional[List[str]] = None):
        if renderer not in RENDERERS:
            raise ValueError(f"renderer must be one of {RENDERERS}, got {renderer!r}")
        self.game_dir = check_game_dir(game_dir)
        self.image = image or os.environ.get("SPELUNKY2RL_IMAGE") or DEFAULT_IMAGE
        self.renderer = renderer
        dev_mod = dev_mod or os.environ.get("SPELUNKY2RL_DEV_MOD")
        self.dev_mod = Path(dev_mod).expanduser().resolve() if dev_mod else None
        if self.dev_mod is not None and not (self.dev_mod / "main.lua").is_file():
            raise FileNotFoundError(f"SPELUNKY2RL_DEV_MOD must point to a lua/ folder with main.lua: {self.dev_mod}")
        self.docker = docker
        self.extra_args = list(extra_args or [])
        if cache_dir is None:
            image_key = re.sub(r"[^A-Za-z0-9_.-]", "_", self.image)
            cache_dir = cache_root() / "playlunky" / image_key / game_version_hash(self.game_dir)
        self.cache = PlaylunkyCache(cache_dir)
        self.use_gpu = self._resolve_gpu()
        self.container = None
        self.display = None
        self.capture_dir = None
        self._starts = 0
        self._process = None
        self._output = collections.deque(maxlen=50)

    def _resolve_gpu(self) -> bool:
        if self.renderer == "cpu":
            return False
        has_gpu = docker_has_nvidia(self.docker)
        if self.renderer == "gpu" and not has_gpu:
            raise RuntimeError("renderer='gpu' but Docker cannot use an NVIDIA GPU here "
                               "(needs nvidia-smi and the NVIDIA Container Toolkit). Use renderer='cpu' or 'auto'.")
        return has_gpu

    def command(self, port: int, name: Optional[str] = None) -> List[str]:
        cmd = [self.docker, "run", "--rm", "--name", name or f"spelunky2rl-{port}", "--network", "host",
               # X display numbers must be unique host-wide; the port already is
               "-e", f"PORT={port}", "-e", f"DISPLAYNUM={port}",
               "-e", f"RENDERER={'cpu' if self.renderer == 'cpu' else 'auto'}",
               "-e", "SCREEN={}x{}".format(*self.screen),
               "-v", f"{self.game_dir}:/game:ro",
               "-v", f"{self.cache.path}:/cache"]
        if self.use_gpu:
            cmd += ["--gpus", "all", "-e", "NVIDIA_DRIVER_CAPABILITIES=all"]
        if self.dev_mod is not None:
            cmd += ["-v", f"{self.dev_mod}:/opt/mod/lua:ro"]
        if self.capture_dir is not None:
            cmd += ["-v", f"{self.capture_dir}:{os.path.dirname(CAPTURE_FILE)}",
                    "-e", "SPELUNKY2RL_CAPTURE_LAYER=1", "-e", f"SPELUNKY2RL_CAPTURE={CAPTURE_FILE}",
                    "-e", f"SPELUNKY2RL_CAPTURE_SLOTS={self.capture_frames}"]
        return cmd + self.extra_args + [self.image]

    def starting(self, timeout: float):
        return self.cache.building(timeout)

    def start(self, port: int) -> None:
        ensure_image(self.image, self.docker)
        self._starts += 1
        # a relaunch must not collide with the previous container while Docker is still removing it
        self.container = f"spelunky2rl-{port}" + (f"-{self._starts}" if self._starts > 1 else "")
        self.display = f":{port}"
        self._output.clear()
        if self.capture:
            # in memory (/dev/shm) where there is one: the layer writes a whole frame per present
            self.capture_dir = tempfile.mkdtemp(prefix="spelunky2rl-capture-",
                                                dir="/dev/shm" if os.path.isdir("/dev/shm") else None)
        self._process = subprocess.Popen(self.command(port, self.container), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         stdin=subprocess.DEVNULL, text=True, errors="replace")
        threading.Thread(target=self._drain, args=(self._process,), daemon=True).start()

    def _drain(self, process) -> None:
        for line in process.stdout:
            self._output.append(line.rstrip())

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def stop(self) -> None:
        if self._process is not None:
            with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                subprocess.run([self.docker, "kill", self.container], capture_output=True, timeout=30)
            with contextlib.suppress(subprocess.TimeoutExpired):
                self._process.wait(timeout=30)
            self._process = None
        if self.capture_dir is not None:
            shutil.rmtree(self.capture_dir, ignore_errors=True)
            self.capture_dir = None

    def frame_source(self, timeout: float) -> FrameSource:
        from ..frames.vulkan import VulkanFrameSource

        return VulkanFrameSource(os.path.join(self.capture_dir, os.path.basename(CAPTURE_FILE)), timeout)

    def diagnostics(self) -> str:
        return "\n".join(self._output)

