"""Tests of the graph's roles and their dict form."""

from __future__ import annotations

import pytest

from ddviz.server.encoding import Encoding


def test_dict_round_trip() -> None:
    """An encoding survives `to_dict` and `from_dict`; missing roles are empty."""
    encoding = Encoding(x=("a",), y=("b", "c"), color="g", col="h")
    assert Encoding.from_dict(encoding.to_dict()) == encoding
    assert Encoding.from_dict({}) == Encoding()


def test_symbol_is_a_role_of_its_own() -> None:
    """The symbol role takes a column name and keeps it in its dict form."""
    encoding = Encoding.from_dict({"x": ["a"], "y": ["b"], "symbol": "o"})
    assert encoding.symbol == "o"
    assert encoding.to_dict()["symbol"] == "o"


def test_columns_lists_each_placed_column_once() -> None:
    """A column on several roles is listed once, in role order."""
    encoding = Encoding(x=("a",), y=("b", "a"), color="g", symbol="o", row="g")
    assert encoding.columns() == ["a", "b", "g", "o"]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"z": "a"}, "unknown roles"),
        ({"overlay": "a"}, "unknown roles"),
        ({"x": "a"}, "x must be a list"),
        ({"y": [1]}, "y must be a list"),
        ({"color": ["a"]}, "color must be a column name"),
        ({"wrap": 1}, "wrap must be a column name"),
        ({"elements": []}, "elements must be"),
        ({"elements": ["bars"]}, "elements must be"),
        ({"elements": "points"}, "elements must be"),
    ],
)
def test_from_dict_refuses_bad_roles(data: dict, message: str) -> None:
    """Unknown roles and values of the wrong type are refused."""
    with pytest.raises(ValueError, match=message):
        Encoding.from_dict(data)


def test_elements_default_to_points_in_their_order() -> None:
    """Missing elements are points; the elements given are kept once, in the order of ELEMENTS."""
    assert Encoding.from_dict({}).elements == ("points",)
    chosen = Encoding.from_dict({"elements": ["smooth", "points", "smooth"]})
    assert chosen.elements == ("points", "smooth")
    assert chosen.to_dict()["elements"] == ["points", "smooth"]
