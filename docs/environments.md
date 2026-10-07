# Environments Guide

SpelunkyRL provides a flexible environment system built on [Gymnasium](https://gymnasium.farama.org/). This guide covers available environments, how to customize them, and how to create your own from scratch.

## Table of Contents

- [Pre-built Environments](#pre-built-environments)
- [Creating Custom Environments](#creating-custom-environments)
- [Required Components](#required-components)
- [Optional Components](#optional-components)
- [Complete Example](#complete-example)
- [Advanced Topics](#advanced-topics)

## Pre-built Environments

SpelunkyRL includes several ready-to-use environments in `src/spelunky2rl/envs/`. They are also
registered with Gymnasium once `spelunky2rl` is imported:

```python
import gymnasium as gym
import spelunky2rl  # registers the ids

env = gym.make("spelunky2rl/GetToExit-v0")
# also: spelunky2rl/Default-v0, Dummy-v0, GoldGrabber-v0, EnemyKiller-v0
# render_mode="rgb_array" enables render()
```

### Dummy Environment

**File**: `dummy_environment.py`

The simplest environment - useful for testing and as a minimal starting point.

```python
from spelunky2rl.envs.dummy_environment import SpelunkyEnv

env = SpelunkyEnv()  # game folder from SPELUNKY2RL_GAME_DIR, or game_dir="..."
```

**Characteristics**:
- Minimal observation space
- Simple reward function
- Good for initial testing

### Get to Exit

**File**: `get_to_exit.py`

Goal-reaching task where the agent navigates to the level exit as quickly as possible.

**Observation Space**:
- Terrain grid (11×21) of entity type IDs
- Character state (animation/action state)
- Can jump flag

**Action Space**: `[Movement X, Movement Y, Jump]`

**Reward Function**:
- Step penalty (-0.01) for efficiency
- Distance-based reward shaping
- Large bonus for reaching exit
- Truncation after 90 seconds or 200 steps without improvement

**Features**:
- Removes all enemies and traps at level start
- Tracks minimum distance to goal
- Success/failure tracking in info dict

```python
from spelunky2rl.envs.get_to_exit import SpelunkyEnv

env = SpelunkyEnv()
```

### Gold Grabber

**File**: `gold_grabber.py`

Resource collection task where the agent collects as much gold as possible.

**Observation Space**:
- Terrain grid (11×21)
- Gold value grid (11×21) showing gold item values at each position
- Character state
- Can jump flag

**Action Space**: `[Movement X, Movement Y, Jump]`

**Reward Function**:
- Reward proportional to gold collected (delta_money / 500.0)
- Distance shaping towards the nearest visible gold
- Tracks total episode gold
- 90-second time limit (never terminates, only truncates)

**Features**:
- Removes all enemies and traps
- Maps gold entity positions to grid
- Provides gold delta and cumulative tracking

```python
from spelunky2rl.envs.gold_grabber import SpelunkyEnv

env = SpelunkyEnv(
)
```

### Enemy Killer

**File**: `enemy_killer.py`

Combat-focused task where the agent must kill as many enemies as possible.

**Observation Space**:
- Terrain grid (11×21)
- Variable-length list of nearby enemies with:
  - Position (x, y)
  - Velocity (vx, vy)
  - Type ID
  - Facing direction
  - Held item
- Character state
- Can jump flag

**Action Space**: `[Movement X, Movement Y, Jump, Attack]`

**Reward Function**:
- +0.5 reward per enemy killed
- 90-second time limit

**Features**:
- Keeps enemies but removes shopkeepers and traps
- Uses Sequence space for variable-length entity lists
- Filters entity info to only include enemy types (219-342)

```python
from spelunky2rl.envs.enemy_killer import SpelunkyEnv

env = SpelunkyEnv(
)
```

## Creating Custom Environments

All custom environments inherit from `SpelunkyRLEngine`. You can either:

1. **Extend an existing environment** - Modify just the parts you need
2. **Create from scratch** - Full control over all components

### Method 1: Extend Existing Environment

If you want to modify just the reward function or observation space:

```python
from spelunky2rl.envs.get_to_exit import SpelunkyEnv

class CustomEnv(SpelunkyEnv):
    def reward_function(self, gamestate, last_gamestate, action, info):
        # Your custom reward logic
        reward = 0.0

        # Example: Bonus for gold
        gold_delta = gamestate["basic_info"]["money"] - last_gamestate["basic_info"]["money"]
        reward += gold_delta / 100.0

        # Keep original goal-reaching logic
        if gamestate["dist_to_goal"] == 0:
            reward += 10.0
            return reward, True, False, {"success": True}

        return reward, False, False, info

env = CustomEnv(
)
```

### Method 2: Create from Scratch

See `src/spelunky2rl/envs/template_environment.py` for a fully commented template.

## Required Components

Every custom environment **must** define these components:

### 1. Observation Space

Defines what the agent observes each step. Must be a valid [Gymnasium space](https://gymnasium.farama.org/api/spaces/).

```python
from gymnasium.spaces import Dict, Box, Discrete
import numpy as np

observation_space = Dict({
    'map_info': Box(low=0, high=116, shape=(11, 21), dtype=np.int32),
    'char_state': Discrete(23),
    'can_jump': Discrete(2),
})
```

**Common observations**:
- `map_info` - 11×21 grid of entity IDs around player (requested via `data_to_send`; the size can change)
- `char_state` - Player animation state (0-22, see [overlunky docs](https://spelunky-fyi.github.io/overlunky/))
- `can_jump` - Whether player can currently jump
- `dist_to_goal` - Distance to level exit (if requested)
- `health`, `bombs`, `ropes`, `money` - Player stats from `basic_info`

### 2. Data to Send

Specifies which data to request from the Lua script, beyond `basic_info` (always sent). This affects
performance - only request what you need.

```python
data_to_send = [
    "map_info",      # 11×21 grid of entity IDs
    "dist_to_goal",  # Distance to exit
    "entity_info",   # Detailed entity information
]
```

**Available options**:
- `"map_info"` - Terrain grid around player
- `"dist_to_goal"` - Distance to level exit
- `"entity_info"` - Nearby entities with position, velocity, type, etc.

`map_info` and `entity_info` cover a view centred on the player, 21 tiles wide and 11 high by
default. To change it, give the fields as a dict of parameters (odd sizes):

```python
data_to_send = {
    "map_info": {"width": 41, "height": 21},
    "entity_info": {"width": 41, "height": 21},
    "dist_to_goal": {},
}
```

A wrong field name or parameter is a `ValueError` when the environment is created.

### 3. Reward Function

Defines how the agent is rewarded. This is the core of your RL task.

```python
def reward_function(self, gamestate, last_gamestate, action, info):
    """
    Args:
        gamestate (dict): Current game state
        last_gamestate (dict): Previous game state
        action (list): Action taken
        info (dict): Info dict to populate

    Returns:
        tuple: (reward, done, truncated, info)
    """
    reward = 0.0
    done = False
    truncated = False

    # Your reward logic here...

    return float(reward), done, truncated, info
```

`done` is Gymnasium's `terminated`: the task really ended (goal reached, failure). Use `truncated`
for time limits and other cut-offs, and do not return `done or truncated` as `done`: learners like
Stable-Baselines3 bootstrap the value of truncated states and would treat time limits as real endings.
The engine sets `done` itself when the player dies or the level is completed.

**Gamestate structure**:
```python
{
    "basic_info": {
        "time": int,           # Game time (60 FPS)
        "health": int,         # Current HP
        "bombs": int,
        "ropes": int,
        "money": int,
        "x_rest": float,       # Player X position (fractional part)
        "y_rest": float,       # Player Y position (fractional part)
        "char_state": int,     # Animation state (0-22)
        "can_jump": bool,
        "win": int,            # 1 if level completed
        "dead_enemies": int,   # Total enemies killed
    },
    "map_info": np.ndarray,    # If requested: int32, (height, width)
    "dist_to_goal": int,       # If requested
    "entity_info": np.ndarray, # If requested: float64, (entities, 7)
}
```

**Tips**:
- The engine automatically handles death (health <= 0) and win conditions
- Use `info["success"] = True` to track successful episodes
- Return `done=True` when goal is reached
- Return `truncated=True` for time limits or failure conditions
- Store episode state in `self` attributes (e.g., `self.min_dist_to_goal`)

### 4. Gamestate to Observation

Converts raw gamestate from Lua to your observation space format.

```python
def gamestate_to_observation(self, gamestate):
    """
    Args:
        gamestate (dict): Raw game state from Lua

    Returns:
        dict: Observation matching observation_space
    """
    observation = {}

    observation["map_info"] = np.array(gamestate["map_info"], dtype=np.int32)
    observation["char_state"] = np.int64(gamestate["basic_info"]["char_state"])
    observation["can_jump"] = np.int64(int(gamestate["basic_info"]["can_jump"]))

    return observation
```

**Important**:
- Ensure types match observation_space (use `np.int32`, `np.float32`, etc.)
- Clip values to valid ranges
- Handle missing data gracefully

## Optional Components

### Custom Action Space

By default, environments use the full action space:

```python
# Default action space (8 actions)
MultiDiscrete([3, 3, 2, 2, 2, 2, 2, 2])
# [Movement X, Movement Y, Jump, Whip, Bomb, Rope, Run, Door]
```

To simplify:

```python
action_space = gym.spaces.MultiDiscrete([
    3,  # Movement X: 0=left, 1=nothing, 2=right
    3,  # Movement Y: 0=down, 1=nothing, 2=up
    2,  # Jump: 0=no, 1=jump
])
```

**If you define a custom action_space, you MUST implement `action_to_input()`**:

```python
def action_to_input(self, action):
    """Convert custom action to default input format"""
    # Add default values for: whip, bomb, rope, run, door
    return action + [0, 0, 0, 1, 0]
```

### Default Reset Options

Specify default game settings:

```python
reset_options = {
    "ent_types_to_destroy": [
        600, 601,                   # Shopkeepers
        *list(range(219, 342)),     # All enemies
        *list(range(899, 906)),     # All traps
    ],
    "hp": 4,
    "bombs": 4,
    "world": 1,
    "level": 1,
}
```

These can be overridden at runtime:

```python
obs, info = env.reset(hp=8, world=2)  # Override defaults
```

`world` and `level` pick the starting level. The theme defaults to the one normally found there
(Jungle for world 2, Tide Pool for world 4, Tiamat for 6-4, Hundun for 7-4); pass `theme` with an
overlunky `THEME` id to get the alternative, e.g. `env.reset(world=2, theme=3)` for Volcana.

## Complete Example

Here's a complete custom environment that rewards gold collection and goal-reaching:

```python
import numpy as np
import gymnasium as gym
from gymnasium.spaces import Dict, Box, Discrete
from spelunky2rl import SpelunkyRLEngine

class GoldRushEnv(SpelunkyRLEngine):
    """Collect gold and reach the exit"""

    # REQUIRED: Observation space
    observation_space = Dict({
        'map_info': Box(low=0, high=116, shape=(11, 21), dtype=np.int32),
        'char_state': Discrete(23),
        'can_jump': Discrete(2),
        'gold': Box(low=0, high=np.inf, shape=(1,), dtype=np.int32),
    })

    # OPTIONAL: Custom action space (simpler than default)
    action_space = gym.spaces.MultiDiscrete([3, 3, 2])  # Move X, Move Y, Jump

    # OPTIONAL: Default reset options
    reset_options = {
        "ent_types_to_destroy": [600, 601] + list(range(219, 342)),
        "hp": 4,
    }

    # REQUIRED: Data to request from Lua
    data_to_send = ["map_info", "dist_to_goal"]

    # REQUIRED: Convert custom actions to default format
    def action_to_input(self, action):
        return action + [0, 0, 0, 1, 0]  # Add: whip, bomb, rope, run, door

    # REQUIRED: Reward function
    def reward_function(self, gamestate, last_gamestate, action, info):
        reward = -0.01  # Small step penalty
        done = False
        truncated = False

        # Reward gold collection
        gold_delta = gamestate["basic_info"]["money"] - last_gamestate["basic_info"]["money"]
        reward += gold_delta / 100.0

        # Bonus for reaching exit
        if gamestate["dist_to_goal"] == 0:
            done = True
            reward += 10.0
            info["success"] = True

        # Time limit
        if gamestate["basic_info"]["time"] >= 60 * 60:  # 60 seconds
            truncated = True

        return float(reward), done, truncated, info

    # REQUIRED: Convert gamestate to observation
    def gamestate_to_observation(self, gamestate):
        return {
            "map_info": np.array(gamestate["map_info"], dtype=np.int32),
            "char_state": np.int64(np.clip(gamestate["basic_info"]["char_state"], 0, 22)),
            "can_jump": np.int64(int(gamestate["basic_info"]["can_jump"])),
            "gold": np.array([gamestate["basic_info"]["money"]], dtype=np.int32),
        }

# Use it
env = GoldRushEnv()
```

## Advanced Topics

### Working with Entity Info

When you request `"entity_info"` in `data_to_send`, you get a numpy array with one row per nearby
entity:

```python
data_to_send = ["map_info", "entity_info"]

def gamestate_to_observation(self, gamestate):
    # Each entity: [x, y, vx, vy, type_id, facing, held_item]
    entities = gamestate["entity_info"]

    # Filter to only gold items (495-506)
    gold_entities = [e for e in entities if 495 <= e[4] <= 506]

    # Process entities as needed
    for entity in gold_entities:
        x, y, vx, vy, type_id, facing, held = entity
        # Your processing logic...
```

**Entity structure**:
- `[0]` - X position (relative to player)
- `[1]` - Y position (relative to player)
- `[2]` - X velocity
- `[3]` - Y velocity
- `[4]` - Type ID (see [overlunky entity types](https://spelunky-fyi.github.io/overlunky/#EntityType))
- `[5]` - Facing direction (0 or 1)
- `[6]` - Held item type ID

See `gold_grabber.py` for an example of mapping entities to a grid.

### Using Sequence Spaces

For variable-length observations (e.g., enemy lists):

```python
from gymnasium.spaces import Sequence, Tuple

observation_space = Dict({
    'map_info': Box(low=0, high=116, shape=(11, 21), dtype=np.int32),
    'enemies': Sequence(
        Tuple((
            Box(low=-np.inf, high=np.inf, shape=(1,), dtype=np.float32),  # x
            Box(low=-np.inf, high=np.inf, shape=(1,), dtype=np.float32),  # y
            Box(low=0, high=915, shape=(1,), dtype=np.float32),           # type
        ))
    ),
})

def gamestate_to_observation(self, gamestate):
    return {
        'map_info': np.array(gamestate["map_info"], dtype=np.int32),
        'enemies': [
            (
                np.array([e[0]], dtype=np.float32),
                np.array([e[1]], dtype=np.float32),
                np.array([e[4]], dtype=np.float32),
            )
            for e in gamestate["entity_info"]
            if 219 <= e[4] <= 342  # Enemy type IDs
        ]
    }
```

See `enemy_killer.py` for a complete example.

### Maintaining Episode State

Track state across steps using instance attributes:

```python
def reward_function(self, gamestate, last_gamestate, action, info):
    # Initialize on first use
    if not hasattr(self, 'min_dist'):
        self.min_dist = float('inf')
        self.steps_without_progress = 0

    # Update state
    current_dist = gamestate["dist_to_goal"]
    if current_dist < self.min_dist:
        self.min_dist = current_dist
        self.steps_without_progress = 0
    else:
        self.steps_without_progress += 1

    # Use state in reward logic
    if self.steps_without_progress >= 200:
        return -1.0, False, True, info  # Truncate

    # Reset state at episode end
    if done or truncated:
        self.min_dist = float('inf')
        self.steps_without_progress = 0

    return reward, done, truncated, info
```

### Reward Shaping Best Practices

1. **Scale rewards appropriately** - Keep values roughly in [-1, 1] range
2. **Balance exploration/exploitation** - Small step penalties encourage efficiency
3. **Distance-based shaping** - Reward getting closer to goals
4. **Avoid reward hacking** - Test that reward function incentivizes desired behavior
5. **Track success rate** - Use `info["success"]` to monitor training progress

Example from `get_to_exit.py`:

```python
# Step penalty (encourages efficiency)
reward = -0.01

# Progress reward (shaped)
reward += (last_gamestate["dist_to_goal"] - gamestate["dist_to_goal"]) * 0.1

# Goal bonus (sparse)
if gamestate["dist_to_goal"] == 0:
    reward += 10.0
```

## Entity Type IDs Reference

Common entity ranges (see [overlunky docs](https://spelunky-fyi.github.io/overlunky/#EntityType) for complete list):

- **219-342**: Enemies (monsters, animals)
- **495-506**: Gold items (nuggets, bars, gems)
- **600-601**: Shopkeepers
- **899-906**: Traps (spikes, arrow traps, etc.)

## Next Steps

- **[Architecture Guide](architecture.md)** - Learn how the engine works internally
- **Example Environments** - Study `src/spelunky2rl/envs/` for more examples
- **Training Examples** - Check `examples/train_get_to_exit.py` for RL training
