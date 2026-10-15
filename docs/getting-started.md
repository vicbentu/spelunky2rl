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

## Creating an environment

Every environment (`SpelunkyRLEngine` and its subclasses in `spelunky2rl.envs`) takes these
parameters; `gymnasium.make("spelunky2rl/...", ...)` passes them through.

| Parameter | Type | Default | What it does |
|---|---|---|---|
| `game_dir` | str | `$SPELUNKY2RL_GAME_DIR` | Spelunky 2 folder (the one with `Spel2.exe`) |
| `frames_per_step` | int | 6 | Game frames (1/60 s each) per `step()`; the action is held for all of them |
| `render_mode` | str | None | `None`, `"rgb_array"` or `"rgb_array_list"`: what `render()` returns, see [Speed and images](#speed-and-images) |
| `render_enabled` | bool | False | The same as `render_mode="rgb_array"` (the older name) |
| `render_resolution` | (int, int) | (640, 360) | Size of the frames, 16:9 and at least 64x36; the game draws at this size |
| `launcher` | str or `Launcher` | "auto" | `"docker"` (the default on Linux; `$SPELUNKY2RL_LAUNCHER` changes it) or `"wine"` |
| `renderer` | str | "auto" | `"gpu"`, `"cpu"` (Mesa's lavapipe) or `"auto"` (GPU if Docker can use one) |
| `cpu_threads` | int | None | Threads drawing each frame on the CPU; None is one per core. See [Drawing on the CPU](#drawing-on-the-cpu) |
| `gpu_memory_mb` | int | 512 | VRAM each game may use when it draws on the GPU; None for no limit. See [Many games on one GPU](#many-games-on-one-gpu) |
| `launcher_options` | dict | None | Extra arguments for the launcher, e.g. `{"image": "..."}` for Docker |
| `log_file` | str | None | Write every state to this file, see [Logging](#logging) |
| `log_info` | list | `["all"]` | What `log_file` gets |
| `step_timeout` | float | 60.0 | Seconds to wait for the game in `reset()`, `step()` and `render()` |
| `startup_timeout` | float | 180.0 | Seconds for the game to start and connect |
| `max_launch_attempts` | int | 3 | Launches before giving up if the game dies before connecting |
| `spelunky_dir` | str | None | The old name of `game_dir` |

Any reset option (next section) can be passed here too, as the default of every episode.

If the game stops answering, `reset()`/`step()` raise `TimeoutError` instead of hanging.
`close()` can be called any number of times; it also runs automatically at interpreter exit.

## Reset options

They set up each episode. There are three ways to give them, and each overrides the one before:

```python
env = SpelunkyEnv(hp=8, world=2)                 # 1. on creation: the default of every episode
obs, info = env.reset(seed=42, god_mode=True)    # 2. as arguments of reset(), for this episode
obs, info = env.reset(options={"hp": 1})         # 3. in options, as Gymnasium wrappers pass them
```

`seed` picks the level (the same seed, the same level); without it, a random one. An unknown option
is a `TypeError`. The defaults below are the engine's; an environment can change them in its
`reset_options` (e.g. `get_to_exit` sets `ent_types_to_destroy`).

| Option | Type | Default | What it does |
|---|---|---|---|
| `speedup` | bool | True | Run as fast as the machine allows; `False` plays in real time (60 FPS) |
| `manual_control` | bool | False | Ignore the agent's actions and read the keyboard |
| `god_mode` | bool | False | The player cannot die |
| `hp` | int | 4 | Starting health |
| `bombs` | int | 4 | Starting bombs |
| `ropes` | int | 4 | Starting ropes |
| `gold` | int | 0 | Starting gold |
| `world` | int | 1 | Starting world (1-16, see [THEME](https://spelunky-fyi.github.io/overlunky/#THEME)) |
| `level` | int | 1 | Starting level within the world |
| `ent_types_to_destroy` | list | [] | Entity type ids to remove when the level starts |
| `theme` | int | None | Overlunky THEME id; None is the usual theme for `world` and `level` |
| `time_ghost` | bool | True | The ghost that appears after 3 minutes; it slows the game ~8x, turn it off for long episodes |
| `audio` | bool | False | Game audio |

## Speed and images

You choose what you want (`speedup` and `render_mode`); the engine picks how to run the game for it.

| Use | `speedup` | `render_mode` | `render()` returns | steps/s, GPU | steps/s, CPU |
|---|---|---|---|---|---|
| Train without images | True (default) | None (default) | — | ~1,600 | ~1,600 |
| Train with images | True | `"rgb_array"` | the frame of the last state | 590 | 170 |
| Record video | True | `"rgb_array_list"` | every frame since the last call | 140–150 | 33 |
| Real time | False | any | as above | 10 | 10 |

One instance of `get_to_exit` with `frames_per_step=6`, frames at 640x360 and `render()` called after
every step; Ryzen 9 7900X, RTX 3060 (`renderer="gpu"`) or lavapipe (`renderer="cpu"`).

- **Without images** the game skips drawing and runs 200 logic-only frames for each real one, so
  the game is no longer the bottleneck: the exchange with Python each step is. Both renderers give
  the same speed.
- **`"rgb_array"`** draws only the last frame of each step, the state's own: `render()` returns
  exactly what the agent's observation describes.
- **`"rgb_array_list"`** draws every frame. `render()` returns a list: the frames of every step since
  the last call (6 per step), and after `reset()` its frame first. Only the Docker launcher has it.
- **Real time** (`speedup=False`) runs the game at 60 frames per second: 60 / `frames_per_step` steps
  per second. There is no window to watch it yet: the game runs headless.

```python
from spelunky2rl.envs.get_to_exit import SpelunkyEnv

# Train without images: the defaults
env = SpelunkyEnv()

# Train with images: the observation and the frame of the same state
env = SpelunkyEnv(render_mode="rgb_array", render_resolution=(320, 180))
obs, info = env.reset()
frame = env.render()             # (180, 320, 3) uint8, RGB

# Record a video: every frame, at 60 frames per second
from gymnasium.utils.save_video import save_video   # needs moviepy

env = SpelunkyEnv(render_mode="rgb_array_list")
obs, info = env.reset(seed=0)
done = truncated = False
while not (done or truncated):
    obs, reward, done, truncated, info = env.step(env.action_space.sample())
save_video(env.render(), "videos", fps=env.metadata["render_fps"])
```

`env.metadata["render_fps"]` is the rate at which a video of what `render()` returns plays at the
game's speed: 60 with `"rgb_array_list"`, 60 / `frames_per_step` with `"rgb_array"`.
`gymnasium.wrappers.RecordVideo` works with `"rgb_array"` (one frame per step, in real time); with
`"rgb_array_list"` it keeps only the last frame of each step, so use `save_video` (or your own
writer, as `examples/record_video.py` does with OpenCV).

### Resolution

With images the game draws at `render_resolution`, which costs most of the step: a smaller one is
faster. Steps/s with `render()` after every step, one instance:

| `render_resolution` | `"rgb_array"`, GPU | `"rgb_array"`, CPU | `"rgb_array_list"`, GPU | `"rgb_array_list"`, CPU |
|---|---|---|---|---|
| 160x90 | 620–670 | 240 | 270–280 | 53 |
| 320x180 | 580–650 | 230 | 240–260 | 50 |
| 640x360 | 590 | 170 | 140–150 | 33 |
| 1280x720 | 380–430 | 92 | 47–49 | 15–16 |

Without images the game runs on a 160x90 screen whatever `render_resolution` says (the screen size
changes the speed even when nothing is drawn).

With `launcher="wine"`, `"rgb_array"` grabs the screen instead, which may still show a frame from
before the state, and `"rgb_array_list"` is not available.

### Many environments

Each environment is its own game (one container on Linux), so run several in parallel. Measured on a
Ryzen 9 7900X (24 threads) with `get_to_exit`, one Python process per env, without images:

| Containers | GPU renderer | CPU renderer (lavapipe) |
|---|---|---|
| 1 | 1,700 steps/s | 1,700 steps/s |
| 8 | 10,400 steps/s total | 8,900 steps/s total |
| 16 | 14,300 steps/s total | 12,100 steps/s total |
| RAM per container | ~1 GiB | ~2.8 GiB |

With images (640x360, `render()` after every step), steps/s in total:

| Containers | `"rgb_array"`, GPU | `"rgb_array"`, CPU | `"rgb_array_list"`, GPU | `"rgb_array_list"`, CPU |
|---|---|---|---|---|
| 1 | 590 | 176 | 147 | 34 |
| 4 | 1,690 | 265 | 349 | 47 |
| 8 | 1,990 | 297 | 317 | 51 |

Drawing is what limits them: lavapipe already spreads one instance's drawing over every core, so on
the CPU more instances add little, and with every frame drawn 4 instances fill the GPU (8 exceed
its 12 GiB of VRAM).

Without images each instance keeps about one core busy, and so does its Python process. With the GPU
renderer each instance keeps its VRAM within `gpu_memory_mb` (see below). Synchronous vector envs
(Gymnasium's `AsyncVectorEnv`, SB3's `SubprocVecEnv`) wait for the slowest env every step; with them
16 envs gave ~3,000 steps/s in total. Asynchronous collection (one process per env) scales better.

### Many games on one GPU

Spelunky 2 loads all its textures, ~1.6 GiB uncompressed, into VRAM at startup, though a level draws
a small part of them. `gpu_memory_mb` (512 by default) caps the VRAM each game uses: DXVK moves the
textures it has not drawn lately to system RAM. Each game then takes ~0.35 GiB instead of ~1.75, at
about the same speed (1-3 % fewer steps/s with 5 and 10 games), which leaves room for a model on the
same card. `gpu_memory_mb=None` lifts the cap;
past the card's VRAM the games still run, spilling to system memory, but a CUDA process that starts
after them can find none left.

Steps/s in total, `benchmarks/throughput.py scale --envs 1 5 10 15 20`: frames of 128x72 as the
observation (`render()` after every step), random actions, Ryzen 9 7900X (24 threads), RTX 3060
(12 GiB). *Free*: every game steps on its own; *lockstep*: every game steps and then the next step
starts, as in a synchronous vector env (an ended episode resets inside the step).

| Games | Free | Lockstep | VRAM per game | CPU cores per game |
|---|---|---|---|---|
| 1 | 645 | 597 | 0.38 GiB | 0.9 |
| 5 | 2,630 | 1,740 | 0.36 GiB | 1.2 |
| 10 | 3,150 | 1,870 | 0.35 GiB | 1.2 |
| 15 | 3,340 | 1,990 | 0.33 GiB | 1.1 |
| 20 | 3,330 | 1,890 | 0.31 GiB | 0.9 |

Past ~10 games the GPU is the limit (90 % busy). With one game the GPU barely works and the driver
lowers its clocks, so a step takes about twice as long as with a few games. In lockstep every game
waits for the slowest one and for every reset each step: about 40 % fewer steps than free.

### Drawing on the CPU

On the CPU (`renderer="cpu"`, or `"auto"` without a GPU) each game draws its frames with as many
threads as the machine has cores. That gets one frame out soonest, which is what one env needs; with
several envs their threads fight over the cores and spend more of them coordinating than drawing.
`cpu_threads` caps them per env. Only the CPU renderer reads it.

Steps/s in total with images (`"rgb_array"`, `render()` after every step), Ryzen 9 7900X (24 threads):

| `render_resolution` | Envs | `cpu_threads=None` | `cpu_threads=4` | `cpu_threads=2` |
|---|---|---|---|---|
| 128x72 | 1 | 252 | 189 | 123 |
| 128x72 | 4 | 469 | 530 | 384 |
| 128x72 | 8 | 581 | 707 | 637 |
| 128x72 | 16 | 681 | 796 | 808 |
| 640x360 | 1 | 179 | 101 | 58 |
| 640x360 | 4 | 271 | 267 | 185 |
| 640x360 | 8 | 305 | 342 | 297 |

Fewer threads pay off with several envs and small frames: try `cpu_threads=4`, and 2 with 16 envs
or more (threads times envs about the number of cores). With one env or large frames keep the
default: recording a video at 960x540 (`"rgb_array_list"`, one env) goes from 23 steps/s to 11 with
`cpu_threads=4`. The GPU, where there is one, is still several times faster: 2,400 steps/s with 4
envs at 128x72.

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
- **`record_video.py`** - Record video of agent gameplay, every frame at 60 FPS

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
- Check that nothing passes `speedup=False` or a `render_mode` (see [Speed and images](#speed-and-images))
- Decrease `frames_per_step` (but this affects agent reactivity)

**Slow episodes after 3 minutes of game time:**
- That is the ghost; pass `time_ghost=False`

**Import errors:**
- Make sure you've installed the package: `pip install spelunky2rl`
- Check that your virtual environment is activated
- Verify all dependencies installed correctly
