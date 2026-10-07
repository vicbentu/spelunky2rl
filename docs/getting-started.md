# Getting Started with SpelunkyRL

This guide will walk you through installing and running your first SpelunkyRL environment.

SpelunkyRL drives a real copy of Spelunky 2. Python runs where you train; each environment
starts its own game instance, headless in a Docker container, and closes it on `env.close()`.

**Linux only for now.** Running natively on Windows is not implemented yet (to do).

## You need your own copy of the game

Spelunky 2 is not included anywhere, including the Docker image. Buy it on Steam, install it once,
and copy the whole folder (the one with `Spel2.exe`) somewhere else. Use that copy for SpelunkyRL:
modding tools should never touch your Steam installation. Steam is not needed after that: on Linux
the image swaps in the [Goldberg emulator](https://github.com/Detanup01/gbe_fork) for the Steam API.

Then tell SpelunkyRL where the copy is, once:

```bash
export SPELUNKY2RL_GAME_DIR="/path/to/Spelunky 2"
```

or pass `game_dir="..."` when creating an environment.

## Installation on Linux (Docker)

1. Install [Docker Engine](https://docs.docker.com/engine/install/) and make sure your user can run
   `docker` without sudo. For GPU rendering also install the
   [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/);
   without it the game renders on the CPU (slower with many instances, but works).
2. Install the package (Python 3.9+, in a virtual environment):

   ```bash
   pip install spelunky2rl    # with launcher="wine", add [render] for render()
   ```

3. Get the game image. Either pull it, or build it from a clone of the repo (a few minutes):

   ```bash
   spelunky2rl pull
   # or: docker build -f docker/Dockerfile -t ghcr.io/vicbentu/spelunky2rl-game:$(python -c "import spelunky2rl.version as v; print(v.__version__)") .
   ```

4. Check everything:

   ```bash
   spelunky2rl doctor
   ```

Each environment then runs `docker run --rm ...` on creation and kills its container on `close()`.
Nothing keeps running when no environment is open. The first start of a new game version takes
~20 s while Playlunky builds its asset cache in `~/.cache/spelunky2rl`; later starts take ~8 s.

**From source** (to work on the code or the mod, or to run `examples/`):

```bash
git clone https://github.com/vicbentu/spelunky2rl.git
cd spelunky2rl
pip install -e ".[dev]"    # add [render], and [train]/[video] for the training examples
```

**Without Docker** (development): `scripts/setup_wine.sh` installs the same pieces for the host's Wine,
then use `launcher="wine"` or `SPELUNKY2RL_LAUNCHER=wine`.

**Editing the Lua mod**: set `SPELUNKY2RL_DEV_MOD=/path/to/spelunky2rl/src/spelunky2rl/mod/lua` and new
environments load it instead of the copy in the image; no rebuild needed.

## Your First Environment

Here's a minimal example to verify everything is working:

```python
from spelunky2rl.envs.dummy_environment import SpelunkyEnv

# Uses SPELUNKY2RL_GAME_DIR; or SpelunkyEnv(game_dir="/path/to/Spelunky 2")
env = SpelunkyEnv()

# Reset the environment
obs, info = env.reset()

# Take 100 random steps
for _ in range(100):
    action = env.action_space.sample()
    obs, reward, done, truncated, info = env.step(action)

    if done or truncated:
        obs, info = env.reset()

# Clean up
env.close()
```

## Environment Configuration

The `SpelunkyRLEngine` (base class for all environments) accepts several configuration parameters:

### Basic Parameters

```python
env = SpelunkyEnv(
    game_dir="/path/to/Spelunky 2",   # Optional: folder with Spel2.exe (default: $SPELUNKY2RL_GAME_DIR)
    frames_per_step=6,                # Optional: Game frames per RL step (default: 6)
    render_enabled=False,             # Optional: Enable render() method (default: False)
    render_resolution=(640, 360),     # Optional: Size of render() frames, 16:9 (default: 640x360)
    launcher="auto",                  # Optional: "docker" (default) or "wine"
    renderer="auto",                  # Optional: "gpu", "cpu" or "auto" (GPU if Docker can use one)
    launcher_options=None,            # Optional: e.g. {"image": "..."} for Docker
    step_timeout=60.0,                # Optional: Max seconds to wait for the game each step
    startup_timeout=180.0,            # Optional: Max seconds for the game to start and connect
    max_launch_attempts=3,            # Optional: Relaunches if the game dies before connecting
)
```

If the game stops answering, `reset()`/`step()` raise `TimeoutError` instead of hanging.
`close()` can be called any number of times; it also runs automatically at interpreter exit.

### Reset Options

You can configure game settings via `reset()` or by passing them to `__init__()` as kwargs:

```python
# Option 1: Configure at initialization
env = SpelunkyEnv(
    hp=8,           # Start with 8 HP
    bombs=10,       # Start with 10 bombs
    world=2,        # Start in world 2
)

# Option 2: Configure at reset
obs, info = env.reset(
    seed=42,        # Set random seed
    hp=4,           # Start with 4 HP
    god_mode=True,  # Enable invulnerability
)
```

### Available Reset Options

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `seed` | int | Random | Random seed for level generation |
| `speedup` | bool | True | Run as fast as the machine allows; `False` plays in real time (60 FPS) |
| `manual_control` | bool | False | Enable keyboard control (useful for testing) |
| `god_mode` | bool | False | Player invulnerability |
| `hp` | int | 4 | Starting health |
| `bombs` | int | 4 | Starting bombs |
| `ropes` | int | 4 | Starting ropes |
| `gold` | int | 0 | Starting gold |
| `world` | int | 1 | Starting world (1-16, see [THEME](https://spelunky-fyi.github.io/overlunky/#THEME)) |
| `level` | int | 1 | Starting level within world |
| `ent_types_to_destroy` | list | [] | Entity type IDs to remove at level start |
| `theme` | int | None | Overlunky THEME id; None = the usual theme for `world`/`level` |
| `time_ghost` | bool | True | The ghost that appears after 3 minutes; it slows the game ~8x, disable for long episodes |
| `audio` | bool | False | Game audio |

## Performance Optimization

The defaults are already the fastest setup for training: `speedup=True` and no render.

```python
env = SpelunkyEnv()  # speedup=True, render_enabled=False, frames_per_step=6
```

Without render the game skips drawing and runs 200 logic-only frames for each real one (the engine
picks this; a step is the same game time either way), so the game is no longer the bottleneck: the
per-step exchange with Python is. One instance, `get_to_exit`, Ryzen 9 7900X and RTX 3060: about
1,600 steps/s with either renderer. With `speedup=False` the game runs in real time, 10 steps/s with
`frames_per_step=6`.

With `render_enabled=True` the last frame of each step is drawn (the one `render()` returns, the
state's own), which costs most of the step. The game draws at `render_resolution`, so a smaller one
is faster. Measured calling `render()` every step:

| `render_resolution` | GPU renderer | CPU renderer (lavapipe) |
|---|---|---|
| 160x90 | 620–670 steps/s | 240 steps/s |
| 320x180 | 580–650 steps/s | 230 steps/s |
| 640x360 | 590 steps/s | 170 steps/s |
| 1280x720 | 380–430 steps/s | 92 steps/s |

With `launcher="wine"` `render()` grabs the screen instead, which may still show a frame from before
the state.

With `render_enabled=False` the screen size still matters (with lavapipe, 640x360 runs ~20 % slower
than 160x90), so the game runs on a 160x90 screen whatever `render_resolution` says.

### Many environments

Each environment is its own game (one container on Linux), so run several in parallel. Measured on a
Ryzen 9 7900X (24 threads) with `get_to_exit` and the defaults, one Python process per env:

| Containers | GPU renderer | CPU renderer (lavapipe) |
|---|---|---|
| 1 | 1,700 steps/s | 1,700 steps/s |
| 8 | 10,400 steps/s total | 8,900 steps/s total |
| 16 | 14,300 steps/s total | 12,100 steps/s total |
| RAM per container | ~1 GiB | ~2.8 GiB |

Each instance keeps about one core busy, and so does its Python process. Synchronous vector envs
(Gymnasium's `AsyncVectorEnv`, SB3's `SubprocVecEnv`) wait for the slowest env every step; with them
16 envs gave ~3,000 steps/s in total. Asynchronous collection (one process per env) scales better.

## Manual Control (Testing)

To test your environment with keyboard controls:

```python
env = SpelunkyEnv(
    manual_control=True,    # Enable keyboard input
    god_mode=True,          # Useful for testing
)

obs, info = env.reset()

# Game loop - keyboard controls are active
while True:
    # Action doesn't matter in manual_control mode
    obs, reward, done, truncated, info = env.step(env.action_space.sample())

    if done or truncated:
        obs, info = env.reset()
```

Controls:
- Arrow keys: Movement
- Z: Jump
- X: Whip/Attack
- C: Bomb
- V: Rope
- Shift: Run
- Up Arrow (at door): Enter door

See `examples/manual_control.py` for a complete example.

## Example Scripts

SpelunkyRL includes several example scripts in `examples/`:

- **`manual_control.py`** - Test environment with keyboard controls
- **`train_get_to_exit.py`** - Complete training example with RecurrentPPO
- **`evaluate_model.py`** - Evaluate a trained model
- **`record_video.py`** - Record video of agent gameplay

## Logging

SpelunkyRL can log game state information for debugging:

```python
env = SpelunkyEnv(
    log_file="game_log.txt",        # Where to save logs
    log_info=["all", "map_info"],   # What to log
)
```

Available log options:
- `"all"` - Full JSON gamestate with timestamp
- `"map_info"` - Formatted 11x21 terrain grid
- `"entity_count"` - Count of each entity type visible

## Next Steps

- **[Environments Guide](environments.md)** - Learn about available environments and create your own
- **[Architecture Guide](architecture.md)** - Understand how SpelunkyRL works internally
- **Example Scripts** - Check `examples/` for training and evaluation examples

## Troubleshooting

**Environment won't start:**
- Run `spelunky2rl doctor`
- The error message ends with the launcher's recent output (the container's, on Linux)

**Game is too slow:**
- Check that nothing passes `speedup=False` or `render_enabled=True` / `render_mode="rgb_array"`
- Decrease `frames_per_step` (but this affects agent reactivity)

**Slow episodes after 3 minutes of game time:**
- That is the ghost; pass `time_ghost=False`

**Import errors:**
- Make sure you've installed the package: `pip install spelunky2rl`
- Check that your virtual environment is activated
- Verify all dependencies installed correctly
