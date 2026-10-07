import mmap
import os
import struct
import time
from typing import List, Optional

import numpy as np

from .base import FrameSource

# The file docker/vklayer/capture.c writes: this header, then `slots` slots of `slot_size` bytes at
# offset HEADER_SIZE, each a SLOT header and the pixels at offset SLOT_SIZE within the slot
HEADER = struct.Struct("<IIQIIQ")  # magic, version, frame, slots, pad, slot_size
HEADER_SIZE = 4096
SLOT = struct.Struct("<QIIIIQ")    # frame, width, height, format, stride, copy_ns
SLOT_SIZE = 64
MAGIC = 0x53324C52
VERSION = 2
# VkFormat -> the channels of RGB in each pixel
CHANNELS = {37: [0, 1, 2], 43: [0, 1, 2],   # R8G8B8A8 UNORM, SRGB
            44: [2, 1, 0], 50: [2, 1, 0]}   # B8G8R8A8 UNORM, SRGB
SPIN = 0.002  # seconds of busy polling before sleeping between looks (the GPU takes ~0.05 ms)


class VulkanFrameSource(FrameSource):
    """Reads the frames the Vulkan layer copies to `path`, one per present, with their count. The
    file keeps the last few frames (as many as the launcher asked the layer for)."""

    counts_frames = True

    def __init__(self, path, timeout: float):
        self.path = os.fspath(path)
        self.timeout = timeout
        self._map = None

    def _header(self):
        """(frame, slots, slot_size), or None while the layer has not written yet."""
        if self._map is None:
            try:
                with open(self.path, "rb") as f:
                    if os.fstat(f.fileno()).st_size < HEADER_SIZE:
                        return None
                    self._map = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            except FileNotFoundError:
                return None
        magic, version, frame, slots, _, slot_size = HEADER.unpack_from(self._map)
        if magic == 0:
            return None  # the layer has made the file but not written the header yet
        if magic != MAGIC or version != VERSION:
            raise RuntimeError(f"{self.path} is not a capture of version {VERSION} "
                               f"(magic {magic:#x}, version {version}): the game image and this package differ")
        if len(self._map) < HEADER_SIZE + slots * slot_size:
            # the swapchain grew and the layer grew the file: map it again
            self._map.close()
            self._map = None
            return self._header()
        return frame, slots, slot_size

    def _wait(self, drawn: Optional[int]):
        """The header once the layer has copied frame `drawn` (any frame if None)."""
        start = time.monotonic()
        while True:
            header = self._header()
            if header is not None and header[0] > 0 and (drawn is None or header[0] >= drawn):
                break
            waited = time.monotonic() - start
            if waited > self.timeout:
                got = "nothing" if header is None else f"{header[0]} frames"
                raise TimeoutError(f"The game drew {drawn} frames, but the capture has {got} after {self.timeout} s")
            time.sleep(0 if waited < SPIN else 0.0002)
        if drawn is not None and header[0] != drawn:
            raise RuntimeError(f"The capture is at frame {header[0]} and the game drew {drawn}: they are out of sync")
        return header

    def _read(self, frame: int, slots: int, slot_size: int) -> np.ndarray:
        offset = HEADER_SIZE + (frame - 1) % slots * slot_size
        number, width, height, fmt, stride, _ = SLOT.unpack_from(self._map, offset)
        if number != frame:
            raise RuntimeError(f"Frame {frame} is no longer in the capture, which keeps the last {slots}: "
                               f"its slot has frame {number}")
        if fmt not in CHANNELS:
            raise RuntimeError(f"The game presents in Vulkan format {fmt}; render() reads only 8-bit RGBA and BGRA")
        pixels = np.frombuffer(self._map, np.uint8, stride * height, offset + SLOT_SIZE).reshape(height, stride // 4, 4)
        return pixels[:, :width, CHANNELS[fmt]]  # fancy indexing: a copy, not a view of the file

    def get_frame(self, drawn: Optional[int] = None) -> np.ndarray:
        frame, slots, slot_size = self._wait(drawn)
        return self._read(frame, slots, slot_size)

    def get_frames(self, first: int, drawn: int) -> List[np.ndarray]:
        frame, slots, slot_size = self._wait(drawn)
        if drawn - first >= slots:
            raise RuntimeError(f"Frames {first} to {drawn} are {drawn - first + 1}, but the capture keeps the "
                               f"last {slots}")
        return [self._read(n, slots, slot_size) for n in range(first, drawn + 1)]

    def close(self) -> None:
        if self._map is not None:
            self._map.close()
            self._map = None
