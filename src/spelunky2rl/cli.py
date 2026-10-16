"""`spelunky2rl` command: check the setup and fetch the game image."""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .version import __version__

OK, FAIL, INFO = "ok  ", "FAIL", "    "


def _report(status: str, message: str) -> bool:
    print(f"[{status}] {message}")
    return status != FAIL


def _check_game_dir(game_dir) -> bool:
    if not game_dir:
        return _report(FAIL, "game folder: pass --game-dir or set SPELUNKY2RL_GAME_DIR")
    from .engine.launchers.base import game_version_hash

    path = Path(game_dir).expanduser()
    if not (path / "Spel2.exe").is_file():
        return _report(FAIL, f"game folder: no Spel2.exe in {path}")
    return _report(OK, f"game folder: {path} (build {game_version_hash(path.resolve())})")


def _check_docker(image: str) -> bool:
    from .engine.launchers.docker import docker_has_nvidia

    if shutil.which("docker") is None:
        return _report(FAIL, "docker: not installed (https://docs.docker.com/engine/install/)")
    info = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], capture_output=True, text=True)
    if info.returncode != 0:
        return _report(FAIL, f"docker: daemon not reachable ({info.stderr.strip().splitlines()[-1:]}); "
                             "is it running and is your user in the docker group?")
    ok = _report(OK, f"docker: server {info.stdout.strip()}")
    if docker_has_nvidia():
        _report(OK, "gpu: NVIDIA GPU usable from Docker (renderer='auto' will use it)")
    else:
        _report(INFO, "gpu: none usable from Docker, games render on the CPU (lavapipe); install the NVIDIA "
                      "Container Toolkit to use a GPU")
    image_check = subprocess.run(["docker", "image", "inspect", image], capture_output=True)
    if image_check.returncode == 0:
        ok &= _report(OK, f"image: {image}")
    else:
        ok &= _report(FAIL, f"image: {image} not found; run `spelunky2rl pull`")
    return ok


def _check_wine() -> bool:
    from .engine.launchers.wine import default_wine_home, runs_the_games_msvcp140

    home = Path(os.environ.get("SPELUNKY2RL_WINE_HOME") or default_wine_home())
    if shutil.which("wine") is None or shutil.which("Xvfb") is None:
        return _report(FAIL, "wine: needs wine and Xvfb on PATH")
    if not (home / "prefix").is_dir() or not (home / "playlunky" / "playlunky_launcher.exe").is_file():
        return _report(FAIL, f"wine: {home} is not set up; run scripts/setup_wine.sh")
    if not runs_the_games_msvcp140(home / "prefix"):
        return _report(FAIL, f"wine: {home} was set up by an older scripts/setup_wine.sh; run it again")
    return _report(OK, f"wine: {home}")


def doctor(args) -> int:
    from .engine.launchers.docker import DEFAULT_IMAGE

    print(f"spelunky2rl {__version__}, Python {sys.version.split()[0]} on {sys.platform}")
    ok = _check_game_dir(args.game_dir or os.environ.get("SPELUNKY2RL_GAME_DIR"))
    launcher = os.environ.get("SPELUNKY2RL_LAUNCHER") or "docker"
    _report(INFO, f"launcher: {launcher}")
    if launcher == "docker":
        ok &= _check_docker(args.image or os.environ.get("SPELUNKY2RL_IMAGE") or DEFAULT_IMAGE)
    elif launcher == "wine":
        ok &= _check_wine()
    print("Everything looks ready." if ok else "Some checks failed.")
    return 0 if ok else 1


def pull(args) -> int:
    from .engine.launchers.docker import DEFAULT_IMAGE

    image = args.image or os.environ.get("SPELUNKY2RL_IMAGE") or DEFAULT_IMAGE
    return subprocess.run(["docker", "pull", image]).returncode


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="spelunky2rl", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)

    doctor_parser = commands.add_parser("doctor", help="check Docker, GPU, the game image and the game folder")
    doctor_parser.add_argument("--game-dir", help="Spelunky 2 folder (default: $SPELUNKY2RL_GAME_DIR)")
    doctor_parser.add_argument("--image", help="game image to check (default: the one for this version)")
    doctor_parser.set_defaults(func=doctor)

    pull_parser = commands.add_parser("pull", help="download the game image for this version")
    pull_parser.add_argument("--image", help="image to pull (default: the one for this version)")
    pull_parser.set_defaults(func=pull)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
