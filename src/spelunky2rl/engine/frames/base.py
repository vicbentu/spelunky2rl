from typing import Optional

import numpy as np


class FrameSource:
    """Where render() gets the game's pixels from."""

    def get_frame(self, drawn: Optional[int] = None) -> np.ndarray:
        """The frame as an (H, W, 3) uint8 RGB array. `drawn` is the count of frames the game had drawn
        when it sent the state (its `drawn`): a source that counts frames returns that one, the others
        the latest."""
        raise NotImplementedError

    def close(self) -> None:
        pass


class NullFrameSource(FrameSource):
    def __init__(self, reason: str):
        self.reason = reason

    def get_frame(self, drawn: Optional[int] = None) -> np.ndarray:
        raise RuntimeError(self.reason)
