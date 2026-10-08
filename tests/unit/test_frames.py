"""render()'s frames: the file the Vulkan layer writes (docker/vklayer/capture.c) and how the engine
asks for the state's frame."""

import os
import threading
import time

import numpy as np
import pytest

from conftest import FakeLauncher
from spelunky2rl.engine.frames import FrameSource
from spelunky2rl.engine.frames.vulkan import HEADER, HEADER_SIZE, MAGIC, SLOT, SLOT_SIZE, VERSION, VulkanFrameSource
from spelunky2rl.envs.default_environment import SpelunkyEnv as DefaultEnv

B8G8R8A8_UNORM, R8G8B8A8_UNORM, R16G16B16A16_SFLOAT = 44, 37, 97


class FakeLayer:
    """Writes the capture file as the layer does: a ring of `slots` frames, each frame's pixels first,
    then its slot's count, then the file's."""

    def __init__(self, path, slots=1):
        self.path = path
        self.slots = slots
        self.slot_size = 0
        self.frame = 0

    def present(self, bgra, fmt=B8G8R8A8_UNORM, magic=MAGIC):
        height, width = bgra.shape[:2]
        if SLOT_SIZE + bgra.nbytes > self.slot_size:  # the layer grows the file and drops the frames
            self.slot_size = SLOT_SIZE + bgra.nbytes
            # as the layer: never empty the file first (O_TRUNC), the reader may have it mapped
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT)
            os.ftruncate(fd, HEADER_SIZE + self.slots * self.slot_size)
            os.close(fd)
        self.frame += 1
        slot = HEADER_SIZE + (self.frame - 1) % self.slots * self.slot_size
        with open(self.path, "r+b") as f:
            f.seek(slot + SLOT_SIZE)
            f.write(bgra.tobytes())
            f.seek(slot)
            f.write(SLOT.pack(self.frame, width, height, fmt, width * 4, 0))
            f.seek(0)
            f.write(HEADER.pack(magic, VERSION, self.frame, self.slots, 0, self.slot_size))


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


def test_waits_for_the_header(layer):
    """The layer makes the file (zeros) before it writes the header: that is not an error."""
    layer.path.write_bytes(bytes(HEADER_SIZE))
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


def test_every_frame_of_a_step(tmp_path):
    layer = FakeLayer(tmp_path / "frame", slots=3)
    source = VulkanFrameSource(layer.path, timeout=1)
    for value in (10, 20, 30, 40):
        layer.present(image(9, 16, value))
    frames = source.get_frames(2, 4)
    assert [frame[0, 0, 2] for frame in frames] == [20, 30, 40]
    assert source.get_frame(drawn=4)[0, 0, 2] == 40


def test_frames_no_longer_in_the_ring_are_an_error(tmp_path):
    """The ring keeps only the last few: older frames were overwritten, and it says so."""
    layer = FakeLayer(tmp_path / "frame", slots=3)
    for value in (10, 20, 30, 40):
        layer.present(image(9, 16, value))
    source = VulkanFrameSource(layer.path, timeout=1)
    with pytest.raises(RuntimeError, match="keeps the last 3"):
        source.get_frames(1, 4)
    layer.present(image(9, 16, 50))
    with pytest.raises(RuntimeError, match="Frame 2 is no longer in the capture"):
        source._read(2, 3, layer.slot_size)


def test_a_bigger_swapchain_is_read_whole(layer):
    source = VulkanFrameSource(layer.path, timeout=1)
    layer.present(image(9, 16, 10))
    source.get_frame(drawn=1)
    layer.present(image(36, 64, 50))
    frame = source.get_frame(drawn=2)
    assert frame.shape == (36, 64, 3) and frame[-1, -1].tolist() == [52, 51, 50]


class RecordingSource(FrameSource):
    """Frames whose first pixel is their number in the game's count."""

    counts_frames = True

    def __init__(self):
        self.asked = []

    def get_frame(self, drawn=None):
        self.asked.append(drawn)
        return np.full((36, 64, 3), drawn, np.uint8)

    def get_frames(self, first, drawn):
        self.asked.append((first, drawn))
        return [np.full((36, 64, 3), n, np.uint8) for n in range(first, drawn + 1)]


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
    assert launcher.source.asked == [3, 5, 5]  # FakeLua draws 3 frames per reset and 1 per step


def test_no_capture_without_render(make_env):
    launcher = CapturingLauncher()
    make_env(DefaultEnv, launcher=launcher)
    assert not launcher.capture


def test_render_returns_every_frame_since_the_last_call(make_env):
    """rgb_array_list, as gymnasium.wrappers.RenderCollection: reset's frame, then each step's."""
    launcher = CapturingLauncher()
    env = make_env(DefaultEnv, launcher=launcher, render_mode="rgb_array_list", frames_per_step=4)
    assert launcher.capture and launcher.capture_frames == 4
    env.reset(seed=0)
    assert env.fake_lua.messages[-1]["render"] and env.fake_lua.messages[-1]["render_all"]
    env.step([1, 1, 0, 0, 0, 0, 0, 0])
    assert [frame[0, 0, 0] for frame in env.render()] == [3, 4, 5, 6, 7]  # FakeLua: 3 frames per reset
    assert env.render() == []
    env.step([1, 1, 0, 0, 0, 0, 0, 0])
    env.step([1, 1, 0, 0, 0, 0, 0, 0])
    assert [frame[0, 0, 0] for frame in env.render()] == list(range(8, 16))
    env.step([1, 1, 0, 0, 0, 0, 0, 0])
    env.reset(seed=0)  # drops the frames of the episode before
    assert [frame[0, 0, 0] for frame in env.render()] == [22]
    assert launcher.source.asked == [3, (4, 7), (8, 11), (12, 15), (16, 19), 22]


def test_rgb_array_draws_only_the_last_frame(make_env):
    launcher = CapturingLauncher()
    env = make_env(DefaultEnv, launcher=launcher, render_mode="rgb_array", frames_per_step=4)
    env.reset(seed=0)
    assert not env.fake_lua.messages[-1]["render_all"] and launcher.capture_frames == 1


def test_rgb_array_list_needs_a_source_that_counts_frames(make_env):
    launcher = CapturingLauncher()
    launcher.source.counts_frames = False
    with pytest.raises(ValueError, match="needs the Docker launcher"):
        make_env(DefaultEnv, launcher=launcher, render_mode="rgb_array_list")


def test_unknown_render_mode(make_env):
    with pytest.raises(ValueError, match="render_mode must be"):
        make_env(DefaultEnv, render_mode="human")


def test_render_fps_is_that_of_what_render_returns(make_env):
    """So that RecordVideo (one render() per step) and save_video (render_fps) play at game speed."""
    assert make_env(DefaultEnv, launcher=CapturingLauncher(), render_mode="rgb_array",
                    frames_per_step=4).metadata["render_fps"] == 15
    assert make_env(DefaultEnv, launcher=CapturingLauncher(), render_mode="rgb_array_list",
                    frames_per_step=4).metadata["render_fps"] == 60
    assert DefaultEnv.metadata["render_fps"] == 60
