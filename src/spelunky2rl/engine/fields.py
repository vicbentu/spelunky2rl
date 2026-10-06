"""The fields an environment can ask the mod for (`data_to_send`), with their parameters.

`basic_info` always comes; these are the extra ones. Each maps parameter -> default. The mod computes
them (mod/lua/spelunky2rl/observations.lua) and describes their types in the reset answer.
"""

from typing import Any, Dict, List, Mapping, Sequence, Union

# The view around the player that map_info and entity_info cover: odd sizes, centred on the player
VIEW = {"width": 21, "height": 11}

FIELDS: Dict[str, Dict[str, Any]] = {
    "map_info": VIEW,      # tile types, `height` rows from top to bottom by `width` columns
    "entity_info": VIEW,   # one row per entity in the view: dx, dy, vel_x, vel_y, type, face_left, held type
    "dist_to_goal": {},    # cells from the player to the nearest exit
}

DataToSend = Union[Sequence[str], Mapping[str, Mapping[str, Any]]]


def resolve_fields(data_to_send: DataToSend) -> List[Dict[str, Any]]:
    """The fields of `data_to_send` as the reset message carries them: [{"name": ..., **parameters}],
    with defaults filled in. `data_to_send` is a list of names or {name: {parameter: value}}."""
    if isinstance(data_to_send, str):
        raise TypeError(f"data_to_send must be a list of field names or a dict, got the string {data_to_send!r}")
    requested = dict(data_to_send) if isinstance(data_to_send, Mapping) else {name: {} for name in data_to_send}

    fields = []
    for name, params in requested.items():
        if name not in FIELDS:
            raise ValueError(f"Unknown field {name!r} in data_to_send. Known: {', '.join(FIELDS)}")
        params = dict(params or {})
        unknown = sorted(set(params) - set(FIELDS[name]))
        if unknown:
            known = ", ".join(FIELDS[name]) or "none"
            raise ValueError(f"Unknown parameter {', '.join(unknown)} for field {name!r}. Known: {known}")
        field = {"name": name, **FIELDS[name], **params}
        for size in ("width", "height"):
            if size in field:
                value = field[size]
                if not isinstance(value, int) or isinstance(value, bool) or value < 1 or value % 2 == 0:
                    raise ValueError(f"{name} {size} must be an odd integer >= 1 (the view is centred "
                                     f"on the player), got {value!r}")
        fields.append(field)
    return fields
