import re
import socket
import threading
import time
from importlib.resources import files

import pytest
from conftest import FakeLauncher

import spelunky2rl.engine.core as core
from spelunky2rl.engine.launchers import make_launcher
from spelunky2rl.engine.protocol import PROTOCOL_VERSION, ProtocolError
from spelunky2rl.envs.dummy_environment import SpelunkyEnv
from spelunky2rl.version import __version__


def test_mod_and_package_versions_agree():
    lua = (files("spelunky2rl") / "mod" / "lua" / "spelunky2rl" / "protocol.lua").read_text()
    assert re.search(r"local PROTOCOL_VERSION = (\d+)", lua).group(1) == str(PROTOCOL_VERSION)
    assert re.search(r'local MOD_VERSION = "([^"]+)"', lua).group(1) == __version__


def test_protocol_mismatch_is_explained():
    launcher = FakeLauncher(hello={"hello": {"protocol": PROTOCOL_VERSION + 1, "mod": "9.9.9"}})
    with pytest.raises(ProtocolError, match=r"mod 9\.9\.9.*needs protocol"):
        SpelunkyEnv(launcher=launcher)
    assert launcher.stops == 1


def test_mod_without_hello_is_rejected(monkeypatch):
    monkeypatch.setattr(core, "HELLO_TIMEOUT", 0.3)
    launcher = FakeLauncher(hello=None)
    with pytest.raises(TimeoutError):
        SpelunkyEnv(launcher=launcher)
    assert launcher.stops == 1


def test_relaunches_when_the_game_dies_early(make_env):
    launcher = FakeLauncher(fail_starts=2)
    env = make_env(SpelunkyEnv, launcher=launcher, max_launch_attempts=3)
    env.reset(seed=0)
    assert (launcher.starts, launcher.stops) == (3, 2)


def test_gives_up_after_max_attempts_with_diagnostics():
    launcher = FakeLauncher(fail_starts=5)
    with pytest.raises(RuntimeError, match="exited 2 times(.|\n)*fake launcher output"):
        SpelunkyEnv(launcher=launcher, max_launch_attempts=2)
    assert launcher.starts == 2


def test_startup_timeout():
    launcher = FakeLauncher(connect=False)
    start = time.monotonic()
    with pytest.raises(TimeoutError, match="did not connect"):
        SpelunkyEnv(launcher=launcher, startup_timeout=0.3)
    assert time.monotonic() - start < 3
    assert launcher.stops == 1


def test_reset_restarts_a_game_that_does_not_answer(make_env):
    from fake_lua import make_gamestate
    import numpy as np

    rng = np.random.default_rng(0)
    launcher = FakeLauncher()
    # the first game never answers its reset; the second one does
    launcher.respond = lambda message, steps: None if launcher.starts == 1 else make_gamestate(rng)
    env = make_env(SpelunkyEnv, launcher=launcher, step_timeout=0.3)
    with pytest.warns(RuntimeWarning, match="stopped answering(.|\n)*fake launcher output"):
        env.reset(seed=7)
    assert (launcher.starts, launcher.stops) == (2, 1)
    assert [m["seed"] for m in launcher.lua.messages if m["command"] == "reset"] == [7]
    env.step(env.action_space.sample())


def test_reset_restarts_a_game_that_died_in_a_step(make_env):
    launcher = FakeLauncher()
    env = make_env(SpelunkyEnv, launcher=launcher)
    env.reset(seed=0)
    launcher.lua.sock.shutdown(socket.SHUT_RDWR)  # the game is gone
    with pytest.raises((ConnectionError, TimeoutError)):
        env.step(env.action_space.sample())
    with pytest.warns(RuntimeWarning, match="starting it again"):
        env.reset(seed=1)
    assert launcher.starts == 2
    env.step(env.action_space.sample())


def test_reset_gives_up_after_max_attempts(make_env):
    launcher = FakeLauncher(respond=lambda message, steps: None)
    env = make_env(SpelunkyEnv, launcher=launcher, step_timeout=0.2, max_launch_attempts=2)
    with pytest.warns(RuntimeWarning), pytest.raises(TimeoutError):
        env.reset(seed=0)
    assert launcher.starts == 2


def test_close_stops_the_launcher(make_env):
    launcher = FakeLauncher()
    env = make_env(SpelunkyEnv, launcher=launcher)
    env.close()
    assert launcher.stops == 1


def test_game_dir_is_required(monkeypatch):
    monkeypatch.delenv("SPELUNKY2RL_GAME_DIR", raising=False)
    with pytest.raises(ValueError, match="SPELUNKY2RL_GAME_DIR"):
        make_launcher("docker", None)


def test_unknown_launcher(tmp_path):
    with pytest.raises(ValueError, match="launcher must be"):
        make_launcher("steam", str(tmp_path))


@pytest.mark.skipif(not hasattr(__import__("os"), "fork"), reason="flock-based cache lock is Linux only")
def test_cache_lock_serialises_only_the_first_build(tmp_path):
    from spelunky2rl.engine.launchers.base import PlaylunkyCache

    events = []

    def instance(name, work):
        with PlaylunkyCache(tmp_path / "cache").building(timeout=5):
            events.append((name, "in", time.monotonic()))
            time.sleep(work)
            events.append((name, "out", time.monotonic()))

    first = threading.Thread(target=instance, args=("first", 0.3))
    first.start()
    time.sleep(0.05)
    waiters = [threading.Thread(target=instance, args=(f"w{i}", 0.3)) for i in range(2)]
    for w in waiters:
        w.start()
    for t in [first, *waiters]:
        t.join()

    times = {(name, what): t for name, what, t in events}
    assert times[("w0", "in")] >= times[("first", "out")]
    assert times[("w1", "in")] >= times[("first", "out")]
    # once the cache is built, waiters do not queue behind each other
    assert times[("w1", "in")] < times[("w0", "out")] and times[("w0", "in")] < times[("w1", "out")]
    assert PlaylunkyCache(tmp_path / "cache").ready


@pytest.mark.skipif(not hasattr(__import__("os"), "fork"), reason="flock-based cache lock is Linux only")
def test_failed_first_build_does_not_mark_the_cache_ready(tmp_path):
    from spelunky2rl.engine.launchers.base import PlaylunkyCache

    cache = PlaylunkyCache(tmp_path / "cache")
    with pytest.raises(RuntimeError), cache.building(timeout=5):
        raise RuntimeError("game crashed")
    assert not cache.ready


def test_windows_is_not_implemented(tmp_path):
    with pytest.raises(NotImplementedError, match="Windows"):
        make_launcher("windows", str(tmp_path))
