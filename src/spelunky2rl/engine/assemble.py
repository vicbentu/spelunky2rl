"""Per-instance game directory as a symlink farm over a read-only Spelunky 2 folder.

Same rules as docker/entrypoint.sh (keep both in sync): the game writes a few files next to Spel2.exe,
so every instance needs its own directory, but copying the game would cost ~1 GB per instance.
"""

import os
import shutil
from importlib.resources import files
from pathlib import Path
from typing import Optional

# What we provide ourselves instead of taking it from the user's folder
PROVIDED = {"steam_api64.dll", "steam_appid.txt", "steam_settings", "playlunky.ini", "local.cfg", "Mods"}
# Logs we do not want to carry over (spelunky.log can be huge)
SKIPPED = {"spelunky.log", "full_output.log"}
# Small files the game rewrites: real copies, never links into the user's folder
COPIED = {"settings.cfg", "savegame.sav", "input.cfg"}

STEAM_APP_ID = "418530"


def mod_dir() -> Path:
    """The bundled mod pack (contains lua/)."""
    return Path(str(files("spelunky2rl") / "mod"))


def config_dir() -> Path:
    """playlunky.ini / local.cfg templates."""
    return Path(str(files("spelunky2rl") / "engine" / "launchers" / "config"))


def assemble_instance(game_dir: Path, out_dir: Path, steam_api: Path, mod: Optional[Path] = None, cache: Optional[Path] = None) -> Path:
    """Build out_dir so that out_dir/Spel2.exe runs the game with Goldberg and our mod."""
    game_dir, out_dir = Path(game_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for entry in game_dir.iterdir():
        if entry.name in PROVIDED or entry.name in SKIPPED:
            continue
        if entry.name in COPIED:
            shutil.copy2(entry, out_dir / entry.name)
        else:
            os.symlink(entry, out_dir / entry.name)

    os.symlink(steam_api, out_dir / "steam_api64.dll")
    (out_dir / "steam_appid.txt").write_text(STEAM_APP_ID + "\n")
    (out_dir / "steam_settings").mkdir()
    (out_dir / "steam_settings" / "steam_appid.txt").write_text(STEAM_APP_ID + "\n")
    # local.cfg: a borderless window sized to the Xvfb screen, see docker/entrypoint.sh
    for name in ("playlunky.ini", "local.cfg"):
        shutil.copy(config_dir() / name, out_dir / name)

    packs = out_dir / "Mods" / "Packs"
    packs.mkdir(parents=True)
    os.symlink(mod or mod_dir(), packs / "spelunky2rl")
    (packs / "load_order.txt").write_text("spelunky2rl\n")
    if cache is not None:
        os.symlink(cache, packs / ".db")
    return out_dir
