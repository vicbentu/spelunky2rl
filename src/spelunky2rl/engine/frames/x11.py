from typing import Optional

import numpy as np

from .base import FrameSource


class X11FrameSource(FrameSource):
    """Grabs the screen of the X display the game runs on (one Xvfb per instance). It cannot tell
    frames apart: the screen may still show a frame from before the state (see docs/architecture.md)."""

    def __init__(self, display: str):
        try:
            import mss
        except ImportError:
            raise ImportError("render_enabled=True with launcher='wine' needs mss: pip install 'spelunky2rl[render]'") from None
        self.display = display
        self._sct = mss.MSS(display=display)

    def get_frame(self, drawn: Optional[int] = None) -> np.ndarray:
        shot = self._sct.grab(self._sct.monitors[0])
        # BGRA -> RGB
        return np.asarray(shot)[..., 2::-1].copy()

    def close(self) -> None:
        self._sct.close()
