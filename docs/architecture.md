# Architecture Guide

This guide explains how SpelunkyRL works internally - the communication protocol, process management, and technical implementation details.

## Table of Contents

- [System Overview](#system-overview)
- [Component Architecture](#component-architecture)
- [Communication Protocol](#communication-protocol)
- [Lifecycle Management](#lifecycle-management)
- [Data Flow](#data-flow)
- [Performance Considerations](#performance-considerations)

## System Overview

SpelunkyRL bridges Python-based RL frameworks with Spelunky 2 through a multi-layer architecture:

```
┌─────────────────────────────────────────────────────────────┐
│                     Python RL Agent                          │
│              (Stable-Baselines3, etc.)                      │
└──────────────────────┬──────────────────────────────────────┘
                       │ Gymnasium Interface
                       │ (reset, step, close)
┌──────────────────────▼──────────────────────────────────────┐
│                SpelunkyRLEngine                              │
│  - Socket communication                                      │
│  - Process management                                        │
│  - Frame grabbing                                            │
│  - Observation/reward processing                             │
└──────────────────────┬──────────────────────────────────────┘
                       │ Socket (JSON over TCP)
┌──────────────────────▼──────────────────────────────────────┐
│                  Lua Script (in Spelunky 2)                  │
│                (via overlunky API)                           │
│  - Game state extraction                                     │
│  - Input injection                                           │
│  - Entity manipulation                                       │
└──────────────────────┬──────────────────────────────────────┘
                       │ overlunky API
┌──────────────────────▼──────────────────────────────────────┐
│               Spelunky 2 Game Engine                         │
└──────────────────────────────────────────────────────────────┘
```

**Key components**:

1. **Python Layer** (`SpelunkyRLEngine`)
   - Implements Gymnasium interface
   - Manages the game's lifecycle through a launcher
   - Handles socket communication
   - Processes observations and rewards

2. **Lua Layer** (the mod in `mod/lua/`, run by Playlunky inside the game)
   - Extracts game state via overlunky API
   - Receives and executes actions
   - Sends data back to Python

3. **Game Layer** (Spelunky 2)
   - Runs the actual game
   - Modified by Lua scripts in real-time

## Component Architecture

### SpelunkyRLEngine (core.py)

The base class that all environments inherit from. Located in `src/spelunky2rl/engine/core.py`.

#### Key Responsibilities

1. **Process Management**
   - Launch Playlunky and Spelunky 2
   - Monitor game process health
   - Clean shutdown on close

2. **Socket Communication**
   - Create server socket
   - Accept connection from Lua script
   - Send/receive JSON messages

3. **State Management**
   - Track current and previous gamestate
   - Maintain episode state
   - Handle reset logic

4. **Gymnasium Interface**
   - Implement `reset()`, `step()`, `close()`, `render()`
   - Delegate to subclass methods for custom logic

#### Initialization Flow

```python
def __init__(self, game_dir=None, launcher="auto", renderer="auto", **kwargs):
    # 1. Store configuration; kwargs become default reset options (an unknown one is a TypeError)
    self.reset_options = kwargs
    # 2. Pick a launcher: Docker by default (or wine / a Launcher instance)
    self.launcher = make_launcher(launcher, game_dir, renderer=renderer)
    # 3. Launch the game and wait for the mod to connect and say hello
    self._game_init()
```

`_game_init()`:

1. Listens on `127.0.0.1` on a random free port.
2. Inside `launcher.starting()` (which holds the Playlunky cache lock on a first start):
   `launcher.start(port)`, then accepts the connection while polling `launcher.is_running()`.
   If the game dies before connecting it is relaunched, up to `max_launch_attempts`, all within
   `startup_timeout`. Errors include the launcher's recent output.
3. Reads the mod's hello and checks the protocol version (`engine/protocol.py`).
4. If `render_enabled`, asks the launcher for a frame source.

### Launchers (engine/launchers/)

A launcher starts one game instance that connects to the given port, reports whether it is still
running, and tears it down. The port reaches the Lua mod through the `Spelunky_RL_Port` environment
variable, and it is also how a launcher finds *its* `Spel2.exe` among several instances.

| Launcher | Where | How |
|---|---|---|
| `DockerLauncher` | Linux (default) | `docker run --rm --network host` of the game image per env; game mounted at `/game:ro`; `--gpus all` when available |
| `WineLauncher` | Linux, no Docker | host Wine, one Xvfb, instance dir and prefix copy per env (`scripts/setup_wine.sh`) |

Docker and Wine run each instance in a directory assembled over the read-only game folder
(`engine/assemble.py`, `docker/entrypoint.sh`): symlinks to the game files, real copies of the few
files the game writes, Goldberg's `steam_api64.dll`, the ini templates, and a
`Mods/Packs` with only the `spelunky2rl` pack. Playlunky's asset cache (`Mods/Packs/.db`) lives in
`~/.cache/spelunky2rl/playlunky/<image>/<game build>/` and is shared by all instances.

The pack only holds `lua/`: Playlunky writes inside mod folders and hangs on read-only packs that
contain images. `meta.unsafe` scripts (needed for luasocket) always start disabled in Playlunky, so
`docker/fetch_assets.sh` patches one byte of `playlunky64.dll` to run them
(`docker/playlunky-patch.md` says why and how to redo it on a Playlunky bump). Overlunky is not
used: it draws its UI into every frame.

`local.cfg` opens the game as a borderless window filling the Xvfb screen: fullscreen leaves every
frame black under Wine + Xvfb, and a framed window leaves a black band where the title bar would be.
The game draws at the screen's size (`resolutionx/y` do not matter), keeping 16:9 with black bars
otherwise. The engine sets `launcher.screen` before starting it: `render_resolution` when
`render_enabled`, else 160x90: the screen size changes the speed even when the mod skips drawing
the level. The Docker launcher passes it as `SCREEN=WxH`.

### The Lua mod (mod/lua/)

Playlunky runs `main.lua`, which only hooks the modules in `spelunky2rl/` to the game. Reading it
shows everything the mod attaches to:

| Module | Owns | Hooked to |
|---|---|---|
| `protocol.lua` | the socket, the hello, `PROTOCOL_VERSION` and `MOD_VERSION` | connects when the script loads |
| `session.lua` | the last command from Python, the frame countdown, the simulated frames | `ON.POST_UPDATE` |
| `control.lua` | starting a level (warp, themes), start values, destroying entities, game options, the pause flag, skipping the render | `ON.RENDER_PRE_GAME`, `ON.RENDER_PRE_HUD` |
| `input.lua` | the input held for the agent, `manual_control` | `ON.PRE_UPDATE` |
| `observations.lua` | the player's last values, the `win` flag, the fields of the episode; builds the game state and packs it as its layout says | `ON.TRANSITION` |
| `pathfinding.lua` | the floor tile table and the distance field to the nearest exit | spawn and destruction of floor tiles |
| `util.lua` | `round`, `safe` | |

Every module returns a table and keeps its state in locals: the mod defines no globals. A callback
is registered only in `main.lua`. `luasocket/` is the vendored socket library.

**One logic frame** (`session.on_post_update`):

1. The pause flag is cleared, so the game can never sit in the pause menu.
2. The countdown of the current command goes down by one. When it reaches 0 the mod *answers* that
   command, *blocks* until Python sends the next one, and *starts* it:
   - `reset` starts by releasing the input, forgetting the tiles and distances of the previous
     episode (`pathfinding.reset`), closing the journal (the death screen opens it, and an open
     journal keeps the new level paused), warping to the level and applying the game options; it
     is answered 60 frames later, once the level is loaded. Only then are the entities in
     `ent_types_to_destroy` killed and `hp`, `bombs`, `ropes` and `gold` set, right before the state
     is sent.
   - `step` starts by holding the action and is answered `frames` frames later.
   - `close` releases the input, restores the game speed and exits the game. So does a lost connection.
3. With `speedup`, `update_state()` runs `state_updates` more logic frames. Each of them fires
   `ON.POST_UPDATE` again and goes through steps 1 and 2: commands are received and answered inside
   that loop.

**Details that environments rely on**:

- `win` is 1 in exactly one state, the first one sent after the player leaves through the exit.
- While there is no player, `health` is 0 and every other player field keeps its last value; a
  `step` received then does not change the held input.
- The input is written to the game before every logic frame (`ON.PRE_UPDATE`) until the next `step`
  replaces it. `reset` and `close` release it. With `manual_control` the agent's actions are ignored.
- `map_info` is `height` rows (top to bottom) of `width` tile types around the player (21x11 by
  default), 0 where there is no floor tile. `entity_info` has one row
  `[dx, dy, vel_x, vel_y, type, face_left, held type]` per entity whose hitbox touches a view of the
  same kind.
- `dist_to_goal` counts cells from the player's cell to the nearest exit (a level can have several)
  through the ones that are not solid, in 4 directions, as if the player could fly: 0 in the exit's
  cell. Tiles, exits and the player are centred on integer coordinates, so a cell is the rounded
  position, the same one `map_info` is centred on. When the player's cell cannot reach an exit, or
  the level has none, the last valid distance of the episode is sent again (-1 if there has not
  been one). Standing, 0 means within half a cell of the door's centre; the game lets the player in
  from up to ~0.75 cells away (measured over 5 seeds in 1-1), so `== 0` is the built-in envs' success.
- The tile table and the distances are rebuilt before the next state is sent whenever a floor tile
  has appeared or been destroyed, and on every `reset`.

**Changing the mod**: point `SPELUNKY2RL_DEV_MOD` at `src/spelunky2rl/mod/lua` to run your copy
without rebuilding the image, and check it with `tests/integration`. The BFS of `pathfinding.lua`
has unit tests that run with the system's Lua (`tests/unit/test_lua_pathfinding.py`).

### Reset Mechanism

```python
def reset(self, seed=None, options=None, **kwargs):
    # 1. Call parent reset (handles RNG seeding)
    super().reset(seed=seed)

    # 2. Send reset command to Lua; an option _game_reset does not know is a TypeError
    self._game_reset(seed=seed, **(self.reset_options | (options or {}) | kwargs))

    # 3. Receive the layout of this episode's states and the first state
    header, data = self.server.receive()
    self.layout = StateLayout(header["layout"])
    gamestate = self.layout.decode(data)

    # 4. Convert to observation
    observation = self.gamestate_to_observation(gamestate)

    # 5. Store for next step
    self.last_gamestate = gamestate

    return observation, {}
```

The `_game_reset()` method sends configuration to Lua:

```python
def _game_reset(self, seed, speedup, state_updates, hp, bombs, ...):
    self._send_dict({
        "command": "reset",
        "speedup": speedup,
        "state_updates": state_updates,
        "seed": seed,
        "ent_types_to_destroy": ent_types_to_destroy,
        "fields": self.fields,  # data_to_send, resolved by engine/fields.py
        "manual_control": manual_control,
        "god_mode": god_mode,
        "hp": hp,
        "bombs": bombs,
        # ... more options
    })
```

### Step Mechanism

```python
def step(self, action):
    # 1. Convert action to default format (if custom action space)
    action = action.tolist() if not hasattr(self, 'action_to_input') \
             else self.action_to_input(action.tolist())

    # 2. Send action to Lua
    self._send_dict({
        "command": "step",
        "input": action,
        "frames": self.frames_per_step,
    })

    # 3. Receive updated gamestate (same layout as the reset's)
    _, data = self.server.receive()
    gamestate = self.layout.decode(data)

    # 4. Calculate reward (delegated to subclass)
    reward, done, truncated, info = self.reward_function(
        gamestate, self.last_gamestate, action, info
    )

    # 5. Check automatic termination conditions
    done = done or (gamestate["basic_info"]["health"] <= 0 or
                    gamestate["basic_info"]["win"] == 1)

    # 6. Convert to observation
    observation = self.gamestate_to_observation(gamestate)

    # 7. Store for next step
    self.last_gamestate = gamestate

    return observation, reward, done, truncated, info
```

## Communication Protocol

### Message Format

One TCP connection on 127.0.0.1. Python sends one JSON object per line. The mod answers every line
with a JSON **header** line; when the header has `"state": n`, the game state follows it as `n`
bytes, packed in binary.

**Python → Lua**:
```json
{
    "command": "step",
    "input": [1, 1, 0, 0, 0, 0, 1, 0],
    "frames": 6
}
```

**Lua → Python**: `{"state": 1352}` and 1352 bytes, which `StateLayout` reads into the gamestate dict:

```python
{
    "basic_info": {"x": 20.3, "y": 100.05, "health": 4, "can_jump": True, "time": 360, "win": 0, ...},
    "map_info": np.array(..., dtype=np.int32),       # shape (11, 21)
    "entity_info": np.array(..., dtype=np.float64),  # shape (entities, 7)
    "dist_to_goal": 42,
}
```

### Game states in binary

The answer to `reset` adds the **layout** of the states of that episode: one entry per field, in the
order of the bytes. Every value is little-endian, with no padding.

```json
{
    "state": 1352,
    "layout": [
        {"name": "basic_info", "record": [["x", "<f8"], ["y", "<f8"], ["health", "<i4"],
                                          ["face_left", "?"], ["powerups", "u1", 18], ...]},
        {"name": "map_info", "dtype": "<i4", "shape": [11, 21]},
        {"name": "entity_info", "dtype": "<f8", "shape": [-1, 7]},
        {"name": "dist_to_goal", "dtype": "<i4", "shape": []}
    ]
}
```

- `record`: a dict of Python values (`float`, `int`, `bool`; a list where there is a count).
  `basic_info` always comes first.
- `shape: []`: one Python value.
- Any other shape: a numpy array. A `-1` is the number of rows, sent as a `uint32` before them.

The dtypes are numpy's, so Python reads each field with `numpy.frombuffer`; the mod packs them with
`string.pack` (`observations.lua`, where the layout is defined). Floats are float64, the same values
the mod has. A state whose length does not match its layout is a `ProtocolError`.

Why binary: written as JSON, every number is formatted in Lua and parsed back in Python, which
dominated the exchange for big views (161x121 map and entities: ~3 ms per step in JSON, ~0.35 ms
in binary).

### Fields and parameters

`data_to_send` names the fields beyond `basic_info`, as a list or with parameters:

```python
data_to_send = ["map_info", "dist_to_goal"]
data_to_send = {"map_info": {"width": 41, "height": 21}, "entity_info": {}}
```

`engine/fields.py` holds every field with its parameters and defaults, and checks them when the env
is created (a wrong name or value is a `ValueError` before the game starts). `map_info` and
`entity_info` take `width` and `height`: odd sizes, centred on the player, 21x11 by default.
The fields go to the mod in the reset message and hold for the whole episode.

### Connection and handshake

`engine/protocol.py` holds the framing: buffered reads, a per-step timeout (`step_timeout`, raises
`TimeoutError`), `ConnectionError` on EOF and `RuntimeError` for `{"error": ...}` headers from Lua,
which can come instead of any answer.

Right after connecting, the mod sends:

```json
{"hello": {"protocol": 2, "mod": "0.1.2"}}
```

Python compares `protocol` with `PROTOCOL_VERSION` and fails with a message naming the image to
use if they differ. Bump both constants (`engine/protocol.py` and `mod/lua/spelunky2rl/protocol.lua`) whenever a message
changes shape; the image tag always equals the package version.

### Command Types

**1. Reset Command**

```json
{
    "command": "reset",
    "seed": 12345,
    "speedup": true,
    "state_updates": 200,
    "ent_types_to_destroy": [219, 220, 221],
    "fields": [{"name": "map_info", "width": 21, "height": 11}, {"name": "dist_to_goal"}],
    "manual_control": false,
    "god_mode": false,
    "hp": 4,
    "bombs": 4,
    "ropes": 4,
    "gold": 0,
    "world": 1,
    "level": 1
}
```

An optional `"theme"` (overlunky `THEME` id) overrides the default theme for `world`/`level`.

The Lua script responds with the layout and the initial gamestate.

**2. Step Command**

```json
{
    "command": "step",
    "input": [1, 1, 0, 1, 0, 0, 1, 0],
    "frames": 6
}
```

The Lua script:
1. Applies the input for the specified number of frames
2. Collects the fields of the last reset
3. Responds with the packed gamestate

**3. Close Command**

```json
{
    "command": "close"
}
```

Signals the Lua script to clean up (though process is also terminated).

## Lifecycle Management

### Startup Sequence

1. **Python listens** on a random port on 127.0.0.1
2. **The launcher starts the game** with `Spelunky_RL_Port=<port>` in its environment
   (Docker: `docker run`; the entrypoint assembles the instance dir, starts Xvfb and Playlunky)
3. **Playlunky injects itself** and loads the `spelunky2rl` pack
4. **Playlunky runs `main.lua`**, which reads the port and connects
5. **The mod sends its hello**; Python checks the protocol version
6. From here on, every command from Python gets one gamestate back

### Shutdown Sequence

`close()` is idempotent and also registered with `atexit`:

1. Sends `{"command": "close"}` (the mod releases input, resets the speedhack and exits the game)
2. Closes the sockets and the frame source
3. `launcher.stop()`: kills the container / the game, Wine server and Xvfb of this instance

If Python dies without closing, the mod sees the connection drop and exits the game itself, and
the container goes with it (`--rm`).

## Data Flow

### Observation Pipeline

```
Lua Gamestate → Python gamestate dict → gamestate_to_observation() → Gymnasium observation
```

**Example**:

```python
# Python reads from the mod:
{
    "basic_info": {"char_state": 12, "can_jump": True, ...},
    "map_info": np.array([[0, 0, 1, ...], ...], dtype=np.int32)
}

# gamestate_to_observation() converts to:
{
    "char_state": np.int64(12),
    "can_jump": np.int64(1),
    "map_info": np.array([[0, 0, 1, ...], ...], dtype=np.int32)
}
```

### Action Pipeline

```
Agent action → action_to_input() → Default format → Lua → Spelunky 2 inputs
```

**Example**:

```python
# Agent outputs (custom action space):
[2, 1, 1]  # [right, no vertical, jump]

# action_to_input() converts to default format:
[2, 1, 1, 0, 0, 0, 1, 0]  # [right, no vertical, jump, no whip, no bomb, no rope, run, no door]

# Lua interprets:
# - Move right (2)
# - No vertical movement (1)
# - Jump (1)
# - Run (1)
```

### Reward Pipeline

```
Gamestate + Last Gamestate → reward_function() → (reward, done, truncated, info)
```

The reward function has access to:
- Current state
- Previous state (for computing deltas)
- Action taken
- Info dict to populate

## Performance Considerations

### Frame Skipping

`frames_per_step` controls how many game frames execute per RL step:

```python
env = SpelunkyEnv(frames_per_step=6)  # Default: 6 frames (~10 actions/sec at 60 FPS)
```

**Trade-off**:
- Lower values → More reactive but slower training
- Higher values → Faster training but less precise control

### State Updates (Speedup)

`state_updates` makes each rendered frame carry N extra logic frames:

```python
env.reset(speedup=True, state_updates=200)
```

**How it works** (Lua side): in `ON.POST_UPDATE`, after the protocol work, the mod calls
`update_state()` N times. Each call simulates one logic frame and fires `POST_UPDATE` again, which
runs the protocol for that frame (so steps and replies happen inside the loop); a flag stops those
nested calls from starting their own loop. Earlier versions recursed instead, N levels deep, which
is why high values used to crash.

**Limits**: above ~50 the game is no longer the bottleneck; the per-step exchange with Python is.
Do not combine with `render_enabled=True`: captured frames would skip most of the action.

With `render_enabled=False` the mod also returns `true` from `ON.RENDER_PRE_GAME` and
`ON.RENDER_PRE_HUD`, so the level is not drawn at all (+~20 % steps/s without `state_updates`).

### Speedup Flag

`speedup=True` makes the game run faster than real time (a 100x speedhack on the game's clock):

```python
env.reset(speedup=True)
```

Allows the game to run as fast as the CPU permits.

### Data Optimization

Only request data you need in `data_to_send`, with the smallest view that works (the cost of
`map_info` and `entity_info` grows with `width` x `height`):

```python
# Minimal (fastest)
data_to_send = ["map_info"]

# Medium
data_to_send = ["map_info", "dist_to_goal"]

# Maximum (slowest)
data_to_send = ["map_info", "dist_to_goal", "entity_info"]
```

**Cost**:
- `map_info`: Low (always computed)
- `dist_to_goal`: Medium (pathfinding calculation)
- `entity_info`: High (iterates all nearby entities)

### Render Mode

Frame grabbing has significant overhead:

```python
# Training (fast)
env = SpelunkyEnv(render_enabled=False)

# Evaluation/recording (slow)
env = SpelunkyEnv(render_enabled=True)
frame = env.render()  # Returns numpy array
```

**Frame sources** (`engine/frames/`), created by the launcher only when `render_enabled=True`:

- `X11FrameSource` (Docker, Wine): grabs the instance's Xvfb display with `mss`. With host networking
  the container's X server is reachable from the host as display `:<port>`.

## Error Handling

### Lua Errors

`session.on_post_update` runs inside `xpcall`. When anything in it fails, the mod sends the error
with its traceback and exits the game; Python raises it from the `reset()` or `step()` that was
waiting:

```python
# Lua sends:
{"error": "Mods/Packs/spelunky2rl/lua/spelunky2rl/session.lua:59: probe\nstack traceback:\n\t..."}

# Python raises:
RuntimeError: Mods/Packs/spelunky2rl/lua/spelunky2rl/session.lua:59: probe
stack traceback:
	...
```

The environment cannot be used after that; create a new one. Errors in the other callbacks
(`ON.PRE_UPDATE`, `ON.TRANSITION`, the render hooks) are not caught and only reach the game's log.

### Connection Errors

A dropped connection raises `ConnectionError`; a game that stops answering raises `TimeoutError`
after `step_timeout` seconds instead of blocking forever.

### Process Crashes

During startup the game is relaunched up to `max_launch_attempts` times. After startup a crashed
game shows up as a `ConnectionError` on the next step; create a new environment to continue.

## Logging

Optional logging for debugging:

```python
env = SpelunkyEnv(
    log_file="debug.txt",
    log_info=["all", "map_info", "entity_count"]
)
```

**Log implementation**:

```python
def log_step(self, gamestate):
    with open(self.log_file, "a") as f:
        if "all" in self.log_info:
            f.write(f"{timestamp} {str(gamestate)}\n")

        if "map_info" in self.log_info:
            for row in gamestate["map_info"]:
                formatted_row = " ".join(f"{cell:>3}" for cell in row)
                f.write(f"{formatted_row}\n")

        if "entity_count" in self.log_info:
            type_counts = Counter(id2name(e[4])["name"] for e in gamestate["entity_info"])
            f.write(f"Entities: {type_counts}\n")
```

## Dependencies

### Python Dependencies

From `pyproject.toml`:

- **gymnasium**, **numpy**, **psutil**
- **mss**: `render` extra, frame capture on Linux
- **torch**, **stable-baselines3**, **sb3-contrib**: `train` extra, only for the examples

### System Dependencies

- **Spelunky 2**: your own copy of the game
- Linux: **Docker** (and the NVIDIA Container Toolkit for GPU rendering). The image
  (`docker/Dockerfile`) contains Wine, DXVK, Xvfb, Playlunky (patched) and the Goldberg emulator,
  pinned in `docker/versions.env`.
- Windows: not supported yet

## Next Steps

- **[Getting Started](getting-started.md)** - Installation and basic usage
- **[Environments Guide](environments.md)** - Create custom environments
- **Lua mod** - Located in `src/spelunky2rl/mod/lua/`; see [The Lua mod](#the-lua-mod-modlua)
