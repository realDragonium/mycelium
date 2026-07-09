"""Regular English plural generation for entity names.

Per the operator's decision, a regular plural is auto-generated and
stored as a separate name row when a name is created, so the exact-match
mention matcher (`mycelium.mentions`) catches both "statement" and
"statements" without any match-time stemming. Irregular plurals
("person"→"people", "datum"→"data") are NOT guessed here — they are
added by hand as ordinary aliases.

Pure function of the input string. Deliberately CONSERVATIVE: it returns
`None` rather than risk a wrong form, because a bad plural would be a
permanent, globally-unique name row. The caller skips generation on
`None` (and also skips when the form collides with an existing name).

Rules (applied to the last whitespace-separated word, so "data point"
→ "data points"):
  - ends in a word already looking plural (a lone trailing "s", e.g.
    "results", "status") → None (ambiguous singular/plural; let a human
    alias it rather than emit "resultses")
  - ends in "ss" / "x" / "z" / "ch" / "sh" (sibilants) → +"es"
  - consonant + "y" → "ies"
  - otherwise → +"s"
"""

from __future__ import annotations


def _pluralize_word(word: str) -> str | None:
    if not word or not word[-1].isalpha():
        return None
    lower = word.lower()
    if lower.endswith("ss"):  # boss → bosses, class → classes
        return word + "es"
    if lower.endswith("s"):  # bus / results / status — ambiguous, skip
        return None
    if lower.endswith(("x", "z", "ch", "sh")):  # box→boxes, church→churches
        return word + "es"
    if lower.endswith("y") and len(word) >= 2 and lower[-2] not in "aeiou":
        return word[:-1] + "ies"  # company → companies (consonant + y)
    return word + "s"  # statement → statements, day → days, API → APIs


def regular_plural(name: str) -> str | None:
    """The regular plural of `name`, or `None` when no confident regular
    form exists (already plural, ends in a non-letter, empty). Pluralizes
    the last word so multi-word names ("link type") inflect their
    head noun ("link types")."""
    stripped = name.strip()
    if not stripped:
        return None
    parts = stripped.split(" ")
    plural_last = _pluralize_word(parts[-1])
    if plural_last is None or plural_last == parts[-1]:
        return None
    parts[-1] = plural_last
    return " ".join(parts)
