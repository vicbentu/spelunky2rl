# SpelunkyRL Examples

This directory contains example scripts demonstrating how to use SpelunkyRL for reinforcement learning.

## Examples Overview

| Script | Purpose |
|--------|---------|
| `manual_control.py` | Test environment with keyboard control |
| `benchmark_performance.py` | Measure environment performance (FPS/throughput) |
| `train_get_to_exit.py` | Train an agent from scratch |
| `evaluate_model.py` | Evaluate a trained model |
| `record_video.py` | Record video of trained agent, every frame at 60 FPS |

## Quick Start

### 1. Manual Control (Test Your Installation)

Test your SpelunkyRL installation by controlling the character manually:

```bash
python examples/manual_control.py
```

**What it does:**
- Opens Spelunky 2 with keyboard control enabled
- God mode activated (invulnerability)
- Good for testing your setup and understanding game mechanics

### 2. Benchmark Performance

Measure how fast your environments run (important for training efficiency):

```bash
python examples/benchmark_performance.py --env dummy
```

**What it does:**
- Measures steps per second (FPS) for different environments
- Tests single or parallel environment configurations
- Helps identify optimal settings for your hardware

**Common usage:**
```bash
# Test a specific environment
python examples/benchmark_performance.py --env get_to_exit

# Test parallel performance
python examples/benchmark_performance.py --env dummy --num-envs 1 2 4 8

# Longer benchmark for accuracy
python examples/benchmark_performance.py --env gold_grabber --duration 60
```

**Environments you can test:**
- `dummy` - Minimal environment (fastest)
- `get_to_exit` - Navigation task
- `gold_grabber` - Collection task
- `enemy_killer` - Combat task

### 3. Train an Agent

Train an RL agent to navigate to the level exit, using SB3:

```bash
python examples/train_get_to_exit.py
```

**What it does:**
- Trains a RecurrentPPO agent with LSTM
- Uses 6 parallel environments for faster training
- Saves checkpoints every 5 rollouts
- Logs training metrics to TensorBoard

**Monitor progress:**
```bash
tensorboard --logdir=./tensorboard_logs
```

### 4. Evaluate a Trained Model

Test a trained model's performance:

```bash
python examples/evaluate_model.py
```

**Before running:**
- Update `MODEL_PATH` in the script to point to your trained model
- Example: `MODEL_PATH = "./models_get_to_exit/final_model.zip"`

**What it does:**
- Runs 50 evaluation episodes
- Calculates success rate and statistics
- Reports average completion time for successful episodes

### 5. Record Video of Agent

Create a video of your trained agent playing:

```bash
python examples/record_video.py
```

**Before running:**
- Update `MODEL_PATH` in the script
- Install opencv: `pip install opencv-python`

**What it does:**
- Records 30 seconds of gameplay, every game frame (`render_mode="rgb_array_list"`) at 60 FPS
- Saves as MP4 in `./videos/` directory
- Shows agent's learned behavior

## Configuration

All scripts find the game through `SPELUNKY2RL_GAME_DIR` (a modding copy of the Spelunky 2 folder,
not your Steam installation). See [Getting Started](../docs/getting-started.md).

## Requirements

### Basic Installation

For just using the environments (no training):
```bash
pip install spelunky2rl
```

### For Training (recommended)

To run the training examples:
```bash
pip install spelunky2rl[train]
```

This installs: `torch`, `stable-baselines3`, `sb3-contrib`

**Note:** GPU (CUDA) is highly recommended for training. Training on CPU is possible but much slower (10+ hours vs 2-4 hours).

### For Video Recording

To record videos of trained agents:
```bash
pip install spelunky2rl[video]
```

This installs: `opencv-python`

### Everything

To install all optional dependencies:
```bash
pip install spelunky2rl[all]
```

## Customization

### Changing the Environment

Replace `SpelunkyEnv` import to try different tasks:

```python
# from spelunky2rl.envs.get_to_exit import SpelunkyEnv
from spelunky2rl.envs.gold_grabber import SpelunkyEnv  # Collect gold
from spelunky2rl.envs.enemy_killer import SpelunkyEnv   # Kill enemies
```

### Adjusting Hyperparameters

In `train_get_to_exit.py`, you can modify:

```python
NUM_ENVS = 6              # Parallel environments (more = faster)
TIMESTEPS_PER_ROLLOUT = 2048  # Steps before model update
learning_rate = 3e-4      # Learning rate
lstm_hidden_size = 64     # LSTM size
```

### Network Architecture

Modify `SpelunkyFeaturesExtractor` to experiment with:
- Different CNN architectures
- Embedding dimensions
- Feature fusion strategies

## Next Steps

After running these examples:

1. **Create custom environments:** See `src/spelunky2rl/envs/template_environment.py`
2. **Design custom reward functions:** Modify reward shaping for your task
3. **Experiment with algorithms:** Try different RL algorithms from stable-baselines3
4. **Multi-task learning:** Train agents on multiple objectives