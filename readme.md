# SpelunkyRL

SpelunkyRL is a Reinforcement Learning environment for Spelunky 2, providing a standard Gymnasium interface with predefined tasks and extensive customization options.

**Built on the excellent work by the spelunky-fyi community:**
- **[overlunky](https://github.com/spelunky-fyi/overlunky)** - Lua API for game state access and manipulation
- **[Playlunky](https://github.com/spelunky-fyi/Playlunky)** - Mod loading and script injection
- **[modlunky2](https://github.com/spelunky-fyi/modlunky2)** - Mod management and installation tools

## Features

- **Gymnasium Interface** - Standard RL environment API compatible with Stable-Baselines3 and other frameworks
- **Pre-built Environments** - Ready-to-use tasks (navigation, gold collection, combat)
- **Custom Environments** - Flexible system for creating your own tasks
- **High Performance** - Optimized for fast training with parallel environments
- **Complete Control** - Access to game state, entities, and full action space

## Quick Start

### Installation

The game runs headless in Docker on Linux, one container per environment (Windows: not implemented yet).
Either way you need your own copy of Spelunky 2 (Steam is only needed to download it).

```bash
pip install spelunky2rl
spelunky2rl pull      # Linux: the game runtime image (Wine, Playlunky; not the game), or build it
spelunky2rl doctor    # checks Docker, GPU, the image and your game folder
```

To work on the code or the Lua mod, clone the repo and `pip install -e ".[dev]"`.
See [Getting Started](https://github.com/vicbentu/spelunky2rl/blob/main/docs/getting-started.md) for the details.

### Basic Usage

```python
from spelunky2rl.envs.get_to_exit import SpelunkyEnv

env = SpelunkyEnv(game_dir="/path/to/Spelunky 2")  # or set SPELUNKY2RL_GAME_DIR

obs, info = env.reset()
for _ in range(1000):
    action = env.action_space.sample()
    obs, reward, done, truncated, info = env.step(action)
    if done or truncated:
        obs, info = env.reset()

env.close()
```

By default the game runs as fast as the machine allows (~1,600 steps/s per instance) and draws
nothing. For images, pass `render_mode="rgb_array"` (`render()` returns the frame of each state, to
train on pixels) or `render_mode="rgb_array_list"` (every frame, to record videos). Every option and
what each costs: [Getting Started](https://github.com/vicbentu/spelunky2rl/blob/main/docs/getting-started.md#creating-an-environment).

## Available Environments

- **`dummy_environment`** - Minimal test environment
- **`get_to_exit`** - Navigate to the level exit as quickly as possible
- **`gold_grabber`** - Collect as much gold as possible within time limit
- **`enemy_killer`** - Combat-focused task to eliminate enemies

## Documentation

- **[Getting Started](https://github.com/vicbentu/spelunky2rl/blob/main/docs/getting-started.md)** - Installation, configuration, and first steps
- **[Environments Guide](https://github.com/vicbentu/spelunky2rl/blob/main/docs/environments.md)** - Creating and customizing environments
- **[Architecture Guide](https://github.com/vicbentu/spelunky2rl/blob/main/docs/architecture.md)** - Technical details and internal workings

## Examples

Check `examples/` for complete examples:

- **`manual_control.py`** - Test environment with keyboard controls
- **`train_get_to_exit.py`** - Train an agent with RecurrentPPO
- **`evaluate_model.py`** - Evaluate trained models
- **`record_video.py`** - Record videos of agent gameplay (every frame, at 60 FPS)

## 🔮 Future Work

- [ ] **Implement more tasks**: specially, long-term planning tasks that require extended sequences of actions and strategic decision-making.

- [ ] **Multi-agent scenarios**: both cooperative and competitive dynamics between multiple agents.

- [ ] **Performance optimization**

- [ ] **Add customization options**: expanding the configuration possibilities.

- [ ] ...

## 🙏 Credits & Acknowledgments

This project would not be possible without the incredible work of the spelunky-fyi community:

- **[overlunky](https://github.com/spelunky-fyi/overlunky)** - The foundation of this project. Overlunky provides the comprehensive Lua API that enables game state access, entity manipulation, and real-time game control. All game interactions in SpelunkyRL are powered by overlunky's scripting capabilities.

- **[Playlunky](https://github.com/spelunky-fyi/Playlunky)** - Essential for mod loading and Lua script injection into Spelunky 2. Playlunky makes it possible to run our custom scripts alongside the game without modifying the original executable.

- **[modlunky2](https://github.com/spelunky-fyi/modlunky2)** - Provides the mod management infrastructure and tools that make setting up and running SpelunkyRL straightforward.

Special thanks to the entire spelunky-fyi community for maintaining these excellent tools and fostering the Spelunky modding ecosystem.

## License

MIT, see [LICENSE](https://github.com/vicbentu/spelunky2rl/blob/main/LICENSE). Bundled third-party code keeps its own license: luasocket (MIT,
`src/spelunky2rl/mod/lua/luasocket/license.txt`) and overlunky's `entities-hierarchy.md` (MIT).
Spelunky 2 itself is not included: each user provides their own copy of the game.
