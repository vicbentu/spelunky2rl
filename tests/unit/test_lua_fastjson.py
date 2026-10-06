"""The JSON encoder of mod/lua/spelunky2rl/fastjson.lua, run with the system's Lua (skipped if there is none)."""

import json
import shutil
import subprocess
from importlib.resources import files

import pytest

LUA = shutil.which("lua5.4") or shutil.which("lua")
LUA_DIR = files("spelunky2rl") / "mod" / "lua"

pytestmark = pytest.mark.skipif(LUA is None, reason="needs a Lua interpreter (lua5.4 or lua)")

SCRIPT = """
package.path = arg[1] .. "/?.lua;" .. package.path
local fastjson = require("spelunky2rl.fastjson")
local ok, out = pcall(fastjson.encode, {value})
io.write(ok and out or ("error: " .. out))
"""


def encode(value: str) -> str:
    """fastjson.encode of `value`, a Lua expression; "error: ..." if it raises."""
    out = subprocess.run([LUA, "-", str(LUA_DIR)], input=SCRIPT.format(value=value),
                         capture_output=True, text=True, check=True)
    return out.stdout


def decode(value: str):
    return json.loads(encode(value))


def test_lists_of_numbers():
    assert decode("{1, -2, 0, 1.5, -0.25, 1e-20, 1e20}") == [1, -2, 0, 1.5, -0.25, 1e-20, 1e20]


def test_numbers_keep_14_significant_digits():
    assert decode("{0.1 + 0.2, 1/3}") == [0.3, 0.33333333333333]


def test_nested_lists_like_map_info():
    assert decode("{{1, 2, 3}, {4, 5, 6}}") == [[1, 2, 3], [4, 5, 6]]


def test_empty_table_is_an_empty_list():
    assert encode("{}") == "[]"
    assert decode("{a = {}}") == {"a": []}


def test_objects_and_other_types():
    assert decode('{x = 1.5, ok = true, no = false, name = "ana", sub = {k = {1, 2}}}') == {
        "x": 1.5, "ok": True, "no": False, "name": "ana", "sub": {"k": [1, 2]}}


def test_lists_that_are_not_only_numbers():
    assert decode('{1, "two", true, {3}, {}}') == [1, "two", True, [3], []]


def test_strings_are_escaped():
    assert decode(r'{s = "q\"uo\\te\n\t\1\127end"}') == {"s": 'q"uo\\te\n\t\x01\x7fend'}


def test_whole_floats_decode_as_floats():
    assert encode("{3.0, 3}") == "[3.0,3]"


def test_nan_and_infinity_raise():
    assert encode("{1, 0/0}").startswith("error:")
    assert encode("{1, math.huge}").startswith("error:")
    assert encode("{x = -math.huge}").startswith("error:")


def test_mixed_keys_raise():
    assert encode("{[2] = 1, x = 1}").startswith("error:")
