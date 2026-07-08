"""Unit tests for the deterministic mention matcher (`mycelium.mentions`).

Pure logic — no DB, no server. Names are supplied as `(name_id, entity_id,
text)` tuples and matched against plain strings.
"""

from __future__ import annotations

from mycelium import mentions
from mycelium.mentions import build_index, is_suspect_name, match_text


def _ids(items) -> set[str]:
    return {m.name_id for m in items}


def _entities(items) -> set[str]:
    return {m.entity_id for m in items}


# ─── tokenization / word-boundary matching ──────────────────────────────────


def test_single_token_match():
    index = build_index([("n1", "e1", "Candidate")])
    result = match_text("The candidate applied today", index)
    assert _ids(result.mentions) == {"n1"}
    assert result.suspects == []


def test_substring_does_not_match():
    # "result" must not match inside "resultant" — token boundaries, not substrings.
    index = build_index([("n1", "e1", "result")], suspect=lambda _t: False)
    assert match_text("the resultant value", index).mentions == []
    # And it DOES match the standalone word.
    assert _ids(match_text("the result value", index).mentions) == {"n1"}


def test_multiword_name_matches_consecutive_run_only():
    index = build_index([("n1", "e1", "assessment part")], suspect=lambda _t: False)
    assert _ids(match_text("the assessment part is scored", index).mentions) == {"n1"}
    # Non-consecutive tokens do not match.
    assert match_text("the assessment of the part", index).mentions == []


def test_case_and_unicode_normalization():
    index = build_index([("n1", "e1", "Candidate")])
    assert _ids(match_text("CANDIDATE", index).mentions) == {"n1"}
    # Curly apostrophe / fancy dash fold the same on both sides.
    index2 = build_index([("n2", "e2", "drag-and-drop")], suspect=lambda _t: False)
    assert _ids(match_text("uses drag—and—drop here", index2).mentions) == {"n2"}


# ─── maximal munch / overlap resolution ──────────────────────────────────────


def test_assessment_part_result_overlap():
    # The named case: the 3-token span suppresses both shorter spans within it.
    index = build_index(
        [
            ("long", "e_long", "assessment part result"),
            ("mid", "e_mid", "assessment part"),
            ("short", "e_short", "result"),
        ],
        suspect=lambda _t: False,  # isolate overlap logic from suspect logic
    )
    result = match_text("the assessment part result was recorded", index)
    assert _ids(result.mentions) == {"long"}
    assert _entities(result.mentions) == {"e_long"}


def test_leftmost_breaks_length_tie():
    # Two equal-length spans overlap; the leftmost claims its tokens first.
    index = build_index(
        [("ab", "e_ab", "alpha beta"), ("bc", "e_bc", "beta gamma")],
        suspect=lambda _t: False,
    )
    result = match_text("alpha beta gamma", index)
    assert _ids(result.mentions) == {"ab"}


def test_nonoverlapping_matches_all_kept():
    index = build_index(
        [("a", "e_a", "alpha"), ("c", "e_c", "gamma")],
        suspect=lambda _t: False,
    )
    result = match_text("alpha then gamma", index)
    assert _ids(result.mentions) == {"a", "c"}


def test_longer_match_starting_later_wins():
    # Locks GLOBAL maximal munch against a naive left-to-right regression: the
    # 3-token name starts one token later than the 2-token name but still wins.
    index = build_index(
        [("short", "e_s", "alpha beta"), ("long", "e_l", "beta gamma delta")],
        suspect=lambda _t: False,
    )
    result = match_text("alpha beta gamma delta", index)
    assert _ids(result.mentions) == {
        "long"
    }  # "alpha beta" suppressed, not just deferred


def test_prefix_name_of_different_entity_is_shadowed():
    # "data" (entity A) is the head word of "data science" (entity B). When the
    # longer name is present it wins and A is dropped (not queued) by maximal
    # munch; "data" still links A when it stands alone. Intended behavior.
    index = build_index(
        [("a", "e_a", "data"), ("b", "e_b", "data science")],
        suspect=lambda _t: False,
    )
    shadowed = match_text("the data science team", index)
    assert _entities(shadowed.mentions) == {"e_b"}
    assert shadowed.suspects == []
    alone = match_text("the data team", index)
    assert _entities(alone.mentions) == {"e_a"}


# ─── dedup to entity ──────────────────────────────────────────────────────────


def test_dedup_to_entity_two_names_one_mention():
    # Two distinct names of the SAME entity both hit → exactly one mention.
    index = build_index(
        [("n1", "e1", "candidate"), ("n2", "e1", "applicant")],
        suspect=lambda _t: False,
    )
    result = match_text("the candidate is also called an applicant", index)
    assert _entities(result.mentions) == {"e1"}
    assert len(result.mentions) == 1


def test_plural_stored_as_separate_name():
    # Plurals are separate name rows; the matcher stays pure exact-match.
    index = build_index(
        [("sing", "e1", "candidate"), ("plur", "e1", "candidates")],
        suspect=lambda _t: False,
    )
    # Plural form alone links the entity.
    r1 = match_text("five candidates applied", index)
    assert _entities(r1.mentions) == {"e1"}
    assert len(r1.mentions) == 1
    # Singular and plural together still collapse to one mention for the entity.
    r2 = match_text("a candidate among the candidates", index)
    assert _entities(r2.mentions) == {"e1"}
    assert len(r2.mentions) == 1


# ─── suspect detection + suppression ──────────────────────────────────────────


def test_is_suspect_name_predicate():
    assert is_suspect_name("flow") is True  # short single token
    assert is_suspect_name("result") is True  # 6 chars, at threshold
    assert is_suspect_name("the") is True  # stopword
    assert is_suspect_name("candidate") is False  # long single token
    assert is_suspect_name("assessment part") is False  # multi-token
    assert is_suspect_name("android") is False  # 7 chars, over threshold


def test_is_suspect_name_flags_verb_participles():
    # Verb / past-participle names match the verb, not the entity — a status
    # "Rejected" hits "a webhook is rejected" — so they are suspect regardless
    # of length and routed to review.
    assert is_suspect_name("rejected") is True
    assert is_suspect_name("declined") is True
    assert is_suspect_name("accepted") is True
    # Long nouns that don't end in -ed stay distinctive.
    assert is_suspect_name("participant") is False
    assert is_suspect_name("indicator") is False
    # The -ed test is single-token only; a multi-word name stays distinctive.
    assert is_suspect_name("assessment completed") is False


def test_suspect_alone_is_queued_not_linked():
    index = build_index([("n1", "e1", "flow")])  # default rule → suspect
    result = match_text("the flow continues", index)
    assert result.mentions == []
    assert _ids(result.suspects) == {"n1"}
    occ = result.suspects[0]
    assert occ.entity_id == "e1"
    assert "flow" == "the flow continues"[occ.start : occ.end]


def test_suspect_within_claimed_span_is_dropped_not_queued():
    # "result" is suspect, but it falls inside the distinctive 3-token span,
    # so it is consumed and neither linked nor queued.
    index = build_index(
        [
            ("long", "e_long", "assessment part result"),  # distinctive (multi-token)
            ("susp", "e_susp", "result"),  # suspect (short single token)
        ]
    )
    result = match_text("the assessment part result here", index)
    assert _ids(result.mentions) == {"long"}
    assert result.suspects == []  # suspect "result" was suppressed, not queued


def test_distinctive_hit_suppresses_entity_suspect_queue():
    # Same entity reached by a distinctive name AND a suspect name at different
    # positions → auto-linked once, suspect occurrence NOT queued.
    index = build_index(
        [
            ("dist", "e1", "candidate pipeline"),  # distinctive
            ("susp", "e1", "flow"),  # suspect, same entity
        ]
    )
    result = match_text("the candidate pipeline drives the flow", index)
    assert _entities(result.mentions) == {"e1"}
    assert len(result.mentions) == 1
    assert result.suspects == []


def test_same_span_collision_distinctive_co_mentions_both_entities():
    # Two DIFFERENT entities whose names fold to the same span ("Result" vs
    # "result") must both surface — neither is silently dropped.
    index = build_index(
        [("na", "e_a", "Result"), ("nb", "e_b", "result")],
        suspect=lambda _t: False,
    )
    result = match_text("the result was final", index)
    assert _entities(result.mentions) == {"e_a", "e_b"}
    assert len(result.mentions) == 2


def test_same_span_collision_suspect_both_queued():
    # Same collision, but both names are suspect → both occurrences queued, so
    # a human can review each entity. Neither is swallowed.
    index = build_index([("na", "e_a", "Flow"), ("nb", "e_b", "flow")])
    result = match_text("the flow runs", index)
    assert result.mentions == []
    assert _entities(result.suspects) == {"e_a", "e_b"}
    assert len(result.suspects) == 2


def test_same_span_collision_distinctive_plus_suspect():
    # One entity's name is distinctive, the other's folds to the same span but
    # is suspect → the distinctive one auto-links, the suspect one is queued.
    index = build_index(
        [("dist", "e_a", "Result"), ("susp", "e_b", "result")],
        # only the lowercase one is suspect; the capitalized alias is "distinctive"
        suspect=lambda t: t == "result",
    )
    result = match_text("the result was final", index)
    assert _entities(result.mentions) == {"e_a"}
    assert _entities(result.suspects) == {"e_b"}


def test_distinct_suspect_names_each_queued_once():
    index = build_index([("f", "e1", "flow"), ("r", "e2", "result")])
    # Same suspect word twice → still one occurrence for that (statement, name).
    result = match_text("flow then flow then result", index)
    assert result.mentions == []
    assert _ids(result.suspects) == {"f", "r"}
    assert len(result.suspects) == 2


# ─── offsets & empties ────────────────────────────────────────────────────────


def test_match_offsets_point_into_original_text():
    text = "the Candidate applied"
    index = build_index([("n1", "e1", "candidate")])
    m = match_text(text, index).mentions[0]
    assert text[m.start : m.end] == "Candidate"  # original casing preserved


def test_empty_and_no_match():
    index = build_index([("n1", "e1", "candidate")])
    assert match_text("", index) == mentions.MatchResult(mentions=[], suspects=[])
    assert match_text("nothing relevant here", index).mentions == []


def test_name_with_no_word_chars_is_skipped():
    index = build_index([("n1", "e1", "!!!"), ("n2", "e2", "candidate")])
    assert "n1" not in {ix.name_id for bucket in index.values() for ix in bucket}
    assert _ids(match_text("the candidate", index).mentions) == {"n2"}
