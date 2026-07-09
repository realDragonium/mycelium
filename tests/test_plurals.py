"""Unit tests for regular plural generation (`mycelium.plurals`)."""

from __future__ import annotations

import pytest

from mycelium.plurals import regular_plural


@pytest.mark.parametrize(
    "singular,expected",
    [
        ("candidate", "candidates"),  # default +s
        ("flow", "flows"),
        ("day", "days"),  # vowel + y → +s
        ("key", "keys"),
        ("box", "boxes"),  # x → es
        ("church", "churches"),  # ch → es
        ("dish", "dishes"),  # sh → es
        ("buzz", "buzzes"),  # z → es
        ("class", "classes"),  # ss → es
        ("company", "companies"),  # consonant + y → ies
        ("policy", "policies"),
        ("link type", "link types"),  # multi-word: head noun
        ("data point", "data points"),
        ("Statement", "Statements"),  # casing of stem preserved
        ("API", "APIs"),  # acronym
    ],
)
def test_regular_plurals(singular, expected):
    assert regular_plural(singular) == expected


@pytest.mark.parametrize(
    "word",
    [
        "results",  # already plural-looking (trailing s) — skip
        "status",
        "bus",  # singular ending in s, but ambiguous — skip rather than risk
        "",  # empty
        "   ",  # whitespace only
        "C++",  # ends in non-letter
    ],
)
def test_no_confident_plural_returns_none(word):
    assert regular_plural(word) is None
