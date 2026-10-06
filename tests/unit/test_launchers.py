import os
import sys

import pytest

import spelunky2rl.engine.launchers.docker as docker_launcher
from spelunky2rl.engine.assemble import assemble_instance
from spelunky2rl.engine.launchers.docker import DockerLauncher

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="symlink farm is for Linux")


@pytest.fixture
def game_dir(tmp_path):
    game = tmp_path / "Spelunky 2"
    game.mkdir()
    for name in ("Spel2.exe", "fmod.dll", "settings.cfg", "savegame.sav", "spelunky.log", "overlunky.ini",
                 "steam_api64.dll", "local.cfg"):
        (game / name).write_text(name)
    (game / "Data").mkdir()
    (game / "Mods" / "Packs" / "SomeOtherMod").mkdir(parents=True)
    return game


@posix_only
def test_symlink_farm(game_dir, tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "steam_api64.dll").write_text("goldberg")
    out = assemble_instance(game_dir, tmp_path / "inst", assets / "steam_api64.dll", cache=tmp_path / "cache")

    assert os.readlink(out / "Spel2.exe") == str(game_dir / "Spel2.exe")
    assert os.readlink(out / "Data") == str(game_dir / "Data")
    for written in ("settings.cfg", "savegame.sav"):
        assert not (out / written).is_symlink() and (out / written).read_text() == written
    assert not (out / "spelunky.log").exists()
    assert (out / "steam_api64.dll").read_text() == "goldberg"
    assert (out / "steam_appid.txt").read_text().strip() == "418530"
    # our borderless window, not the user's video settings (fullscreen leaves every frame black)
    assert "<window_mode>1</window_mode>" in (out / "local.cfg").read_text()
    packs = out / "Mods" / "Packs"
    assert sorted(p.name for p in packs.iterdir()) == [".db", "load_order.txt", "spelunky2rl"]
    assert (packs / "spelunky2rl" / "lua" / "main.lua").is_file()
    assert (packs / "load_order.txt").read_text() == "spelunky2rl\n"


@pytest.fixture
def no_gpu(monkeypatch):
    monkeypatch.setattr(docker_launcher, "docker_has_nvidia", lambda docker="docker": False)


def test_docker_command(game_dir, tmp_path, no_gpu):
    launcher = DockerLauncher(game_dir, image="img:1", cache_dir=tmp_path / "cache")
    cmd = launcher.command(4242)
    assert cmd[:3] == ["docker", "run", "--rm"]
    assert cmd[-1] == "img:1"
    joined = " ".join(cmd)
    assert "--network host" in joined
    assert "PORT=4242" in joined and "DISPLAYNUM=4242" in joined
    assert f"{game_dir}:/game:ro" in joined
    assert f"{tmp_path / 'cache'}:/cache" in joined
    assert "--gpus" not in cmd


def test_docker_gpu_and_dev_mod(game_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(docker_launcher, "docker_has_nvidia", lambda docker="docker": True)
    dev = tmp_path / "lua"
    dev.mkdir()
    (dev / "main.lua").write_text("")
    cmd = DockerLauncher(game_dir, cache_dir=tmp_path / "c", dev_mod=str(dev)).command(1)
    assert cmd[cmd.index("--gpus") + 1] == "all"
    assert f"{dev}:/opt/mod/lua:ro" in cmd
    cpu = DockerLauncher(game_dir, cache_dir=tmp_path / "c", renderer="cpu").command(1)
    assert "--gpus" not in cpu and "RENDERER=cpu" in cpu


def test_gpu_renderer_needs_a_gpu(game_dir, tmp_path, no_gpu):
    with pytest.raises(RuntimeError, match="renderer='gpu'"):
        DockerLauncher(game_dir, cache_dir=tmp_path / "c", renderer="gpu")


def test_cache_is_per_game_build(game_dir, tmp_path, no_gpu, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    first = DockerLauncher(game_dir, image="img:1").cache.path
    (game_dir / "Spel2.exe").write_text("patched game")
    second = DockerLauncher(game_dir, image="img:1").cache.path
    assert first != second and first.parent == second.parent


def test_missing_game(tmp_path, no_gpu):
    with pytest.raises(FileNotFoundError, match="No Spel2.exe"):
        DockerLauncher(tmp_path)
