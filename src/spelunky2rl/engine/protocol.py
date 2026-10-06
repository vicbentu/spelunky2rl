"""Protocol between Python and the Lua mod (mod/lua/spelunky2rl/protocol.lua).

Python listens on 127.0.0.1 and the Lua mod connects. Python sends one JSON object per line. The mod
answers with a JSON header line, followed by `state` bytes when the header has that key:

- first, unasked: ``{"hello": {"protocol": N, "mod": "x.y.z"}}``
- to `reset`: ``{"state": n, "layout": [...]}`` and the game state, packed as `layout` says
- to `step`: ``{"state": n}`` and the game state, with the layout of the last reset
- on a Lua error, at any time: ``{"error": "..."}``

`close` gets no answer. StateLayout reads the game state.
"""

import json
import socket
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ..version import __version__

# Bump when a message changes shape; keep in sync with PROTOCOL_VERSION in mod/lua/spelunky2rl/protocol.lua
PROTOCOL_VERSION = 2


class ProtocolError(RuntimeError):
    """The game runs a mod that does not speak this package's protocol."""


class Connection:
    """The message stream over a connected socket."""

    def __init__(self, sock: socket.socket, timeout: Optional[float]):
        self.sock = sock
        self.timeout = timeout
        self._buffer = bytearray()
        sock.settimeout(timeout)
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            # one message each way per step: never wait to batch
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def send(self, payload: Dict[str, Any]) -> None:
        self.sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))

    def receive(self, timeout: Optional[float] = None) -> Tuple[Dict[str, Any], Optional[bytearray]]:
        """The next header and the state bytes that follow it (None if the header has no `state`)."""
        timeout = self.timeout if timeout is None else timeout
        self.sock.settimeout(timeout)
        try:
            while (end := self._buffer.find(b"\n")) < 0:
                self._fill(timeout)
            header = json.loads(self._buffer[:end].decode("utf-8"))
            del self._buffer[:end + 1]
            if "error" in header:
                raise RuntimeError(header["error"])
            size = header.get("state")
            if size is None:
                return header, None
            while len(self._buffer) < size:
                self._fill(timeout)
            data = self._buffer[:size]
            del self._buffer[:size]
            return header, data
        finally:
            self.sock.settimeout(self.timeout)

    def _fill(self, timeout: Optional[float]) -> None:
        try:
            data = self.sock.recv(1 << 20)
        except socket.timeout:
            raise TimeoutError(f"No response from the Spelunky Lua script in {timeout} s") from None
        if not data:
            raise ConnectionError("Disconnected from Spelunky Lua script")
        self._buffer += data

    def close(self) -> None:
        self.sock.close()


class StateLayout:
    """Reads game states packed as the mod's `layout` says: a list of fields in the order of the bytes,
    all little-endian, each one of

    - ``{"name": n, "record": [[key, dtype], [key, dtype, count], ...]}``: a dict of Python values
      (bool, int, float; a list where there is a count)
    - ``{"name": n, "dtype": d, "shape": []}``: one Python value
    - ``{"name": n, "dtype": d, "shape": [...]}``: a numpy array; a -1 in the shape is the number of
      rows, sent as a uint32 before them
    """

    def __init__(self, layout: List[Dict[str, Any]]):
        self.fields = []
        try:
            for field in layout:
                if "record" in field:
                    dtype = np.dtype([(key, dt, tuple(count)) if count else (key, dt)
                                      for key, dt, *count in field["record"]])
                    self.fields.append((field["name"], "record", dtype, None))
                else:
                    self.fields.append((field["name"], "array", np.dtype(field["dtype"]), tuple(field["shape"])))
        except (KeyError, TypeError, ValueError) as e:
            raise ProtocolError(f"The mod sent a layout this package cannot read ({e}): {layout}") from None

    def decode(self, data: bytearray) -> Dict[str, Any]:
        state = {}
        offset = 0
        try:
            for name, kind, dtype, shape in self.fields:
                if kind == "record":
                    record = np.frombuffer(data, dtype, 1, offset)[0]
                    state[name] = {key: record[key].tolist() for key in dtype.names}
                    offset += dtype.itemsize
                    continue
                if -1 in shape:
                    rows = int(np.frombuffer(data, "<u4", 1, offset)[0])
                    offset += 4
                    shape = tuple(rows if size == -1 else size for size in shape)
                count = int(np.prod(shape))
                values = np.frombuffer(data, dtype, count, offset)
                offset += count * dtype.itemsize
                state[name] = values.reshape(shape) if shape else values[0].tolist()
        except ValueError as e:
            raise ProtocolError(f"Game state shorter than its layout ({len(data)} bytes): {e}") from None
        if offset != len(data):
            raise ProtocolError(f"Game state of {len(data)} bytes, but its layout reads {offset}")
        return state


def check_hello(message: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the mod's first message and return its contents."""
    hello = message.get("hello")
    if not isinstance(hello, dict) or hello.get("protocol") != PROTOCOL_VERSION:
        got = hello.get("protocol") if isinstance(hello, dict) else None
        mod = hello.get("mod", "unknown") if isinstance(hello, dict) else "unknown"
        raise ProtocolError(
            f"The game runs spelunky2rl mod {mod} (protocol {got}), but this package "
            f"(spelunky2rl {__version__}) needs protocol {PROTOCOL_VERSION}. "
            f"Use the game image tagged {__version__} (spelunky2rl pull) or the mod from this package."
        )
    return hello
