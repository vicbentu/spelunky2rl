from typing import List, Optional

import numpy as np


class FrameSource:
    """Where render() gets the game's pixels from."""

    # True if it tells frames apart by the game's count of frames drawn: only such a source can
    # return the state's frame for sure, and every frame of a step (get_frames)
    counts_frames = False

    def get_frame(self, drawn: Optional[int] = None) -> np.ndarray:
        """The frame as an (H, W, 3) uint8 RGB array. `drawn` is the count of frames the game had drawn
        when it sent the state (its `drawn`): a source that counts frames returns that one, the others
        the latest."""
        raise NotImplementedError

    def get_frames(self, first: int, drawn: int) -> List[np.ndarray]:
        """Frames `first` to `drawn` of the game's count, oldest first."""
        raise NotImplementedError(f"{type(self).__name__} cannot return every frame of a step")

    def close(self) -> None:
        pass


class NullFrameSource(FrameSource):
    def __init__(self, reason: str):
        self.reason = reason

    def get_frame(self, drawn: Optional[int] = None) -> np.ndarray:
        raise RuntimeError(self.reason)
