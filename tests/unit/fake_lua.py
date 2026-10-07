"""A stand-in for the Lua mod: speaks the protocol and answers with synthetic game states."""

import json
import socket
import threading

import numpy as np

# basic_info as mod/lua/spelunky2rl/observations.lua packs it
BASIC = [["x", "<f8"], ["y", "<f8"], ["x_rest", "<f8"], ["y_rest", "<f8"], ["layer", "<i4"],
         ["health", "<i4"], ["bombs", "<i4"], ["ropes", "<i4"], ["money", "<i4"],
         ["vel_x", "<f8"], ["vel_y", "<f8"], ["face_left", "?"], ["powerups", "u1", 18],
         ["holding_type_player", "<i4"], ["back_item", "<i4"], ["char_state", "<i4"], ["can_jump", "?"],
         ["world", "<i4"], ["level", "<i4"], ["theme", "<i4"], ["time", "<i4"], ["win", "<i4"],
         ["dead_enemies", "<i4"]]


def make_gamestate(rng, time=60, health=4, dist_to_goal=50, dead_enemies=0, money=0, win=0,
                   fields=("map_info", "dist_to_goal", "entity_info")):
    """A game state with the shape and value ranges that the mod produces, as Python reads it.
    `fields` are names, or reset fields ({"name": ..., "width": ..., "height": ...})."""
    gamestate = {
        "basic_info": {
            "x": 20.0, "y": 100.0, "x_rest": 0.3, "y_rest": 0.05, "layer": 0,
            "health": health, "bombs": 4, "ropes": 4, "money": money,
            "vel_x": 0.0, "vel_y": -0.1, "face_left": bool(rng.integers(2)),
            "powerups": [0] * 18, "holding_type_player": 0, "back_item": 0,
            "char_state": int(rng.integers(0, 23)), "can_jump": bool(rng.integers(2)),
            "world": 1, "level": 1, "theme": 1, "time": time, "win": win,
            "dead_enemies": dead_enemies,
        },
    }
    for field in fields:
        field = field if isinstance(field, dict) else {"name": field, "width": 21, "height": 11}
        name = field["name"]
        if name == "map_info":
            gamestate["map_info"] = rng.choice([0, 1, 4, 13, 15, 23, 114], size=(field["height"], field["width"]))
        elif name == "dist_to_goal":
            gamestate["dist_to_goal"] = dist_to_goal
        elif name == "entity_info":
            half_x, half_y = field["width"] / 2, field["height"] / 2
            gamestate["entity_info"] = np.array([
                [rng.uniform(-half_x, half_x), rng.uniform(-half_y, half_y), 0.0, 0.0,
                 entity_type, rng.integers(2), 0]
                for entity_type in (220, 495, 600)
            ], dtype=np.float64)
    return gamestate


def layout_for(fields):
    """The layout the mod sends for these reset fields."""
    layout = [{"name": "basic_info", "record": BASIC}]
    for field in fields:
        if field["name"] == "map_info":
            layout.append({"name": "map_info", "dtype": "<i4", "shape": [field["height"], field["width"]]})
        elif field["name"] == "entity_info":
            layout.append({"name": "entity_info", "dtype": "<f8", "shape": [-1, 7]})
        elif field["name"] == "dist_to_goal":
            layout.append({"name": "dist_to_goal", "dtype": "<i4", "shape": []})
    return layout


def pack_state(layout, gamestate) -> bytes:
    """`gamestate` packed as `layout` says, the way the mod does it."""
    parts = []
    for field in layout:
        value = gamestate[field["name"]]
        if "record" in field:
            dtype = np.dtype([(key, dt, tuple(count)) if count else (key, dt) for key, dt, *count in field["record"]])
            record = np.zeros(1, dtype)
            for key in dtype.names:
                record[key] = value[key]
            parts.append(record.tobytes())
        elif field["shape"] == []:
            parts.append(np.array(value, field["dtype"]).tobytes())
        else:
            array = np.asarray(value, field["dtype"])
            if -1 in field["shape"]:
                parts.append(np.uint32(len(array)).tobytes())
            parts.append(array.tobytes())
    return b"".join(parts)


class FakeLua(threading.Thread):
    """Client end of the engine socket. `respond(message, step_index)` returns the state to send (a
    dict like make_gamestate's), a dict with "error", or None to stay silent. Every received message
    is kept in `messages`."""

    def __init__(self, sock: socket.socket, respond=None, seed=0, hello=None):
        super().__init__(daemon=True)
        self.sock = sock
        self.hello = hello
        self.rng = np.random.default_rng(seed)
        self.respond = respond or self.default_respond
        self.messages = []
        self.steps = 0
        self.fields = []
        self.start()

    def default_respond(self, message, steps):
        return make_gamestate(self.rng, time=60 + 6 * steps, fields=self.fields)

    def send_line(self, header, state=b""):
        self.sock.sendall((json.dumps(header) + "\n").encode() + state)

    def run(self):
        if self.hello is not None:
            self.send_line(self.hello)
        reader = self.sock.makefile("rb")
        layout = None
        try:
            for line in reader:
                message = json.loads(line)
                self.messages.append(message)
                if message["command"] == "close":
                    break
                if message["command"] == "reset":
                    self.steps = 0
                    self.fields = message["fields"]
                    layout = layout_for(self.fields)
                else:
                    self.steps += 1
                reply = self.respond(message, self.steps)
                if reply is None:
                    continue
                if "error" in reply:
                    self.send_line(reply)
                    continue
                state = pack_state(layout, reply)
                header = {"state": len(state), "drawn": self.steps}
                if message["command"] == "reset":
                    header["layout"] = layout
                self.send_line(header, state)
        except OSError:
            pass
        finally:
            reader.close()
            self.sock.close()
