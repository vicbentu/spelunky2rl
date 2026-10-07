import mmap
import os
import struct
import time
from typing import Optional

import numpy as np

from .base import FrameSource

# The file docker/vklayer/capture.c writes: this header, then the pixels at offset HEADER_SIZE
HEADER = struct.Struct("<IIQIIIIQ")  # magic, version, frame, width, height, format, stride, copy_ns
HEADER_SIZE = 4096
MAGIC = 0x53324C52
VERSION = 1
# VkFormat -> the channels of RGB in each pixel
CHANNELS = {37: [0, 1, 2], 43: [0, 1, 2],   # R8G8B8A8 UNORM, SRGB
            44: [2, 1, 0], 50: [2, 1, 0]}   # B8G8R8A8 UNORM, SRGB
SPIN = 0.002  # seconds of busy polling before sleeping between looks (the GPU takes ~0.05 ms)


class VulkanFrameSource(FrameSource):
    """Reads the frames the Vulkan layer copies to `path`, one per present, with their count."""

    def __init__(self, path, timeout: float):
        self.path = os.fspath(path)
        self.timeout = timeout
        self._map = None

    def _header(self):
        """(frame, width, height, format, stride), or None while the layer has not written yet."""
        if self._map is None:
            try:
                with open(self.path, "rb") as f:
                    if os.fstat(f.fileno()).st_size < HEADER_SIZE:
                        return None
                    self._map = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            except FileNotFoundError:
                return None
        magic, version, frame, width, height, fmt, stride, _ = HEADER.unpack_from(self._map)
        if magic != MAGIC or version != VERSION:
            raise RuntimeError(f"{self.path} is not a capture of version {VERSION} "
                               f"(magic {magic:#x}, version {version}): the game image and this package differ")
        return frame, width, height, fmt, stride

    def get_frame(self, drawn: Optional[int] = None) -> np.ndarray:
        start = time.monotonic()
        while True:
            header = self._header()
            if header is not None and (drawn is None or header[0] >= drawn):
                break
            waited = time.monotonic() - start
            if waited > self.timeout:
                got = "nothing" if header is None else f"{header[0]} frames"
                raise TimeoutError(f"The game drew {drawn} frames, but the capture has {got} after {self.timeout} s")
            time.sleep(0 if waited < SPIN else 0.0002)
        frame, width, height, fmt, stride = header
        if drawn is not None and frame != drawn:
            raise RuntimeError(f"The capture is at frame {frame} and the game drew {drawn}: they are out of sync")
        if fmt not in CHANNELS:
            raise RuntimeError(f"The game presents in Vulkan format {fmt}; render() reads only 8-bit RGBA and BGRA")
        if len(self._map) < HEADER_SIZE + stride * height:
            # the swapchain grew and the layer grew the file: map it again
            self._map.close()
            self._map = None
            self._header()
        pixels = np.frombuffer(self._map, np.uint8, stride * height, HEADER_SIZE).reshape(height, stride // 4, 4)
        return pixels[:, :width, CHANNELS[fmt]]  # fancy indexing: a copy, not a view of the file

    def close(self) -> None:
        if self._map is not None:
            self._map.close()
            self._map = None
