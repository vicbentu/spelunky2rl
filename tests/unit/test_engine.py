from importlib.resources import files

import numpy as np
import pytest

import spelunky2rl
from spelunky2rl.engine.core import STATE_UPDATES
from spelunky2rl.envs.default_environment import SpelunkyEnv as DefaultEnv
from spelunky2rl.envs.get_to_exit import SpelunkyEnv as GetToExit


def sent_seeds(env):
    return [m["seed"] for m in env.fake_lua.messages if m["command"] == "reset"]


def test_seeds_are_reproducible(make_env):
    a, b = make_env(DefaultEnv), make_env(DefaultEnv)
    for env in (a, b):
        env.reset(seed=123)
        env.reset()
        env.reset()
    assert sent_seeds(a)[0] == 123
    assert sent_seeds(a) == sent_seeds(b)
    assert len(set(sent_seeds(a))) == 3


def test_unseeded_resets_differ_between_envs(make_env):
    a, b = make_env(DefaultEnv), make_env(DefaultEnv)
    a.reset()
    b.reset()
    assert sent_seeds(a) != sent_seeds(b)


def test_reset_options_reach_lua(make_env):
    env = make_env(DefaultEnv, hp=8)
    env.reset(seed=0, world=3, theme=4)
    message = env.fake_lua.messages[-1]
    assert (message["hp"], message["world"], message["theme"]) == (8, 3, 4)
    env.reset(seed=0)
    assert "theme" not in env.fake_lua.messages[-1]


def test_headless_defaults_reach_lua(make_env):
    env = make_env(DefaultEnv)
    env.reset(seed=0)
    message = env.fake_lua.messages[-1]
    assert message["render"] is False and message["vsync"] is False and message["audio"] is False
    assert message["time_ghost"] is True
    env.reset(seed=0, time_ghost=False)
    assert env.fake_lua.messages[-1]["time_ghost"] is False


@pytest.mark.parametrize("kwargs, state_updates, speedup", [
    ({}, STATE_UPDATES, True),
    ({"render_enabled": True}, 0, True),  # the mod runs the logic-only frames of each step itself
    ({"speedup": False}, 0, False),
])
def test_the_engine_picks_state_updates(make_env, kwargs, state_updates, speedup):
    env = make_env(DefaultEnv, **kwargs)
    env.reset(seed=0)
    message = env.fake_lua.messages[-1]
    assert (message["state_updates"], message["speedup"]) == (state_updates, speedup)


def test_state_updates_is_gone(make_env):
    with pytest.raises(TypeError, match="state_updates was removed"):
        make_env(DefaultEnv, state_updates=200)
    env = make_env(DefaultEnv)
    with pytest.raises(TypeError, match="state_updates was removed"):
        env.reset(seed=0, state_updates=200)
    with pytest.raises(TypeError, match="state_updates was removed"):
        env.reset(seed=0, options={"state_updates": 200})
    assert not env.fake_lua.messages


def test_unknown_reset_option_is_rejected(make_env):
    """`bomb=3` (for `bombs`) used to be dropped in silence."""
    with pytest.raises(TypeError, match="bomb"):
        make_env(DefaultEnv, bomb=3)
    env = make_env(DefaultEnv)
    with pytest.raises(TypeError, match="bomb"):
        env.reset(seed=0, bomb=3)
    with pytest.raises(TypeError, match="bomb"):
        env.reset(seed=0, options={"bomb": 3})
    assert not env.fake_lua.messages


def test_screen_follows_render_resolution(make_env):
    assert make_env(DefaultEnv, render_enabled=True).launcher.screen == (640, 360)
    assert make_env(DefaultEnv, render_enabled=True, render_resolution=(1280, 720)).launcher.screen == (1280, 720)
    # nobody reads the frames: a small screen is faster
    assert make_env(DefaultEnv, render_resolution=(1280, 720)).launcher.screen == (160, 90)


@pytest.mark.parametrize("resolution", [(400, 400), (32, 18), (640,), "640x360"])
def test_bad_render_resolution_is_rejected(make_env, resolution):
    with pytest.raises(ValueError, match="render_resolution"):
        make_env(DefaultEnv, render_resolution=resolution)


def test_fields_are_sent_on_reset_only(make_env):
    class WideView(GetToExit):
        data_to_send = {"map_info": {"width": 41, "height": 21}, "dist_to_goal": {}}

        def gamestate_to_observation(self, gamestate):
            return {}

    env = make_env(WideView)
    env.reset(seed=0)
    assert env.fake_lua.messages[-1]["fields"] == [{"name": "map_info", "width": 41, "height": 21},
                                                   {"name": "dist_to_goal"}]
    assert env.last_gamestate["map_info"].shape == (21, 41)
    env.step([1, 1, 0])
    assert "fields" not in env.fake_lua.messages[-1] and "data_to_send" not in env.fake_lua.messages[-1]
    assert env.last_gamestate["map_info"].shape == (21, 41)


@pytest.mark.parametrize("action", [[2, 1, 1], (2, 1, 1), np.array([2, 1, 1])])
def test_action_types(make_env, action):
    env = make_env(GetToExit)
    env.reset(seed=0)
    env.step(action)
    assert env.fake_lua.messages[-1]["input"] == [2, 1, 1, 0, 0, 0, 1, 0]


def test_lua_error_is_raised(make_env):
    env = make_env(DefaultEnv, respond=lambda message, steps: {"error": "Invalid world number: 99"})
    with pytest.raises(RuntimeError, match="Invalid world"):
        env.reset(seed=0)


def test_silent_game_times_out(make_env):
    env = make_env(DefaultEnv, respond=lambda message, steps: None, step_timeout=0.2)
    with pytest.raises(TimeoutError):
        env.reset(seed=0)


def test_close_is_idempotent(make_env):
    env = make_env(DefaultEnv)
    env.reset(seed=0)
    env.close()
    env.close()
    env.fake_lua.join(timeout=2)
    commands = [m["command"] for m in env.fake_lua.messages]
    assert commands.count("close") == 1


def test_close_survives_dead_game(make_env):
    env = make_env(DefaultEnv)
    env.reset(seed=0)
    env.fake_lua.sock.close()
    env.close()


def test_package_ships_the_mod_and_entity_names():
    assert (files("spelunky2rl") / "mod" / "lua" / "main.lua").is_file()
    assert (files("spelunky2rl") / "mod" / "lua" / "spelunky2rl" / "session.lua").is_file()
    assert (files("spelunky2rl") / "mod" / "lua" / "luasocket" / "socket_core.dll").is_file()
    assert spelunky2rl.id2name(23)["name"] == "FLOOR_DOOR_EXIT"


@pytest.mark.parametrize("env_id", ["spelunky2rl/GetToExit-v0", "spelunky2rl/Default-v0", "spelunky2rl/Dummy-v0",
                                    "spelunky2rl/GoldGrabber-v0", "spelunky2rl/EnemyKiller-v0"])
def test_registered_envs_pass_gymnasium_checks(env_id):
    import warnings

    import gymnasium as gym
    from conftest import FakeLauncher

    launcher = FakeLauncher()
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # the passive env checker warns on contract violations
        env = gym.make(env_id, launcher=launcher)
        try:
            env.reset(seed=0)
            for _ in range(5):
                env.step(env.action_space.sample())
        finally:
            env.close()
    assert env.unwrapped.render_mode is None


def test_render_mode_enables_capture():
    import gymnasium as gym
    from conftest import FakeLauncher

    env = gym.make("spelunky2rl/Dummy-v0", render_mode="rgb_array", launcher=FakeLauncher())
    try:
        assert env.unwrapped.render_enabled
        assert "render_mode" not in env.unwrapped.reset_options
    finally:
        env.close()
