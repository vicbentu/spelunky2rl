import socket

import pytest

from fake_lua import FakeLua
from spelunky2rl.engine.launchers import Launcher
from spelunky2rl.engine.protocol import PROTOCOL_VERSION

HELLO = {"hello": {"protocol": PROTOCOL_VERSION, "mod": "test"}}


class FakeLauncher(Launcher):
    """Instead of a game, connects a FakeLua to the engine's port.
    `fail_starts` makes the first N starts die without connecting."""

    def __init__(self, respond=None, hello=HELLO, fail_starts=0, connect=True):
        self.respond = respond
        self.hello = hello
        self.fail_starts = fail_starts
        self.connect = connect
        self.starts = 0
        self.stops = 0
        self.running = False
        self.lua = None

    def start(self, port):
        self.starts += 1
        if self.starts <= self.fail_starts:
            self.running = False
            return
        self.running = True
        if self.connect:
            # the engine is already listening, so this completes before accept()
            sock = socket.create_connection(("127.0.0.1", port))
            self.lua = FakeLua(sock, self.respond, hello=self.hello)

    def is_running(self):
        return self.running

    def stop(self):
        self.stops += 1
        self.running = False

    def diagnostics(self):
        return "fake launcher output"


@pytest.fixture
def make_env():
    """Build any SpelunkyEnv class wired to a FakeLua instead of a real game."""
    created = []

    def factory(env_cls, respond=None, launcher=None, **kwargs):
        launcher = launcher or FakeLauncher(respond)
        env = env_cls(launcher=launcher, **kwargs)
        env.fake_lua = launcher.lua
        created.append(env)
        return env

    yield factory
    for env in created:
        env.close()
