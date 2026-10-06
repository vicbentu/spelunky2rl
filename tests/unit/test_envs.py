import importlib

import numpy as np
import pytest

from fake_lua import make_gamestate

ENV_MODULES = ["default_environment", "dummy_environment", "get_to_exit", "gold_grabber",
               "enemy_killer", "template_environment"]


def env_class(name):
    return importlib.import_module(f"spelunky2rl.envs.{name}").SpelunkyEnv


@pytest.mark.parametrize("name", ENV_MODULES)
def test_observations_match_space(make_env, name):
    env = make_env(env_class(name))
    obs, info = env.reset(seed=1)
    assert env.observation_space.contains(obs)
    for _ in range(20):
        obs, reward, terminated, truncated, info = env.step(env.action_space.sample())
        assert env.observation_space.contains(obs), {k: v for k, v in obs.items()}
        assert isinstance(reward, float)
        assert isinstance(terminated, bool) and isinstance(truncated, bool)


@pytest.mark.parametrize("name", ENV_MODULES)
def test_time_limit_truncates_without_terminating(make_env, name):
    rng = np.random.default_rng(0)

    def respond(message, steps):
        return make_gamestate(rng, time=60 if message["command"] == "reset" else 60 * 90)

    env = make_env(env_class(name), respond)
    env.reset(seed=0)
    _, _, terminated, truncated, _ = env.step(env.action_space.sample())
    assert truncated is True
    assert terminated is False


@pytest.mark.parametrize("name", ENV_MODULES)
def test_death_terminates(make_env, name):
    rng = np.random.default_rng(0)

    def respond(message, steps):
        return make_gamestate(rng, health=4 if message["command"] == "reset" else 0)

    env = make_env(env_class(name), respond)
    env.reset(seed=0)
    _, _, terminated, truncated, _ = env.step(env.action_space.sample())
    assert terminated is True
    assert truncated is False


def test_enemy_killer_rewards_kills_positively(make_env):
    rng = np.random.default_rng(0)

    def respond(message, steps):
        return make_gamestate(rng, dead_enemies=steps)

    env = make_env(env_class("enemy_killer"), respond)
    env.reset(seed=0)
    _, reward, _, _, _ = env.step(env.action_space.sample())
    assert reward == pytest.approx(0.5)


@pytest.mark.parametrize("dist_to_goal, success", [(0, True), (1, False)])
def test_get_to_exit_terminates_in_the_exit_cell_only(make_env, dist_to_goal, success):
    """1 is the next cell, where the game does not let the player in: it used to count as success."""
    rng = np.random.default_rng(0)

    def respond(message, steps):
        return make_gamestate(rng, dist_to_goal=10 if steps == 0 else dist_to_goal)

    env = make_env(env_class("get_to_exit"), respond)
    env.reset(seed=0)
    _, reward, terminated, truncated, info = env.step(env.action_space.sample())
    assert terminated is success and truncated is False
    assert info["success"] is success
    if success:
        assert reward > 0


@pytest.mark.parametrize("frames_per_step", [3, 6, 12])
def test_get_to_exit_truncation_penalty_scales_with_frames_per_step(make_env, frames_per_step):
    """Truncating at step k of an episode of N steps costs 0.01 per remaining step."""
    rng = np.random.default_rng(0)
    steps_done = 100
    time = 60 + steps_done * frames_per_step

    def respond(message, steps):
        # no progress at all: after 200 steps the env truncates
        return make_gamestate(rng, time=time, dist_to_goal=10)

    env = make_env(env_class("get_to_exit"), respond, frames_per_step=frames_per_step)
    env.reset(seed=0)
    for _ in range(201):
        _, reward, _, truncated, _ = env.step(env.action_space.sample())
        if truncated:
            break
    assert truncated
    max_steps = 60 * 90 / frames_per_step
    expected = -0.01 - 5 - 0.01 * (max_steps - time / frames_per_step)
    assert reward == pytest.approx(expected)
