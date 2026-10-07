"""The user guide (docs/getting-started.md) and the docstrings list every parameter and reset option,
and nothing that does not exist."""

import inspect
import re
from pathlib import Path

import pytest

from spelunky2rl.engine.core import SpelunkyRLEngine

GUIDE = Path(__file__).parents[2] / "docs" / "getting-started.md"


def table_names(heading):
    """The names in the first column of the first table under `heading`."""
    section = GUIDE.read_text().split(f"\n{heading}\n", 1)[1]
    names, in_table = [], False
    for line in section.splitlines():
        if line.startswith("|"):
            in_table = True
            match = re.match(r"\|\s*`(\w+)`", line)
            if match:
                names.append(match.group(1))
        elif in_table:
            break
    return names


def init_parameters():
    return [name for name, p in inspect.signature(SpelunkyRLEngine.__init__).parameters.items()
            if name != "self" and p.kind is not p.VAR_KEYWORD]


def reset_options():
    return [name for name in inspect.signature(SpelunkyRLEngine._game_reset).parameters
            if name not in ("self", "seed")]


@pytest.mark.parametrize("heading, names", [
    ("## Creating an environment", init_parameters),
    ("## Reset options", reset_options),
])
def test_the_guide_tables_match_the_code(heading, names):
    listed = table_names(heading)
    assert len(listed) == len(set(listed)), f"listed twice under {heading}"
    assert sorted(listed) == sorted(names())


def test_the_docstrings_list_every_option():
    init = inspect.getdoc(SpelunkyRLEngine.__init__)
    assert all(re.search(rf"^\s*{name}:", init, re.M) for name in init_parameters())
    reset = inspect.getdoc(SpelunkyRLEngine.reset)
    assert all(re.search(rf"\b{name} \(", reset) for name in reset_options())
