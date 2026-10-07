"""render()'s frames: the file the Vulkan layer writes (docker/vklayer/capture.c) and how the engine
asks for the state's frame."""

import threading
import time

import numpy as np
import pytest

from conftest import FakeLauncher
from spelunky2rl.engine.frames import FrameSource
from spelunky2rl.engine.frames.vulkan import HEADER, HEADER_SIZE, MAGIC, VERSION, VulkanFrameSource
from spelunky2rl.envs.default_environment import SpelunkyEnv as DefaultEnv

B8G8R8A8_UNORM, R8G8B8A8_UNORM, R16G16B16A16_SFLOAT = 44, 37, 97


class FakeLayer:
    """Writes the capture file as the layer does: pixels first, then the count."""

    def __init__(self, path):
        self.path = path
        self.frame = 0

    def present(self, bgra, fmt=B8G8R8A8_UNORM, magic=MAGIC):
        height, width = bgra.shape[:2]
        size = HEADER_SIZE + bgra.nbytes
        with open(self.path, "r+b" if self.path.exists() else "w+b") as f:
            f.truncate(max(size, self.path.stat().st_size))
            f.seek(HEADER_SIZE)
            f.write(bgra.tobytes())
            self.frame += 1
            f.seek(0)
            f.write(HEADER.pack(magic, VERSION, self.frame, width, height, fmt, width * 4, 0))


def image(height, width, value):
    """BGRA pixels whose B, G, R are value, value + 1, value + 2."""
    pixels = np.zeros((height, width, 4), np.uint8)
    pixels[..., :3] = [value, value + 1, value + 2]
    return pixels


@pytest.fixture
def layer(tmp_path):
    return FakeLayer(tmp_path / "frame")


def test_the_frame_comes_as_rgb(layer):
    layer.present(image(9, 16, 10))
    frame = VulkanFrameSource(layer.path, timeout=1).get_frame(drawn=1)
    assert frame.shape == (9, 16, 3) and frame.dtype == np.uint8
    assert frame[0, 0].tolist() == [12, 11, 10]
    rgba = image(9, 16, 10)
    layer.present(rgba, fmt=R8G8B8A8_UNORM)
    assert VulkanFrameSource(layer.path, timeout=1).get_frame(drawn=2)[0, 0].tolist() == [10, 11, 12]


def test_the_frame_does_not_change_with_the_file(layer):
    """render() returns a copy: the next present must not change an image already returned."""
    source = VulkanFrameSource(layer.path, timeout=1)
    layer.present(image(9, 16, 10))
    frame = source.get_frame(drawn=1)
    layer.present(image(9, 16, 50))
    assert frame[0, 0].tolist() == [12, 11, 10]
    assert source.get_frame(drawn=2)[0, 0].tolist() == [52, 51, 50]


def test_waits_for_the_state_frame(layer):
    """The game answers before the frame reaches the layer (DXVK presents in its own thread)."""
    layer.present(image(9, 16, 10))
    source = VulkanFrameSource(layer.path, timeout=2)
    later = threading.Timer(0.05, layer.present, args=(image(9, 16, 50),))
    later.start()
    start = time.monotonic()
    frame = source.get_frame(drawn=2)
    assert time.monotonic() - start >= 0.04
    assert frame[0, 0].tolist() == [52, 51, 50]
    later.join()


def test_waits_for_the_file(layer):
    source = VulkanFrameSource(layer.path, timeout=2)
    later = threading.Timer(0.05, layer.present, args=(image(9, 16, 10),))
    later.start()
    assert source.get_frame(drawn=1)[0, 0].tolist() == [12, 11, 10]
    later.join()


def test_times_out(layer):
    layer.present(image(9, 16, 10))
    with pytest.raises(TimeoutError, match="drew 2 frames, but the capture has 1"):
        VulkanFrameSource(layer.path, timeout=0.1).get_frame(drawn=2)
    with pytest.raises(TimeoutError, match="capture has nothing"):
        VulkanFrameSource(layer.path.with_name("missing"), timeout=0.1).get_frame(drawn=1)


def test_a_capture_ahead_of_the_game_is_an_error(layer):
    """The image would not be the state's: fail rather than return it."""
    layer.present(image(9, 16, 10))
    layer.present(image(9, 16, 10))
    with pytest.raises(RuntimeError, match="out of sync"):
        VulkanFrameSource(layer.path, timeout=1).get_frame(drawn=1)


def test_other_formats_and_files_are_refused(layer, tmp_path):
    layer.present(image(9, 16, 10), fmt=R16G16B16A16_SFLOAT)
    with pytest.raises(RuntimeError, match="format 97"):
        VulkanFrameSource(layer.path, timeout=1).get_frame(drawn=1)
    other = FakeLayer(tmp_path / "other")
    other.present(image(9, 16, 10), magic=0x1234)
    with pytest.raises(RuntimeError, match="not a capture"):
        VulkanFrameSource(other.path, timeout=1).get_frame(drawn=1)


def test_a_bigger_swapchain_is_read_whole(layer):
    source = VulkanFrameSource(layer.path, timeout=1)
    layer.present(image(9, 16, 10))
    source.get_frame(drawn=1)
    layer.present(image(36, 64, 50))
    frame = source.get_frame(drawn=2)
    assert frame.shape == (36, 64, 3) and frame[-1, -1].tolist() == [52, 51, 50]


class RecordingSource(FrameSource):
    def __init__(self):
        self.asked = []

    def get_frame(self, drawn=None):
        self.asked.append(drawn)
        return np.zeros((360, 640, 3), np.uint8)


class CapturingLauncher(FakeLauncher):
    def __init__(self):
        super().__init__()
        self.source = RecordingSource()

    def frame_source(self, timeout):
        return self.source


def test_render_asks_for_the_last_state_frame(make_env):
    launcher = CapturingLauncher()
    env = make_env(DefaultEnv, launcher=launcher, render_mode="rgb_array")
    assert launcher.capture
    env.reset(seed=0)
    env.render()
    env.step([1, 1, 0, 0, 0, 0, 0, 0])
    env.step([1, 1, 0, 0, 0, 0, 0, 0])
    env.render()
    env.render()
    assert launcher.source.asked == [0, 2, 2]  # FakeLua's `drawn` is its step count


def test_no_capture_without_render(make_env):
    launcher = CapturingLauncher()
    make_env(DefaultEnv, launcher=launcher)
    assert not launcher.capture
