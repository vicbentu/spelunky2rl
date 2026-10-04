"""
Record Video with Pretrained Agent

This script demonstrates how to record a video of a pretrained RL agent playing Spelunky 2.

Usage:
1. Train a model using train_get_to_exit.py (or use a pretrained model)
2. Update MODEL_PATH below to point to your saved model
3. Run this script to record a video

The script will:
- Load the specified model
- Record gameplay for the specified duration
- Save the video as MP4 in the output directory

Requirements:
- stable-baselines3
- sb3-contrib (if using RecurrentPPO)
- opencv-python (cv2)
- A trained model file (.zip)
"""

import time
import cv2
import numpy as np
from datetime import datetime
import os

from sb3_contrib import RecurrentPPO
from stable_baselines3 import PPO

from spelunky2rl.envs.get_to_exit import SpelunkyEnv


##################### CONFIGURATION #####################

# IMPORTANT: Update this path to your trained model
MODEL_PATH = "./models_get_to_exit/final_model.zip"

# Recording settings
DURATION = 30           # Recording duration in seconds
OUTPUT_DIR = "./videos"  # Directory to save videos
FPS = 10                # One video frame per step: 60 game frames/s / frames_per_step=6 = real time
USE_LSTM = True         # Set to True if model uses RecurrentPPO, False for PPO
DETERMINISTIC = True    # Use deterministic actions (recommended for videos)


##################### RECORDING FUNCTION #####################

def record_agent_video(
    model_path: str,
    duration: int = 30,
    output_dir: str = "./videos",
    fps: int = 10,
    use_lstm: bool = True,
    deterministic: bool = True
):
    """
    Record a video of a pretrained agent playing Spelunky 2.

    Args:
        model_path: Path to saved model (.zip file)
        duration: Recording duration in seconds
        output_dir: Directory to save the video
        fps: Target frames per second for output video
        use_lstm: True if model is RecurrentPPO, False if PPO
        deterministic: Use deterministic actions (no exploration)
    """

    # Create output directory
    os.makedirs(output_dir, exist_ok=True)

    # Generate timestamped filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(output_dir, f"spelunky_agent_{timestamp}.mp4")

    print("=" * 70)
    print("SpelunkyRL - Video Recording")
    print("=" * 70)
    print(f"Model: {model_path}")
    print(f"Duration: {duration} seconds")
    print(f"Output: {output_file}")
    print(f"FPS: {fps}")
    print("=" * 70)
    print()

    try:
        # -------- Initialize Environment -------------------------------------
        print("Initializing environment with rendering enabled...")
        env = SpelunkyEnv(
            # The game folder comes from SPELUNKY2RL_GAME_DIR (or pass game_dir="...")

            frames_per_step=6,      # Same as train_get_to_exit.py: the model acts at the pace it learned
            speedup=False,          # Don't speed up (real-time looks better)
            render_enabled=True,    # ENABLE FRAME GRABBING
            manual_control=False,
            god_mode=False
        )
        print("✓ Environment initialized")

        # -------- Load Model -------------------------------------------------
        print(f"Loading model from {model_path}...")
        if use_lstm:
            model = RecurrentPPO.load(model_path)
        else:
            model = PPO.load(model_path)
        print("✓ Model loaded")

        # -------- Reset Environment ------------------------------------------
        obs, _ = env.reset()
        print("✓ Environment reset")

        # Initialize LSTM state if needed
        lstm_state = None
        episode_start = np.array([True])

        # -------- Setup Video Writer -----------------------------------------
        # Get frame dimensions
        first_frame = env.render()
        h, w, c = first_frame.shape
        print(f"✓ Video dimensions: {w}x{h}")

        # Create video writer
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        video_writer = cv2.VideoWriter(output_file, fourcc, fps, (w, h))

        if not video_writer.isOpened():
            raise RuntimeError("Failed to open video writer")

        print("✓ Video writer initialized")
        print()

        # -------- Record Video -----------------------------------------------
        print(f"Recording {duration} seconds of gameplay...")
        print("Press Ctrl+C to stop early")
        print()

        start_time = time.time()
        end_time = start_time + duration
        frame_count = 0
        episode_count = 0
        last_progress_time = start_time

        while time.time() < end_time:
            # Get action from model
            if use_lstm:
                action, lstm_state = model.predict(
                    obs,
                    state=lstm_state,
                    episode_start=episode_start,
                    deterministic=deterministic
                )
            else:
                action, _ = model.predict(obs, deterministic=deterministic)

            # Step environment
            obs, reward, done, truncated, info = env.step(action)

            # Update episode start flag for LSTM
            episode_start = np.array([done or truncated])

            # Capture and write frame
            frame = env.render()
            video_writer.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))  # render() is RGB, OpenCV wants BGR
            frame_count += 1

            # Reset if episode ends
            if done or truncated:
                episode_count += 1
                success = info.get("success", False)
                print(f"  Episode {episode_count} ended - "
                      f"{'SUCCESS' if success else 'FAILED'}")
                obs, _ = env.reset()
                episode_start = np.array([True])
                lstm_state = None  # Reset LSTM state

            # Show progress every 5 seconds
            current_time = time.time()
            if current_time - last_progress_time >= 5:
                elapsed = current_time - start_time
                remaining = duration - elapsed
                progress = (elapsed / duration) * 100
                print(f"Progress: {progress:.1f}% - "
                      f"{remaining:.1f}s remaining - "
                      f"{frame_count} frames recorded")
                last_progress_time = current_time

        # -------- Cleanup ----------------------------------------------------
        video_writer.release()
        env.close()

        elapsed_time = time.time() - start_time
        actual_fps = frame_count / elapsed_time

        print()
        print("=" * 70)
        print("RECORDING COMPLETE")
        print("=" * 70)
        print(f"Frames recorded: {frame_count}")
        print(f"Episodes: {episode_count}")
        print(f"Recording time: {elapsed_time:.2f} seconds")
        print(f"Actual FPS: {actual_fps:.2f}")
        print(f"Video saved to: {output_file}")

        # Verify file was created
        if os.path.exists(output_file):
            file_size = os.path.getsize(output_file) / (1024 * 1024)  # MB
            print(f"File size: {file_size:.2f} MB")
        else:
            print("⚠ Warning: Video file was not created!")

        print("=" * 70)

    except FileNotFoundError:
        print(f"✗ Error: Model file not found at {model_path}")
        print("Please update MODEL_PATH to point to your trained model.")

    except KeyboardInterrupt:
        print("\n\nRecording stopped by user")
        print("Saving partial video...")
        try:
            video_writer.release()
            env.close()
            print(f"Partial video saved to: {output_file}")
        except Exception:
            pass

    except Exception as e:
        print(f"\n✗ Error during recording: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # Ensure cleanup
        try:
            video_writer.release()
            env.close()
        except Exception:
            pass


##################### MAIN #####################

if __name__ == "__main__":
    record_agent_video(
        model_path=MODEL_PATH,
        duration=DURATION,
        output_dir=OUTPUT_DIR,
        fps=FPS,
        use_lstm=USE_LSTM,
        deterministic=DETERMINISTIC
    )
