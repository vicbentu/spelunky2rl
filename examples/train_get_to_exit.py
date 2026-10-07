"""
Train Get-to-Exit Example

This script demonstrates how to train an RL agent to navigate to the level exit in Spelunky 2.

Architecture:
- RecurrentPPO with LSTM (handles partial observability)
- Custom feature extractor with tile embeddings and CNN
- 6 parallel environments for faster training
- Custom callbacks for logging success rate

Training details:
- Total timesteps: ~3.7M (300 loops * 2048 steps * 6 envs)
- Expected training time: 2-4 hours on GPU
- Checkpoints saved every 10,240 steps

Requirements:
- stable-baselines3
- sb3-contrib (for RecurrentPPO)
- torch (CUDA recommended)
"""

from sb3_contrib import RecurrentPPO
from stable_baselines3.common.callbacks import CheckpointCallback, BaseCallback
from stable_baselines3.common.vec_env import SubprocVecEnv
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.torch_layers import BaseFeaturesExtractor

import torch
import torch.nn as nn
import gymnasium as gym
from typing import Dict
import numpy as np

from spelunky2rl.envs.get_to_exit import SpelunkyEnv


##################### CUSTOM CALLBACK #####################

class SuccessRateCallback(BaseCallback):
    """
    Custom callback for logging success rate and episode length.
    Tracks episodes where the agent successfully reaches the exit.
    """

    def __init__(self, verbose=0):
        super().__init__(verbose)
        self.episode_successes = []
        self.successes_length = []

    def _on_step(self) -> bool:
        # Check each environment's info dict
        infos = self.locals.get("infos", [])
        for info in infos:
            if "episode" in info:
                # Record success (True if agent reached exit)
                success = info.get("success", False)
                self.episode_successes.append(success)

                # Record episode length (time) for successful episodes
                if success:
                    self.successes_length.append(info.get("time", 0))

        return True

    def _on_rollout_end(self) -> None:
        """Log metrics at the end of each rollout"""
        if self.episode_successes:
            # Success rate over last 100 episodes
            recent_success_rate = 100 * np.mean(self.episode_successes[-100:])
            self.logger.record("custom/success_rate", recent_success_rate)

            if self.verbose:
                print(f"Success rate (last 100 episodes): {recent_success_rate:.2f}%")

        if self.successes_length:
            # Average time to complete successful episodes
            recent_success_length = np.mean(self.successes_length[-100:])
            self.logger.record("custom/avg_success_time", recent_success_length)

            if self.verbose:
                print(f"Avg success time (last 100): {recent_success_length:.1f} frames")


##################### FEATURES EXTRACTOR #####################

class SpelunkyFeaturesExtractor(BaseFeaturesExtractor):
    """
    Custom neural network for extracting features from Spelunky observations.

    Architecture:
    - CNN for spatial feature extraction from multi-hot encoded map
    - MLP for combining map features with player state

    Input:
        - map_info: (C, H, W) multi-hot encoded map (5 channels: empty, stairs, exit, platform, ground)
        - char_state: player animation state, one-hot (B, 23) after SB3's preprocessing
        - can_jump: one-hot (B, 2) after SB3's preprocessing

    Output:
        - features_dim dimensional feature vector
    """

    def __init__(self, observation_space: gym.spaces.Dict, features_dim: int = 128):
        super().__init__(observation_space, features_dim)

        # -------- Map CNN -------------------------------------------------------
        map_space = observation_space["map_info"]  # Box(shape=(C, H, W))
        self.n_channels = map_space.shape[0]  # 5 channels (empty, stairs, exit, platform, ground)
        self.H, self.W = map_space.shape[-2:]

        # CNN for processing multi-hot encoded map
        self.map_cnn = nn.Sequential(
            nn.Conv2d(self.n_channels, 64, kernel_size=3, padding="same"),
            nn.ReLU(),
            nn.Conv2d(64, 64, kernel_size=3, padding="same"),
            nn.ReLU(),
            nn.MaxPool2d(2, 2),
            nn.Conv2d(64, 128, kernel_size=3, padding="same"),
            nn.ReLU(),
            nn.Conv2d(128, 128, kernel_size=3, padding="same"),
            nn.ReLU(),
            nn.MaxPool2d(2, 2),
            nn.Flatten(),
        )

        # Calculate flattened map feature size
        with torch.no_grad():
            dummy = torch.zeros(1, self.n_channels, self.H, self.W)
            map_flatten = self.map_cnn(dummy).shape[1]

        # -------- Player Features -----------------------------------------------
        # SB3 already one-hot encodes Discrete observations before the extractor:
        # char_state arrives as (B, 23) and can_jump as (B, 2)
        extra_flatten = observation_space["char_state"].n + observation_space["can_jump"].n

        # -------- Final Projection ----------------------------------------------
        self.linear = nn.Linear(map_flatten + extra_flatten, features_dim)

    def forward(self, observations: Dict[str, torch.Tensor]) -> torch.Tensor:
        # ---- Process Map -------------------------------------------------------
        # (B, C, H, W) multi-hot encoded map -> CNN features
        map_input = observations["map_info"].float()
        map_features = self.map_cnn(map_input)

        # ---- Process Player State ----------------------------------------------
        # Already one-hot (see __init__); rollouts give (B, n) and training batches (B, 1, n)
        batch = map_features.shape[0]
        extra_feats = torch.cat([observations["char_state"].float().reshape(batch, -1),
                                 observations["can_jump"].float().reshape(batch, -1)], dim=1)

        # ---- Combine All Features ----------------------------------------------
        all_feats = torch.cat([map_features, extra_feats], dim=1)
        return self.linear(all_feats)


##################### ENVIRONMENT CREATION #####################

def make_env(index: int):
    """
    Create a single Spelunky environment wrapped with Monitor.

    Args:
        index: Environment index (for parallel environments)

    Returns:
        Function that creates the environment
    """
    def _init():
        env = SpelunkyEnv(
            # The game folder comes from SPELUNKY2RL_GAME_DIR (or pass game_dir="...")

            # Performance settings
            frames_per_step=6,   # 6 frames between actions (~10 actions/sec)
            # speedup=True is the default: the game runs as fast as the machine allows

            # Training settings
            manual_control=False,  # AI control
            god_mode=False         # No god mode (agents must avoid damage)
        )
        return Monitor(env)
    return _init


##################### TRAINING #####################

if __name__ == "__main__":

    # -------- Hyperparameters ------------------------------------------------
    NUM_ENVS = 6              # Number of parallel environments
    TIMESTEPS_PER_ROLLOUT = 2048  # Steps per environment before update
    TOTAL_LOOPS = 300         # Number of training loops
    TOTAL_TIMESTEPS = TIMESTEPS_PER_ROLLOUT * TOTAL_LOOPS * NUM_ENVS

    print("=" * 70)
    print("SpelunkyRL - Get to Exit Training")
    print("=" * 70)
    print("Configuration:")
    print(f"  - Parallel environments: {NUM_ENVS}")
    print(f"  - Timesteps per rollout: {TIMESTEPS_PER_ROLLOUT}")
    print(f"  - Total loops: {TOTAL_LOOPS}")
    print(f"  - Total timesteps: {TOTAL_TIMESTEPS:,}")
    print("  - Algorithm: RecurrentPPO with LSTM")
    print("=" * 70)
    print()

    # -------- Create Parallel Environments -----------------------------------
    print("Creating parallel environments...")
    env = SubprocVecEnv([make_env(i) for i in range(NUM_ENVS)])
    print(f"✓ {NUM_ENVS} environments created successfully")
    print()

    # -------- Setup Callbacks ------------------------------------------------
    checkpoint_callback = CheckpointCallback(
        save_freq=TIMESTEPS_PER_ROLLOUT * 5,  # Save every 5 rollouts
        save_path="./models_get_to_exit",
        name_prefix="ppo_get_to_exit",
        verbose=1
    )

    success_callback = SuccessRateCallback(verbose=1)

    # -------- Create Model ---------------------------------------------------
    print("Creating RecurrentPPO model...")
    model = RecurrentPPO(
        policy="MultiInputLstmPolicy",
        env=env,
        verbose=2,
        device="auto",  # CUDA if available

        # Training parameters
        n_steps=TIMESTEPS_PER_ROLLOUT,
        learning_rate=3e-4,
        ent_coef=0.02,      # Entropy coefficient (exploration)
        gamma=0.98,         # Discount factor

        # Network architecture
        policy_kwargs=dict(
            features_extractor_class=SpelunkyFeaturesExtractor,
            features_extractor_kwargs={},
            lstm_hidden_size=64,  # LSTM hidden state size
            n_lstm_layers=1,      # Number of LSTM layers
        ),

        # Logging
        tensorboard_log="./tensorboard_logs",
    )
    print("✓ Model created successfully")
    print()

    # -------- Train Model ----------------------------------------------------
    print("Starting training...")
    print("Monitor progress with: tensorboard --logdir=./tensorboard_logs")
    print("Press Ctrl+C to stop training early")
    print()

    try:
        model.learn(
            total_timesteps=TOTAL_TIMESTEPS,
            tb_log_name="get_to_exit_training",
            callback=[checkpoint_callback, success_callback],
            reset_num_timesteps=False
        )

        print("\n" + "=" * 70)
        print("Training completed successfully!")
        print("=" * 70)

        # Save final model
        final_model_path = "./models_get_to_exit/final_model.zip"
        model.save(final_model_path)
        print(f"Final model saved to: {final_model_path}")

    except KeyboardInterrupt:
        print("\n\nTraining interrupted by user")
        print("Saving current model...")

        interrupted_model_path = "./models_get_to_exit/interrupted_model.zip"
        model.save(interrupted_model_path)
        print(f"Model saved to: {interrupted_model_path}")

    except Exception as e:
        print(f"\n\nError during training: {e}")
        import traceback
        traceback.print_exc()

    finally:
        print("Closing environments...")
        env.close()
        print("Done!")
