"""The fields an env can ask for and the binary game states (engine/fields.py, engine/protocol.py)."""

import numpy as np
import pytest

from fake_lua import BASIC, layout_for, make_gamestate, pack_state
from spelunky2rl.engine.fields import resolve_fields
from spelunky2rl.engine.protocol import ProtocolError, StateLayout
from spelunky2rl.envs.get_to_exit import SpelunkyEnv as GetToExit

ALL = resolve_fields(["map_info", "entity_info", "dist_to_goal"])


def roundtrip(fields, **kwargs):
    gamestate = make_gamestate(np.random.default_rng(0), fields=fields, **kwargs)
    layout = layout_for(fields)
    return gamestate, StateLayout(layout).decode(bytearray(pack_state(layout, gamestate)))


def test_names_get_the_default_view():
    assert resolve_fields(["map_info", "dist_to_goal"]) == [
        {"name": "map_info", "width": 21, "height": 11}, {"name": "dist_to_goal"}]


def test_parameters_override_the_defaults():
    assert resolve_fields({"map_info": {"width": 41}, "entity_info": {}}) == [
        {"name": "map_info", "width": 41, "height": 11}, {"name": "entity_info", "width": 21, "height": 11}]


@pytest.mark.parametrize("data_to_send, match", [
    (["map_info", "custom_info"], "Unknown field 'custom_info'"),
    ({"map_info": {"size": 3}}, "Unknown parameter size"),
    ({"dist_to_goal": {"width": 3}}, "Unknown parameter width"),
    ({"map_info": {"width": 20}}, "odd integer"),
    ({"entity_info": {"height": 0}}, "odd integer"),
    ({"map_info": {"height": 5.0}}, "odd integer"),
])
def test_wrong_fields_are_rejected(data_to_send, match):
    with pytest.raises(ValueError, match=match):
        resolve_fields(data_to_send)


def test_a_single_name_is_not_a_list_of_names():
    with pytest.raises(TypeError, match="string"):
        resolve_fields("map_info")


def test_wrong_fields_fail_before_launching_the_game():
    class Env(GetToExit):
        data_to_send = ["map_info", "custom_info"]

    with pytest.raises(ValueError, match="custom_info"):
        Env(launcher="no launcher is made")


def test_states_decode_to_the_values_sent():
    sent, got = roundtrip(ALL)
    assert got.keys() == sent.keys()
    assert got["basic_info"] == sent["basic_info"]
    assert got["dist_to_goal"] == sent["dist_to_goal"]
    assert np.array_equal(got["map_info"], sent["map_info"]) and got["map_info"].dtype == np.int32
    assert np.array_equal(got["entity_info"], sent["entity_info"]) and got["entity_info"].shape == (3, 7)


def test_basic_info_has_python_types():
    _, got = roundtrip(ALL)
    info = got["basic_info"]
    assert [key for key, *_ in BASIC] == list(info)
    assert type(info["x"]) is float and type(info["health"]) is int
    assert type(info["can_jump"]) is bool and type(info["face_left"]) is bool
    assert info["powerups"] == [0] * 18
    assert type(got["dist_to_goal"]) is int


def test_any_view_size():
    fields = resolve_fields({"map_info": {"width": 41, "height": 3}, "entity_info": {"width": 5, "height": 5}})
    _, got = roundtrip(fields)
    assert got["map_info"].shape == (3, 41)


def test_no_entities_is_an_empty_table():
    gamestate = make_gamestate(np.random.default_rng(0), fields=ALL)
    gamestate["entity_info"] = np.zeros((0, 7))
    layout = layout_for(ALL)
    got = StateLayout(layout).decode(bytearray(pack_state(layout, gamestate)))
    assert got["entity_info"].shape == (0, 7)


def test_arrays_can_be_changed_in_place():
    _, got = roundtrip(ALL)
    got["map_info"][0, 0] = 5


@pytest.mark.parametrize("change", [lambda data: data[:-1], lambda data: data + b"\0"])
def test_a_state_that_does_not_match_its_layout_is_an_error(change):
    gamestate = make_gamestate(np.random.default_rng(0), fields=ALL)
    layout = layout_for(ALL)
    with pytest.raises(ProtocolError):
        StateLayout(layout).decode(bytearray(change(pack_state(layout, gamestate))))


def test_an_unreadable_layout_is_an_error():
    with pytest.raises(ProtocolError, match="layout"):
        StateLayout([{"name": "map_info", "dtype": "not a dtype", "shape": [1]}])
