"""
Performance Benchmark Example

This script benchmarks the performance of SpelunkyRL environments to help you:
- Measure environment FPS (frames per second / steps per second)
- Compare single vs parallel environment performance
- Test different environment configurations
- Identify optimal settings for your hardware

The benchmark tests how many environment steps can be executed per second,
which is crucial for training efficiency in reinforcement learning.

Usage:
    # Test single environment
    python examples/benchmark_performance.py --env dummy

    # Test parallel environments
    python examples/benchmark_performance.py --env get_to_exit --num-envs 2 4 8

    # Longer test with custom duration
    python examples/benchmark_performance.py --env gold_grabber --duration 30

    # Test all configurations
    python examples/benchmark_performance.py --env enemy_killer --num-envs 1 2 4 --duration 20

Available environments:
- dummy: Minimal environment (fastest, for benchmarking)
- get_to_exit: Navigate to level exit
- gold_grabber: Collect gold task
- enemy_killer: Combat-focused task
"""

import time
import argparse
from typing import Tuple
from stable_baselines3.common.vec_env import SubprocVecEnv
from stable_baselines3.common.monitor import Monitor

# Environment imports - add new environments here
ENV_CLASSES = {
    'dummy': 'spelunky2rl.envs.dummy_environment',
    'get_to_exit': 'spelunky2rl.envs.get_to_exit',
    'gold_grabber': 'spelunky2rl.envs.gold_grabber',
    'enemy_killer': 'spelunky2rl.envs.enemy_killer',
}


def import_env_class(env_name: str):
    """Dynamically import environment class based on name."""
    if env_name not in ENV_CLASSES:
        raise ValueError(f"Unknown environment: {env_name}. Available: {list(ENV_CLASSES.keys())}")

    module_path = ENV_CLASSES[env_name]
    module = __import__(module_path, fromlist=['SpelunkyEnv'])
    return module.SpelunkyEnv


def make_env(env_class, env_id: int, game_dir: str, stagger_delay: float = 2.0):
    """Factory function to create a monitored SpelunkyEnv instance.

    Args:
        env_class: The environment class to instantiate
        env_id: Environment identifier (used for staggered initialization)
        game_dir: Spelunky 2 folder (None: $SPELUNKY2RL_GAME_DIR)
        stagger_delay: Delay between environment starts (seconds)

    Returns:
        Function that creates a monitored environment
    """
    def _init():
        # Stagger initialization to avoid race conditions
        time.sleep(env_id * stagger_delay)

        if env_id > 0:  # Don't print for first env
            print(f"  [Env {env_id}] Initializing...")

        env = env_class(
            frames_per_step=6,
            render_enabled=False,
            game_dir=game_dir,
            manual_control=False
        )
        env = Monitor(env)

        if env_id > 0:
            print(f"  [Env {env_id}] Ready")

        return env
    return _init


def test_single_env(env_class, duration: float, game_dir: str) -> Tuple[int, float, float]:
    """Benchmark a single environment.

    Args:
        env_class: The environment class to test
        duration: Test duration in seconds
        game_dir: Spelunky 2 folder (None: $SPELUNKY2RL_GAME_DIR)

    Returns:
        Tuple of (total_steps, elapsed_time, steps_per_second)
    """
    print("Initializing single environment...")

    env = env_class(
        frames_per_step=6,
        render_enabled=False,
        game_dir=game_dir,
        manual_control=False
    )

    print("Running benchmark...")
    obs, _ = env.reset()

    start_time = time.time()
    end_time = start_time + duration
    step_count = 0

    try:
        while time.time() < end_time:
            action = env.action_space.sample()
            obs, reward, done, truncated, info = env.step(action)
            step_count += 1

            if done or truncated:
                obs, _ = env.reset()
    finally:
        env.close()

    elapsed_time = time.time() - start_time
    steps_per_sec = step_count / elapsed_time

    return step_count, elapsed_time, steps_per_sec


def test_parallel_envs(env_class, num_envs: int, duration: float,
                      game_dir: str, stagger_delay: float = 2.0) -> Tuple[int, float, float]:
    """Benchmark parallel environments using SubprocVecEnv.

    Args:
        env_class: The environment class to test
        num_envs: Number of parallel environments
        duration: Test duration in seconds
        game_dir: Spelunky 2 folder (None: $SPELUNKY2RL_GAME_DIR)
        stagger_delay: Delay between environment starts (seconds)

    Returns:
        Tuple of (total_steps, elapsed_time, steps_per_second)
    """
    print(f"Initializing {num_envs} parallel environments...")
    print(f"  Using stagger delay of {stagger_delay}s between starts")

    try:
        # Create parallel environments
        env = SubprocVecEnv([
            make_env(env_class, i, game_dir, stagger_delay)
            for i in range(num_envs)
        ])

        print(f"Successfully initialized {num_envs} environments")
        print("Running benchmark...")

        obs = env.reset()

        start_time = time.time()
        end_time = start_time + duration
        step_count = 0

        while time.time() < end_time:
            actions = [env.action_space.sample() for _ in range(num_envs)]
            obs, rewards, dones, infos = env.step(actions)
            step_count += num_envs  # Each step processes all environments

        elapsed_time = time.time() - start_time
        steps_per_sec = step_count / elapsed_time

        env.close()
        return step_count, elapsed_time, steps_per_sec

    except Exception as e:
        print(f"ERROR: Failed to run {num_envs} parallel environments")
        print(f"Error details: {e}")
        return 0, 0.0, 0.0


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark SpelunkyRL environment performance",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test single dummy environment
  python examples/benchmark_performance.py --env dummy

  # Test parallel get_to_exit environments
  python examples/benchmark_performance.py --env get_to_exit --num-envs 2 4

  # Longer benchmark
  python examples/benchmark_performance.py --env gold_grabber --duration 60
        """
    )

    parser.add_argument(
        "--env",
        type=str,
        default="dummy",
        choices=list(ENV_CLASSES.keys()),
        help="Environment to benchmark (default: dummy)"
    )
    parser.add_argument(
        "--num-envs",
        type=int,
        nargs="+",
        default=[1],
        help="Number(s) of parallel environments to test (default: [1])"
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=20.0,
        help="Test duration in seconds per configuration (default: 20.0)"
    )
    parser.add_argument(
        "--stagger-delay",
        type=float,
        default=2.0,
        help="Delay between parallel environment starts in seconds (default: 2.0)"
    )
    parser.add_argument(
        "--game-dir",
        type=str,
        default=None,
        help="Spelunky 2 folder (default: $SPELUNKY2RL_GAME_DIR)"
    )

    args = parser.parse_args()

    # Import the selected environment class
    env_class = import_env_class(args.env)

    # Print header
    print("=" * 80)
    print(f"SpelunkyRL Performance Benchmark - {args.env.upper()} Environment")
    print("=" * 80)
    print(f"Test duration: {args.duration} seconds per configuration")
    print(f"Parallel configs: {args.num_envs}")
    print(f"Stagger delay: {args.stagger_delay} seconds")
    print()

    results = []
    baseline_sps = None  # Steps per second for single env (for speedup calculation)

    # Run benchmarks for each configuration
    for num_envs in sorted(args.num_envs):
        print("-" * 80)

        if num_envs == 1:
            # Single environment
            steps, elapsed, sps = test_single_env(
                env_class, args.duration, args.game_dir
            )
            config_name = "Single"
            baseline_sps = sps  # Set baseline for speedup calculation
        else:
            # Parallel environments
            steps, elapsed, sps = test_parallel_envs(
                env_class, num_envs, args.duration,
                args.game_dir, args.stagger_delay
            )
            config_name = f"{num_envs} Parallel"

        if sps > 0:  # Successful test
            speedup = sps / baseline_sps if baseline_sps else 1.0
            sps_per_env = sps / num_envs
            results.append((config_name, num_envs, steps, elapsed, sps, sps_per_env, speedup))

            print("\nResults:")
            print(f"  Total steps: {steps}")
            print(f"  Time: {elapsed:.2f}s")
            print(f"  Steps/sec (total): {sps:.2f}")
            print(f"  Steps/sec (per env): {sps_per_env:.2f}")
            if baseline_sps and num_envs > 1:
                print(f"  Speedup: {speedup:.2f}x")
        else:
            print("\nFAILED: Benchmark failed for this configuration")
            results.append((config_name, num_envs, 0, 0, 0, 0, 0))

        print()

    # Summary table
    print("=" * 90)
    print("BENCHMARK SUMMARY")
    print("=" * 90)
    print(f"{'Config':<15} {'Envs':<6} {'Steps':<12} {'Time (s)':<10} "
          f"{'Total SPS':<12} {'SPS/Env':<12} {'Speedup':<10}")
    print("-" * 90)

    for config, num_envs, steps, elapsed, sps, sps_per_env, speedup in results:
        if sps > 0:  # Successful test
            speedup_str = f"{speedup:.2f}x" if speedup > 0 else "N/A"
            print(f"{config:<15} {num_envs:<6} {steps:<12} {elapsed:<10.2f} "
                  f"{sps:<12.2f} {sps_per_env:<12.2f} {speedup_str:<10}")
        else:  # Failed test
            print(f"{config:<15} {num_envs:<6} {'FAILED':<12} {'--':<10} "
                  f"{'--':<12} {'--':<12} {'FAILED':<10}")

    print("=" * 90)
    print("\nTips:")
    print("- Higher SPS (steps per second) = faster training")
    print("- Parallel environments improve total throughput but may reduce per-env efficiency")
    print("- 'dummy' environment is fastest for pure performance testing")
    print("- Adjust --stagger-delay if parallel initialization fails")


if __name__ == "__main__":
    main()
