"""
Evaluate Pretrained Model Example

This script demonstrates how to load and evaluate a pretrained RL agent.

Usage:
1. Train a model using train_get_to_exit.py (or use a pretrained model)
2. Update MODEL_PATH below to point to your saved model
3. Run this script to watch the agent play

The script will:
- Load the specified model
- Run N evaluation episodes
- Track success rate, average time, and FPS
- Print statistics at the end

Requirements:
- stable-baselines3
- sb3-contrib (if using RecurrentPPO)
- A trained model file (.zip)
"""

from sb3_contrib import RecurrentPPO
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import SubprocVecEnv
from stable_baselines3.common.monitor import Monitor

import numpy as np
from datetime import datetime

from spelunky2rl.envs.get_to_exit import SpelunkyEnv


##################### CONFIGURATION #####################

# IMPORTANT: Update this path to your trained model
MODEL_PATH = "./models_get_to_exit/final_model.zip"

# Evaluation settings
NUM_EPISODES = 50      # Number of episodes to evaluate
NUM_ENVS = 4           # Number of parallel environments
USE_LSTM = True        # Set to True if model uses RecurrentPPO, False for PPO
DETERMINISTIC = True   # Use deterministic actions (no exploration)


##################### ENVIRONMENT CREATION #####################

def make_env(index: int):
    """Create a single Spelunky environment for evaluation"""
    def _init():
        env = SpelunkyEnv(
            # The game folder comes from SPELUNKY2RL_GAME_DIR (or pass game_dir="...")

            frames_per_step=6,
            manual_control=False,
            god_mode=False,
            render_enabled=False  # Set to True to enable video recording
        )
        return Monitor(env)
    return _init


##################### EVALUATION #####################

if __name__ == "__main__":

    print("=" * 70)
    print("SpelunkyRL - Model Evaluation")
    print("=" * 70)
    print(f"Model: {MODEL_PATH}")
    print(f"Episodes: {NUM_EPISODES}")
    print(f"Parallel envs: {NUM_ENVS}")
    print(f"LSTM: {USE_LSTM}")
    print(f"Deterministic: {DETERMINISTIC}")
    print("=" * 70)
    print()

    # -------- Create Environments --------------------------------------------
    print("Creating environments...")
    env = SubprocVecEnv([make_env(i) for i in range(NUM_ENVS)])
    print(f"✓ {NUM_ENVS} environments created")
    print()

    # -------- Load Model -----------------------------------------------------
    print(f"Loading model from {MODEL_PATH}...")
    try:
        if USE_LSTM:
            model = RecurrentPPO.load(MODEL_PATH, env=env)
        else:
            model = PPO.load(MODEL_PATH, env=env)
        print("✓ Model loaded successfully")
    except FileNotFoundError:
        print(f"✗ Error: Model file not found at {MODEL_PATH}")
        print("Please update MODEL_PATH to point to your trained model.")
        env.close()
        exit(1)
    except Exception as e:
        print(f"✗ Error loading model: {e}")
        env.close()
        exit(1)
    print()

    # -------- Run Evaluation -------------------------------------------------
    print(f"Starting evaluation ({NUM_EPISODES} episodes)...")
    print()

    # Initialize LSTM states if using RecurrentPPO
    lstm_states = None
    episode_starts = np.ones((NUM_ENVS,), dtype=bool)

    # Reset environments
    obs = env.reset()

    # Track statistics
    episode_count = np.zeros(NUM_ENVS, dtype=int)
    successes = []
    episode_times = []
    episode_rewards = []

    # Timing
    start_time = datetime.now()
    step_count = 0

    while np.min(episode_count) < NUM_EPISODES:
        step_count += NUM_ENVS

        # Get action from model
        if USE_LSTM:
            actions, lstm_states = model.predict(
                obs,
                state=lstm_states,
                episode_start=episode_starts,
                deterministic=DETERMINISTIC
            )
        else:
            actions, _ = model.predict(obs, deterministic=DETERMINISTIC)

        # Step environments
        obs, rewards, dones, infos = env.step(actions)

        # Update episode starts for LSTM
        episode_starts = dones

        # Process episode completions
        for env_idx, (done, info) in enumerate(zip(dones, infos)):
            if done:
                episode_count[env_idx] += 1

                # Extract episode statistics from Monitor wrapper
                if "episode" in info:
                    episode_rewards.append(info["episode"]["r"])

                    # Extract success and time if available
                    success = info.get("success", False)
                    successes.append(success)

                    if success:
                        episode_time = info.get("time", 0)
                        episode_times.append(episode_time)

                    # Print progress
                    total_episodes = np.sum(episode_count)
                    success_symbol = "✓" if success else "✗"
                    print(f"Episode {total_episodes}/{NUM_EPISODES * NUM_ENVS} - "
                          f"Env {env_idx} - {success_symbol} "
                          f"{'SUCCESS' if success else 'FAILED'}")

    # -------- Calculate Statistics -------------------------------------------
    elapsed_time = (datetime.now() - start_time).total_seconds()
    fps = step_count / elapsed_time

    success_rate = 100 * np.mean(successes) if successes else 0
    avg_reward = np.mean(episode_rewards) if episode_rewards else 0
    avg_time = np.mean(episode_times) if episode_times else 0

    # -------- Print Results --------------------------------------------------
    print()
    print("=" * 70)
    print("EVALUATION RESULTS")
    print("=" * 70)
    print(f"Total episodes: {len(successes)}")
    print(f"Success rate: {success_rate:.2f}%")
    print(f"Successes: {sum(successes)}/{len(successes)}")
    print()
    print(f"Average reward: {avg_reward:.2f}")
    if episode_times:
        print(f"Average time (successful episodes): {avg_time:.1f} frames ({avg_time/60:.1f} seconds)")
    print()
    print(f"Evaluation time: {elapsed_time:.1f} seconds")
    print(f"Average FPS: {fps:.1f}")
    print("=" * 70)

    # -------- Cleanup --------------------------------------------------------
    env.close()
    print("\nEvaluation complete!")
