import pytest

from mycelium.require import require


def test_require_returns_value_unchanged():
    assert require(5, "n") == 5
    assert require("x", "s") == "x"
    assert require([1], "list") == [1]


def test_require_passes_through_falsey_non_none():
    # 0 / "" / [] are present — only None is missing.
    assert require(0, "zero") == 0
    assert require("", "empty") == ""
    assert require([], "list") == []


def test_require_raises_on_none():
    with pytest.raises(RuntimeError, match="widget unexpectedly missing"):
        require(None, "widget")
