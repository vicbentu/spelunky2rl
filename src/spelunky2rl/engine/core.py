import atexit
import inspect
import socket
import time
import warnings
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

import gymnasium as gym
import numpy as np

from ..tools.id2name import id2name
from .frames import FrameSource
from .launchers import Launcher, make_launcher
from .fields import resolve_fields
from .protocol import Connection, StateLayout, check_hello

HELLO_TIMEOUT = 15.0  # the mod says hello right after connecting
# The screen size changes the speed even when the mod skips drawing the level (with lavapipe,
# 640x360 -> 160x90 is ~20 % more steps/s); at 16x9 the game does not start
HIDDEN_SCREEN = (160, 90)
MIN_RENDER_RESOLUTION = (64, 36)
GAME_FPS = 60  # logic frames per second of game time

# Extra logic frames the mod runs per real frame with speedup and no render. A step is the same game
# time with any value; past ~200 the exchange with Python (~0.6 ms per step) is the limit
STATE_UPDATES = 200
REMOVED_STATE_UPDATES = ("state_updates was removed: the engine sets it (speedup=True, the default, "
                         "already runs as fast as the machine allows). Drop the argument.")


def check_render_resolution(resolution) -> Tuple[int, int]:
    try:
        width, height = (int(n) for n in resolution)
    except (TypeError, ValueError):
        raise ValueError(f"render_resolution must be (width, height), got {resolution!r}") from None
    if width < MIN_RENDER_RESOLUTION[0] or height < MIN_RENDER_RESOLUTION[1]:
        raise ValueError(f"render_resolution must be at least 64x36, got {width}x{height}")
    # the game keeps 16:9 and fills the rest of the screen with black bars
    if abs(width * 9 - height * 16) > width * 9 / 100:
        raise ValueError(f"render_resolution must be 16:9 (e.g. 320x180, 1280x720), got {width}x{height}")
    return width, height


class SpelunkyRLEngine(gym.Env):

    ############## GYM interface ##############

    action_space: gym.spaces.MultiDiscrete = gym.spaces.MultiDiscrete([
        3, # Movement X
        3, # Movement Y
        2, # Jump
        2, # Whip
        2, # Bomb
        2, # Rope
        2, # Run
        2, # Door
    ])

    observation_space: gym.spaces.Dict

    def __init__(
            self,
            game_dir: Optional[str] = None,
            frames_per_step: int = 6,
            render_enabled: bool = False,
            render_mode: Optional[str] = None,
            render_resolution: Tuple[int, int] = (640, 360),
            launcher: Union[str, Launcher] = "auto",
            renderer: str = "auto",
            cpu_threads: Optional[int] = None,
            gpu_memory_mb: Optional[int] = 512,
            launcher_options: Optional[Dict[str, Any]] = None,
            log_file: str = None,
            log_info: Optional[List[str]] = None,
            step_timeout: float = 60.0,
            startup_timeout: float = 180.0,
            max_launch_attempts: int = 3,
            spelunky_dir: Optional[str] = None,
            **kwargs
        ) -> None:
        """Starts the game (one instance per environment) and connects to it. Each parameter is
        detailed in docs/getting-started.md (https://github.com/vicbentu/spelunky2rl/blob/main/docs/getting-started.md).

        Args:
            game_dir: Spelunky 2 folder (with Spel2.exe). Defaults to $SPELUNKY2RL_GAME_DIR.
            frames_per_step: game frames (1/60 s each) per step(); the action is held for all of them.
            render_enabled: the same as render_mode="rgb_array".
            render_mode: None, "rgb_array" (render() returns the frame of the last state) or
                "rgb_array_list" (render() returns every frame since the last call, for video).
            render_resolution: (width, height) of the frames, 16:9 and at least 64x36.
            launcher: "auto" (Docker; $SPELUNKY2RL_LAUNCHER changes it), "docker", "wine" or a Launcher.
            renderer: "auto" (GPU if Docker can use one, else CPU), "gpu" or "cpu".
            cpu_threads: threads drawing each frame when the game draws on the CPU; None, one per
                core. Fewer can be faster with several envs and small frames.
            gpu_memory_mb: VRAM each game may use, in MB, when it draws on the GPU: the textures it has
                not drawn lately move to system RAM. None: no limit (~1.75 GB per game).
            launcher_options: extra keyword arguments for the launcher, e.g. {"image": ...}.
            log_file: a file where every state is written, for debugging.
            log_info: what log_file gets: "all", "map_info", "entity_count".
            step_timeout: seconds to wait for the game in reset(), step() and render().
            startup_timeout: seconds for the game to start and connect.
            max_launch_attempts: launches before giving up if the game dies before connecting; also
                how many times in a row reset() starts again a game that stopped answering.
            spelunky_dir: the old name of game_dir.
            **kwargs: default reset options for every episode (see reset()). An unknown one is a
                TypeError.
        """

        super().__init__()

        if "state_updates" in kwargs:
            raise TypeError(REMOVED_STATE_UPDATES)
        known = set(inspect.signature(self._game_reset).parameters) - {"seed"}
        unknown = sorted(set(kwargs) - known)
        if unknown:
            raise TypeError(f"Unknown reset options: {', '.join(unknown)}. Known: {', '.join(sorted(known))}")

        # before launching anything: a wrong field name or parameter fails here
        self.fields = resolve_fields(getattr(self, "data_to_send", []))
        self.layout: Optional[StateLayout] = None

        self.game_dir = game_dir or spelunky_dir
        self.frames_per_step = frames_per_step
        self.reset_options = getattr(self, "reset_options", {}) | kwargs
        if render_mode not in (None, *self.metadata["render_modes"]):
            raise ValueError(f"render_mode must be None, 'rgb_array' or 'rgb_array_list', got {render_mode!r}")
        self.render_mode = render_mode or ("rgb_array" if render_enabled else None)
        self.render_enabled = self.render_mode is not None
        self._frames: List[np.ndarray] = []  # with "rgb_array_list": the frames render() has not returned
        if self.render_mode == "rgb_array":
            # one frame per step: a video of them at this rate runs at the game's speed (RecordVideo)
            self.metadata = {**self.metadata, "render_fps": GAME_FPS / frames_per_step}
        self.log_file = log_file
        self.log_info = log_info if log_info is not None else ["all"]
        self.step_timeout = step_timeout
        self.startup_timeout = startup_timeout
        self.max_launch_attempts = max_launch_attempts
        self._closed = False
        self.server = None
        self.frame_source: Optional[FrameSource] = None

        self.render_resolution = check_render_resolution(render_resolution)
        self.launcher = make_launcher(launcher, self.game_dir, renderer=renderer, options=launcher_options,
                                      cpu_threads=cpu_threads, gpu_memory_mb=gpu_memory_mb)
        self.launcher.screen = self.render_resolution if self.render_enabled else HIDDEN_SCREEN
        self.launcher.capture = self.render_enabled
        self.launcher.capture_frames = frames_per_step if self.render_mode == "rgb_array_list" else 1
        self._drawn: Optional[int] = None  # frames drawn when the last state was sent
        self._game_init()


    # TODO: items, powerups
    def reset(
        self,
        *,
        seed: Optional[int] = None,
        options: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Tuple[Dict, Dict[str, Any]]:
        """Starts a new episode on a new level. `seed` picks the level (random if None).

        Reset options, for this episode: as keyword arguments or in `options` (the gymnasium way).
        They override the ones given to __init__, which override the environment's defaults
        (`reset_options`); an unknown one is a TypeError. Defaults in parentheses.

            speedup (True): run as fast as the machine allows; False plays in real time (60 FPS).
            ent_types_to_destroy (()): ENT_TYPE ids killed when the level starts.
            manual_control (False): the agent's actions are ignored and the game reads the keyboard.
            god_mode (False): the player cannot die.
            hp (4), bombs (4), ropes (4), gold (0): the player's starting values.
            world (1), level (1): where the episode starts.
            theme (None): an Overlunky THEME id; None is the usual theme of world and level.
            time_ghost (True): the ghost that appears after 3 minutes (it slows the game ~8x).
            audio (False): the game's sound.
        """

        super().reset(seed=seed)
        reset_options = self.reset_options | (options or {}) | kwargs
        if "state_updates" in reset_options:
            raise TypeError(REMOVED_STATE_UPDATES)
        if seed is None:
            seed = int(self.np_random.integers(0, 2**32))

        # A game that stopped answering (hung, or gone: after a failed step() too) is started again
        # and the reset sent to the new one, up to max_launch_attempts times
        for attempt in range(1, self.max_launch_attempts + 1):
            try:
                return self._reset_game(seed, reset_options)
            except (TimeoutError, ConnectionError) as error:
                if attempt == self.max_launch_attempts:
                    raise
                self._restart_game(error)

    def _reset_game(self, seed: int, reset_options: Dict[str, Any]) -> Tuple[Dict, Dict[str, Any]]:
        self._game_reset(seed=seed, **reset_options)

        header, data = self.server.receive()
        self._drawn = header["drawn"]
        if self.render_mode == "rgb_array_list":
            # the frames of the level's start are not the episode's: only the state's
            self._frames = [self.frame_source.get_frame(self._drawn)]
        self.layout = StateLayout(header["layout"])
        gamestate = self.layout.decode(data)
        self.last_gamestate = gamestate
        observation = self.gamestate_to_observation(gamestate)
        return observation, {}


    def step(
        self, action: Any
    ) -> Tuple[Dict, float, bool, bool, Dict[str, Any]]:

        action = np.asarray(action).tolist()
        if hasattr(self, 'action_to_input'):
            action = self.action_to_input(action)
        self._send_dict({
            "command": "step",
            "input": action,
            "frames": self.frames_per_step,
        })

        header, data = self.server.receive()
        if self.render_mode == "rgb_array_list":
            # read now: the capture keeps only the frames of one step
            self._frames += self.frame_source.get_frames(self._drawn + 1, header["drawn"])
        self._drawn = header["drawn"]
        gamestate = self.layout.decode(data)

        info = {
            "success": False
        }

        if self.log_file:
            self.log_step(gamestate)

        reward, done, truncated, info = self.reward_function(gamestate, self.last_gamestate, action, info)
        done = done or bool(gamestate["basic_info"]["health"] <= 0 or gamestate["basic_info"]["win"] == 1)
        self.last_gamestate = gamestate
        observation = self.gamestate_to_observation(gamestate)

        return observation, reward, done, truncated, info



    ############ Spelunky  Communicaton ############

    def close(self):
        if getattr(self, "_closed", True):
            return
        self._closed = True
        atexit.unregister(self.close)

        if self.server is not None:
            try:
                self._send_dict({"command": "close"})
            except OSError:
                pass
            self.server.close()
        if getattr(self, "server_socket", None) is not None:
            self.server_socket.close()
        if self.frame_source is not None:
            self.frame_source.close()
        if getattr(self, "launcher", None) is not None:
            self.launcher.stop()

    def _game_init(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.bind(('127.0.0.1', 0))
        self.server_socket.listen(1)
        self.server_socket.settimeout(0.05)
        atexit.register(self.close)

        try:
            self.server, self.mod_version, self.frame_source = self._start_game()
        except BaseException:
            self.close()
            raise
        if self.render_mode == "rgb_array_list" and not self.frame_source.counts_frames:
            self.close()
            raise ValueError(f"render_mode='rgb_array_list' needs the Docker launcher: "
                             f"{type(self.launcher).__name__} cannot tell the frames of a step apart")

    def _start_game(self) -> Tuple[Connection, Optional[str], Optional[FrameSource]]:
        """Launch the game, wait for its mod's hello and, with render, open its frames: (connection,
        mod version, frame source)."""
        with self.launcher.starting(self.startup_timeout):
            server = self._launch_and_accept()
            try:
                hello = check_hello(server.receive(timeout=HELLO_TIMEOUT)[0])
            except BaseException:
                server.close()
                raise
        frame_source = self.launcher.frame_source(self.step_timeout) if self.render_enabled else None
        return server, hello.get("mod"), frame_source

    def _restart_game(self, error: BaseException) -> None:
        """Stop this game and start a new one in its place (for a reset: no state survives)."""
        warnings.warn(f"spelunky2rl: the game stopped answering ({error}); starting it again"
                      + self._diagnostics(), RuntimeWarning, stacklevel=3)
        self.server.close()
        if self.frame_source is not None:
            self.frame_source.close()
        self.launcher.stop()
        self.server, self.mod_version, self.frame_source = self._start_game()

    def _launch_and_accept(self) -> Connection:
        deadline = time.monotonic() + self.startup_timeout
        port = self.server_socket.getsockname()[1]
        for _ in range(self.max_launch_attempts):
            self.launcher.start(port)
            while True:
                try:
                    sock, _ = self.server_socket.accept()
                    return Connection(sock, self.step_timeout)
                except socket.timeout:
                    pass
                if time.monotonic() > deadline:
                    raise TimeoutError(f"Spelunky 2 did not connect within {self.startup_timeout} s"
                                       + self._diagnostics())
                if not self.launcher.is_running():
                    break
            self.launcher.stop()
        raise RuntimeError(f"The game exited {self.max_launch_attempts} times before the mod connected"
                           + self._diagnostics())

    def _diagnostics(self) -> str:
        output = self.launcher.diagnostics()
        return f"\nLauncher output:\n{output}" if output else ""

    def _game_reset(
            self,
            seed:int = None,
            speedup: bool = True,

            ent_types_to_destroy = (),
            manual_control: bool = False,
            god_mode: bool = False,
            hp: int = 4,
            bombs: int = 4,
            ropes: int = 4,
            gold: int = 0,
            world: int = 1,
            level: int = 1,
            theme: Optional[int] = None,
            time_ghost: bool = True,
            audio: bool = False,
        ) -> None:

        message = {
            "command": "reset",
            "speedup": speedup,
            # extra logic frames per real frame only without render: with it the mod runs all of a
            # step but the last frame itself, and the game draws that one
            "state_updates": STATE_UPDATES if speedup and not self.render_enabled else 0,
            "seed": seed,
            "ent_types_to_destroy": list(ent_types_to_destroy),
            "fields": self.fields,
            "manual_control": manual_control,
            "god_mode": god_mode,
            "hp": hp,
            "bombs": bombs,
            "ropes": ropes,
            "gold": gold,
            "world": world,
            "level": level,
            # the ghost that appears after 3 minutes slows the game down about 8x
            "time_ghost": time_ghost,
            "audio": audio,
            "vsync": False,
            # skip drawing when nobody reads the frames
            "render": self.render_enabled,
            # draw every frame of a step, not only the last one
            "render_all": self.render_mode == "rgb_array_list",
        }
        # Lua picks the world's default theme; pass a THEME value to choose e.g. Volcana (3) or Temple (6)
        if theme is not None:
            message["theme"] = theme
        self._send_dict(message)

    def _send_dict(self, payload: Dict[str, Any]) -> None:
        self.server.send(payload)


    ############ Render ############

    # frames per second of what render() returns, so that a video of them runs at the game's speed:
    # every frame with "rgb_array_list"; one per step with "rgb_array" (set in __init__)
    metadata = {"render_modes": ["rgb_array", "rgb_array_list"], "render_fps": GAME_FPS}

    def render(self):
        """With render_mode="rgb_array", the frame of the last state as an (H, W, 3) uint8 RGB array;
        with "rgb_array_list", the list of frames since the last call (or since reset(), whose frame
        is the first)."""
        if self.frame_source is None:
            raise RuntimeError("render() needs render_mode='rgb_array' or 'rgb_array_list' on init")
        if self.render_mode == "rgb_array_list":
            frames, self._frames = self._frames, []
            return frames

        # the frame of the last state: with the Docker launcher the one drawn right before it was sent
        return self.frame_source.get_frame(self._drawn)



    ########### Log ################

    def log_step(self, gamestate):
        with open(self.log_file, "a") as f:
            f.write("----------------------------------\n")
            for field in self.log_info:
                if field == "all":
                    timestamp = datetime.now().strftime("%H:%M:%S:%f")[:-3]
                    f.write(f"-- {timestamp} {str(gamestate)}\n")
                if field == "map_info":
                    f.write(str(gamestate["map_info"]) + "\n")
                    for row in gamestate["map_info"]:
                        formatted_row = " ".join(f"{cell:>3}" for cell in row)
                        f.write(f"{formatted_row}\n")
                elif field == "entity_count":
                    type_counts = Counter(id2name(int(entity[4]))["name"] for entity in gamestate["entity_info"])
                    f.write(f"Entities: {type_counts}\n")
