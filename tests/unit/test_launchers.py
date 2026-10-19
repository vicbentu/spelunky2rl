import os

import pytest

import spelunky2rl.engine.launchers.docker as docker_launcher
from spelunky2rl.engine.launchers.docker import DockerLauncher


@pytest.fixture
def game_dir(tmp_path):
    game = tmp_path / "Spelunky 2"
    game.mkdir()
    (game / "Spel2.exe").write_text("Spel2.exe")
    return game


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
    assert "SCREEN=640x360" in joined
    launcher.screen = (320, 180)
    assert "SCREEN=320x180" in " ".join(launcher.command(4242))
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


def test_cpu_threads_reach_lavapipe(game_dir, tmp_path, monkeypatch):
    from spelunky2rl.engine.launchers import make_launcher

    monkeypatch.setattr(docker_launcher, "docker_has_nvidia", lambda docker="docker": False)
    default = DockerLauncher(game_dir, cache_dir=tmp_path / "c", renderer="cpu").command(1)
    assert not any(arg.startswith("LP_NUM_THREADS") for arg in default)
    cpu = make_launcher("docker", str(game_dir), renderer="cpu", cpu_threads=4,
                        options={"cache_dir": tmp_path / "c"}).command(1)
    assert cpu[cpu.index("LP_NUM_THREADS=4") - 1] == "-e"
    # "auto" without a GPU draws on the CPU too
    assert "LP_NUM_THREADS=2" in DockerLauncher(game_dir, cache_dir=tmp_path / "c", cpu_threads=2).command(1)
    monkeypatch.setattr(docker_launcher, "docker_has_nvidia", lambda docker="docker": True)
    gpu = DockerLauncher(game_dir, cache_dir=tmp_path / "c", cpu_threads=4).command(1)
    assert not any(arg.startswith("LP_NUM_THREADS") for arg in gpu)


@pytest.mark.parametrize("bad", [0, -1, 2.5, "4", True])
def test_cpu_threads_must_be_a_positive_int(game_dir, tmp_path, no_gpu, bad):
    with pytest.raises(ValueError, match="cpu_threads"):
        DockerLauncher(game_dir, cache_dir=tmp_path / "c", cpu_threads=bad)


def test_gpu_memory_caps_dxvk(game_dir, tmp_path, monkeypatch):
    from spelunky2rl.engine.launchers import make_launcher

    monkeypatch.setattr(docker_launcher, "docker_has_nvidia", lambda docker="docker": True)
    capped = make_launcher("docker", str(game_dir), gpu_memory_mb=512, options={"cache_dir": tmp_path / "c"}).command(1)
    assert capped[capped.index("DXVK_CONFIG=dxvk.maxMemoryBudget=512") - 1] == "-e"
    uncapped = DockerLauncher(game_dir, cache_dir=tmp_path / "c").command(1)
    assert not any(arg.startswith("DXVK_CONFIG") for arg in uncapped)
    # on the CPU there is no VRAM to cap
    cpu = DockerLauncher(game_dir, cache_dir=tmp_path / "c", renderer="cpu", gpu_memory_mb=512).command(1)
    assert not any(arg.startswith("DXVK_CONFIG") for arg in cpu)


@pytest.mark.parametrize("bad", [0, -1, 2.5, "512", True])
def test_gpu_memory_must_be_a_positive_int(game_dir, tmp_path, no_gpu, bad):
    with pytest.raises(ValueError, match="gpu_memory_mb"):
        DockerLauncher(game_dir, cache_dir=tmp_path / "c", gpu_memory_mb=bad)


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


def test_docker_capture(game_dir, tmp_path, no_gpu, monkeypatch):
    """With render the Vulkan layer gets a file of its own per instance, gone on stop()."""
    launcher = DockerLauncher(game_dir, cache_dir=tmp_path / "c")
    assert "SPELUNKY2RL_CAPTURE_LAYER=1" not in launcher.command(1)
    monkeypatch.setattr(docker_launcher, "ensure_image", lambda image, docker: None)
    launcher.docker = "true"  # start() runs `true run ...` instead of a container
    launcher.capture = True
    launcher.capture_frames = 6
    launcher.start(1)
    capture_dir = launcher.capture_dir
    cmd = launcher.command(1)
    assert f"{capture_dir}:/capture" in cmd
    assert "SPELUNKY2RL_CAPTURE_LAYER=1" in cmd and "SPELUNKY2RL_CAPTURE=/capture/frame" in cmd
    assert "SPELUNKY2RL_CAPTURE_SLOTS=6" in cmd
    assert launcher.frame_source(timeout=1).path == f"{capture_dir}/frame"
    launcher.stop()
    assert not os.path.exists(capture_dir) and launcher.capture_dir is None
