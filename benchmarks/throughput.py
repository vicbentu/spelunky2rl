"""How many steps per second N games give, what each costs the machine, and where a step's time goes.

Each game runs in its own process, as in training, with the environment the experiments use: frames
of 128x72 from render() as the observation, `dist_to_goal` in the state, no bombs, an episode cut at
90 s of game time, random actions. Two commands:

    # steps/s for 1, 5 and 10 games on the GPU and on the CPU, stepping freely and in lockstep
    python benchmarks/throughput.py scale --envs 1 5 10 --renderer gpu cpu

    # one hour of 5 games in lockstep, a line every 40,000 steps of each: is a step getting slower?
    python benchmarks/throughput.py drift --envs 5 --seconds 3600

With few games on the GPU the driver lowers its clocks (P5-P8) and a step takes up to twice as long:
the `gpu` column says which state it was in.

Modes (`--mode`):
- free: each game steps as fast as it can, on its own. What the games can give.
- lockstep: every game steps, then the next step starts, and an ended episode is reset inside the
  step that ended it, so every game waits for the slowest and for each reset. What a training loop
  like `gymnasium.vector.AsyncVectorEnv` or the experiments' VecEnv gets.

Per step, each game's time is split into:
- send: the action to the mod (Python side only).
- game: until the state arrives: the mod runs the logic frames, the game draws the last one, the mod
  reads the state.
- frame: until render() has the frame of that state (the capture's wait and copy).
- python: the rest of step() in Python (decoding, reward).
Resets are timed apart. In lockstep, `wait` is what a game waits for the others each step.

Resources, sampled during the measured window: CPU (cores) and memory of each game's container,
VRAM of each game process, and the GPU's clocks.

Results go to stdout as a table and, one JSON line per configuration, to --out.
"""

import argparse
import json
import multiprocessing as mp
import os
import subprocess
import sys
import time
import traceback
from typing import Dict, List, Optional

import numpy as np

WIDTH, HEIGHT = 128, 72
TIME_LIMIT = 60 * 90  # game frames


def make_env(renderer: str, resolution, cpu_threads: Optional[int], container_env: List[str],
             image: Optional[str] = None, **kwargs):
    import gymnasium as gym

    from spelunky2rl import SpelunkyRLEngine

    class PixelEnv(SpelunkyRLEngine):
        """The experiments' PixelGetToExit without bombs: the frame is the observation."""

        observation_space = gym.spaces.Box(0, 255, (resolution[1], resolution[0], 3), np.uint8)
        reset_options = {"ent_types_to_destroy": (), "bombs": 0}
        data_to_send = ["dist_to_goal"]

        def reward_function(self, gamestate, last_gamestate, action, info):
            done = gamestate["dist_to_goal"] == 0
            truncated = not done and gamestate["basic_info"]["time"] >= TIME_LIMIT
            return 0.0, done, truncated, info

        def gamestate_to_observation(self, gamestate):
            return self.render()

    options = {"extra_args": [arg for kv in container_env for arg in ("-e", kv)]}
    if image:
        options["image"] = image
    return PixelEnv(render_mode="rgb_array", render_resolution=tuple(resolution), renderer=renderer,
                    cpu_threads=cpu_threads, launcher_options=options, **kwargs)


class Timers:
    """Seconds spent in each part of step() and in reset(), since the last take()."""

    PARTS = ("send", "game", "frame")

    def __init__(self, env):
        self.t = dict.fromkeys(self.PARTS + ("step", "reset"), 0.0)
        self.steps = self.resets = 0
        self.max_step = 0.0
        self.server = None
        self.attach(env)

    def attach(self, env) -> None:
        """Time the game's connection and frames; again when restart_every switched to a new game."""
        if env.server is self.server:
            return
        self.server = env.server
        for part, obj, name in (("send", env.server, "send"), ("game", env.server, "receive"),
                                ("frame", env.frame_source, "get_frame")):
            setattr(obj, name, self._timed(part, getattr(obj, name)))

    def _timed(self, part, f):
        def timed(*args, **kwargs):
            start = time.perf_counter()
            try:
                return f(*args, **kwargs)
            finally:
                self.t[part] += time.perf_counter() - start
        return timed

    def take(self) -> Dict:
        out = {"steps": self.steps, "resets": self.resets, "max_step_s": self.max_step, **self.t}
        self.t = dict.fromkeys(self.t, 0.0)
        self.steps = self.resets = 0
        self.max_step = 0.0
        return out


def game_pid(container: str) -> Optional[int]:
    """Spel2.exe's pid (host namespace) in that container."""
    out = subprocess.run(["docker", "top", container, "-o", "pid,comm"], capture_output=True, text=True).stdout
    for line in out.splitlines()[1:]:
        pid, _, comm = line.strip().partition(" ")
        if comm.strip().startswith("Spel2"):
            return int(pid)
    return None


def worker(index: int, args, conn) -> None:
    """One game. Answers the parent's commands on `conn` until "close"."""
    rng = np.random.default_rng(index)
    try:
        start = time.perf_counter()
        kwargs = {"restart_every": args.restart_every}
        if args.gpu_memory_mb is not None:
            kwargs["gpu_memory_mb"] = None if args.gpu_memory_mb == 0 else args.gpu_memory_mb
        env = make_env(args.renderer_now, args.resolution, args.cpu_threads, args.container_env, args.image, **kwargs)
        env.reset(seed=args.level_seed)
        startup = time.perf_counter() - start
    except Exception:
        conn.send({"error": traceback.format_exc()})
        return
    timers = Timers(env)
    container, pid = env.launcher.container, game_pid(env.launcher.container)
    conn.send({"ready": startup, "container": container, "pid": pid})

    def one_step():
        start = time.perf_counter()
        _, _, done, truncated, _ = env.step(rng.integers(env.action_space.nvec))
        elapsed = time.perf_counter() - start
        timers.t["step"] += elapsed
        timers.max_step = max(timers.max_step, elapsed)
        timers.steps += 1
        if done or truncated or (args.episode_steps and env.steps_in_episode >= args.episode_steps):
            start = time.perf_counter()
            env.reset(seed=args.level_seed)
            timers.t["reset"] += time.perf_counter() - start
            timers.resets += 1
            timers.attach(env)
            env.steps_in_episode = 0
        else:
            env.steps_in_episode += 1

    env.steps_in_episode = 0
    try:
        while True:
            cmd, value = conn.recv()
            if cmd == "step":
                one_step()
                conn.send(None)
            elif cmd == "free":  # step on our own until this time.monotonic()
                while time.monotonic() < value:
                    one_step()
                conn.send(timers.take())
            elif cmd == "take":
                stats = timers.take()
                if env.launcher.container != container:  # restart_every switched to a new game
                    container = env.launcher.container
                    pid = game_pid(container)
                stats.update(container=container, pid=pid)
                conn.send(stats)
            elif cmd == "close":
                break
    finally:
        env.close()


class Sampler:
    """Resources of the games' containers and processes, sampled every `period` seconds."""

    def __init__(self, containers: List[str], pids: List[Optional[int]]):
        self.samples = []
        self.containers = []
        self.follow(containers, pids)

    def follow(self, containers: List[str], pids: List[Optional[int]]) -> None:
        """The games now running (restart_every replaces them)."""
        if containers != self.containers:
            self.cgroups = []
            for name in containers:
                cid = subprocess.run(["docker", "inspect", "-f", "{{.Id}}", name], capture_output=True,
                                     text=True).stdout.strip()
                path = f"/sys/fs/cgroup/system.slice/docker-{cid}.scope"
                self.cgroups.append(path if cid and os.path.isdir(path) else None)
            self.containers = list(containers)
        self.pids = pids

    def _cpu_usec(self, cgroup):
        try:
            with open(f"{cgroup}/cpu.stat") as f:
                return int(f.readline().split()[1])
        except OSError:  # that game is gone
            return None

    def _mem(self, cgroup):
        try:
            with open(f"{cgroup}/memory.current") as f:
                return int(f.read())
        except OSError:
            return None

    def sample(self):
        now = time.monotonic()
        cpu = [self._cpu_usec(c) if c else None for c in self.cgroups]
        mem = [self._mem(c) if c else None for c in self.cgroups]
        vram = {}
        out = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True).stdout if has_nvidia() else ""
        for line in out.splitlines():
            pid, _, used = line.partition(",")
            vram[int(pid)] = int(used)
        gpu = gpu_state()
        rss = []
        for pid in self.pids:
            try:
                with open(f"/proc/{pid}/status") as f:
                    rss.append(next(int(line.split()[1]) for line in f if line.startswith("RssAnon")) // 1024)
            except (OSError, TypeError, StopIteration):
                rss.append(None)
        self.samples.append({"t": now, "cpu": cpu, "mem": mem, "rss_anon_mb": rss,
                             "vram_mb": [vram.get(pid) for pid in self.pids], "gpu": gpu})

    def summary(self) -> Dict:
        if len(self.samples) < 2:
            return {}
        first, last = self.samples[0], self.samples[-1]
        span = last["t"] - first["t"]
        cores = [(b - a) / 1e6 / span if a is not None and b is not None else None
                 for a, b in zip(first["cpu"], last["cpu"])]
        def mean(xs):
            xs = [x for x in xs if x is not None]
            return round(float(np.mean(xs)), 2) if xs else None
        return {
            "cpu_cores_per_game": mean(cores),
            "cpu_cores_total": round(sum(c for c in cores if c is not None), 1),
            "container_mem_gb_per_game": mean([m / 2**30 for m in last["mem"] if m is not None]),
            "game_rss_anon_mb_per_game": mean(last["rss_anon_mb"]),
            "vram_gb_per_game": mean([v / 1024 for v in last["vram_mb"] if v is not None]),
            "gpu": [s["gpu"] for s in self.samples[-3:]],
        }


_nvidia = None


def has_nvidia() -> bool:
    global _nvidia
    if _nvidia is None:
        _nvidia = subprocess.run(["which", "nvidia-smi"], capture_output=True).returncode == 0
    return _nvidia


def gpu_state() -> Optional[str]:
    if not has_nvidia():
        return None
    return subprocess.run(["nvidia-smi", "--query-gpu=pstate,clocks.sm,clocks.mem,utilization.gpu,memory.used",
                           "--format=csv,noheader"], capture_output=True, text=True).stdout.strip()


def start_games(args, n: int):
    ctx = mp.get_context("spawn")
    conns, procs = [], []
    for i in range(n):
        parent, child = ctx.Pipe()
        proc = ctx.Process(target=worker, args=(i, args, child), daemon=True)
        proc.start()
        conns.append(parent)
        procs.append(proc)
    ready = [conn.recv() for conn in conns]
    return conns, procs, ready


def close_games(conns, procs):
    for conn in conns:
        try:
            conn.send(("close", None))
        except (BrokenPipeError, OSError):
            pass
    for proc in procs:
        proc.join(timeout=60)
        if proc.is_alive():
            proc.terminate()


def per_step(stats: List[Dict]) -> Dict:
    """Mean ms per step of each part, over every game."""
    steps = sum(s["steps"] for s in stats)
    resets = sum(s["resets"] for s in stats)
    out = {f"{part}_ms": round(1000 * sum(s[part] for s in stats) / steps, 3) for part in Timers.PARTS + ("step",)}
    out["python_ms"] = round(out["step_ms"] - out["send_ms"] - out["game_ms"] - out["frame_ms"], 3)
    out["reset_ms"] = round(1000 * sum(s["reset"] for s in stats) / resets, 1) if resets else None
    out["resets"] = resets
    out["max_step_ms"] = round(1000 * max(s["max_step_s"] for s in stats), 1)
    return out


def measure_free(conns, sampler, args) -> Dict:
    for conn in conns:
        conn.send(("free", time.monotonic() + args.warmup))
    for conn in conns:
        conn.recv()
    end = time.monotonic() + args.seconds
    start = time.perf_counter()
    for conn in conns:
        conn.send(("free", end))
    sampler.sample()
    while time.monotonic() < end - 1:
        time.sleep(min(args.sample_every, max(0.0, end - 1 - time.monotonic())))
        sampler.sample()
    stats = [conn.recv() for conn in conns]
    elapsed = time.perf_counter() - start
    steps = sum(s["steps"] for s in stats)
    return {"steps_per_s": round(steps / elapsed), "per_game": [round(s["steps"] / elapsed) for s in stats],
            **per_step(stats)}


def lockstep(conns, seconds: float, sampler=None, sample_every: float = 2.0):
    """Step every game together for `seconds`: (lockstep steps, elapsed s)."""
    n, start = 0, time.perf_counter()
    end = time.monotonic() + seconds
    next_sample = time.monotonic() + sample_every
    while time.monotonic() < end:
        for conn in conns:
            conn.send(("step", None))
        for conn in conns:
            conn.recv()
        n += 1
        if sampler is not None and time.monotonic() >= next_sample:
            sampler.sample()
            next_sample = time.monotonic() + sample_every
    return n, time.perf_counter() - start


def take(conns) -> List[Dict]:
    for conn in conns:
        conn.send(("take", None))
    return [conn.recv() for conn in conns]


def measure_lockstep(conns, sampler, args) -> Dict:
    lockstep(conns, args.warmup)
    take(conns)
    sampler.sample()
    n, elapsed = lockstep(conns, args.seconds, sampler, args.sample_every)
    stats = take(conns)
    out = {"steps_per_s": round(n * len(conns) / elapsed), "per_game": round(n / elapsed), **per_step(stats)}
    out["wait_ms"] = round(1000 * elapsed / n - out["step_ms"], 3)
    return out


def cmd_scale(args) -> None:
    out = open(args.out, "a") if args.out else None
    rows = []
    for renderer in args.renderer:
        for n in args.envs:
            args.renderer_now = renderer
            start = time.perf_counter()
            conns, procs, ready = start_games(args, n)
            errors = [r["error"] for r in ready if "error" in r]
            config = {"renderer": renderer, "envs": n, "resolution": args.resolution, "cpu_threads": args.cpu_threads,
                      "container_env": args.container_env, "episode_steps": args.episode_steps,
                      "startup_s": round(time.perf_counter() - start, 1),
                      "startup_s_per_game": [round(r["ready"], 1) for r in ready if "ready" in r]}
            if errors:
                print(f"{renderer} x{n}: {len(errors)} games failed to start:\n{errors[0]}", file=sys.stderr)
                close_games(conns, procs)
                record = {**config, "failed": len(errors), "error": errors[0][-2000:]}
                rows.append(record)
                if out:
                    out.write(json.dumps(record) + "\n")
                    out.flush()
                continue
            containers = [r["container"] for r in ready]
            for mode in args.mode:
                sampler = Sampler(containers, [r["pid"] for r in ready])
                result = (measure_free if mode == "free" else measure_lockstep)(conns, sampler, args)
                record = {**config, "mode": mode, **result, **sampler.summary()}
                rows.append(record)
                print(json.dumps(record), flush=True)
                if out:
                    out.write(json.dumps(record) + "\n")
                    out.flush()
            close_games(conns, procs)
    print_table(rows)


def print_table(rows: List[Dict]) -> None:
    cols = ["renderer", "envs", "mode", "steps_per_s", "step_ms", "game_ms", "frame_ms", "python_ms", "wait_ms",
            "reset_ms", "cpu_cores_per_game", "container_mem_gb_per_game", "vram_gb_per_game"]
    print("\n| " + " | ".join(cols) + " |")
    print("|" + "---|" * len(cols))
    for r in rows:
        print("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")


def cmd_drift(args) -> None:
    """Games in lockstep for a long time; a line every --window steps per game."""
    args.renderer_now = args.renderer[0]
    n = args.envs[0]
    conns, procs, ready = start_games(args, n)
    errors = [r["error"] for r in ready if "error" in r]
    if errors:
        close_games(conns, procs)
        raise SystemExit(errors[0])
    sampler = Sampler([r["container"] for r in ready], [r["pid"] for r in ready])
    out = open(args.out, "a") if args.out else None
    start = time.monotonic()
    total = 0
    take(conns)
    while time.monotonic() - start < args.seconds:
        t0 = time.perf_counter()
        steps = 0
        while steps < args.window:
            for conn in conns:
                conn.send(("step", None))
            for conn in conns:
                conn.recv()
            steps += 1
        elapsed = time.perf_counter() - t0
        total += steps
        stats = take(conns)
        sampler.follow([s["container"] for s in stats], [s["pid"] for s in stats])
        sampler.samples = []
        sampler.sample()
        last = sampler.samples[-1]
        record = {"steps_per_game": total, "minutes": round((time.monotonic() - start) / 60, 1),
                  "lockstep_ms": round(1000 * elapsed / steps, 3), **per_step(stats),
                  "container_mem_gb": [round(m / 2**30, 3) for m in last["mem"] if m is not None],
                  "game_rss_anon_mb": last["rss_anon_mb"], "gpu": last["gpu"]}
        print(json.dumps(record), flush=True)
        if out:
            out.write(json.dumps(record) + "\n")
            out.flush()
    close_games(conns, procs)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("scale", "drift"):
        s = sub.add_parser(name)
        s.add_argument("--envs", type=int, nargs="+", default=[1, 5, 10] if name == "scale" else [5])
        s.add_argument("--renderer", nargs="+", default=["gpu"], choices=["gpu", "cpu"])
        s.add_argument("--resolution", type=int, nargs=2, default=[WIDTH, HEIGHT], metavar=("W", "H"))
        s.add_argument("--cpu-threads", type=int, default=None, help="lavapipe threads per game (renderer cpu)")
        s.add_argument("--container-env", action="append", default=[], metavar="KEY=VALUE",
                       help="an environment variable for every game's container, e.g. DXVK_CONFIG=...")
        s.add_argument("--gpu-memory-mb", type=int, default=None,
                       help="VRAM per game (default: the library's; 0: no limit)")
        s.add_argument("--restart-every", type=int, default=None, help="the engine's restart_every")
        s.add_argument("--image", default=None, help="the game image (default: the one of this package)")
        s.add_argument("--level-seed", type=int, default=1036, help="every episode plays this level")
        s.add_argument("--episode-steps", type=int, default=0,
                       help="cut each episode after this many steps (0: only at the exit, death or 90 s)")
        s.add_argument("--out", default=None, help="append one JSON line per result to this file")
        s.add_argument("--sample-every", type=float, default=2.0)
        if name == "scale":
            s.add_argument("--mode", nargs="+", default=["free", "lockstep"], choices=["free", "lockstep"])
            s.add_argument("--warmup", type=float, default=10.0)
            s.add_argument("--seconds", type=float, default=30.0)
        else:
            s.add_argument("--seconds", type=float, default=3600.0)
            s.add_argument("--window", type=int, default=40000, help="lockstep steps per line")
    args = p.parse_args(argv)
    if args.command == "scale":
        cmd_scale(args)
    else:
        cmd_drift(args)


if __name__ == "__main__":
    main()
