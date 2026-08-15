from mycelium import phrasing
from mycelium.connect import segment as seg


def fragment_texts(result):
    return [fragment.text for fragment in result.fragments]


# ─── conditionals ───────────────────────────────────────────────────────────


def test_initial_on_condition_produces_requires_proposal():
    result = seg.segment("On any Tuesday, he likes to eat pizza")

    assert [(item.text, item.role) for item in result.fragments] == [
        ("any Tuesday", "condition"),
        ("he likes to eat pizza", "claim"),
    ]
    assert len(result.cuts) == 1
    assert result.cuts[0].kind == "conditional"
    assert result.cuts[0].connective == "On"
    assert result.proposals == [seg.ConditionProposal(claim=1, condition=0, cue="On")]


def test_initial_when_condition_produces_requires_proposal():
    result = seg.segment("When the invite is sent, a reminder is scheduled")

    assert fragment_texts(result) == [
        "the invite is sent",
        "a reminder is scheduled",
    ]
    assert result.proposals == [seg.ConditionProposal(claim=1, condition=0, cue="When")]


def test_trailing_condition_preserves_reading_order():
    result = seg.segment("A reminder is scheduled when the invite is sent")

    assert fragment_texts(result) == [
        "A reminder is scheduled",
        "the invite is sent",
    ]
    assert [item.role for item in result.fragments] == ["claim", "condition"]
    assert result.proposals == [seg.ConditionProposal(claim=0, condition=1, cue="when")]


def test_causal_clause_cuts_without_requires_proposal():
    result = seg.segment("Because the token expired, the request is rejected")

    assert len(result.cuts) == 1
    assert any(item.role == "condition" for item in result.fragments)
    assert result.proposals == []


def test_unlisted_fronted_condition_keeps_opener_verbatim():
    result = seg.segment("Given the flag is set, the job runs")

    assert fragment_texts(result) == ["Given the flag is set", "the job runs"]
    assert [item.role for item in result.fragments] == ["condition", "claim"]


# ─── coordination and lexical cuts ──────────────────────────────────────────


def test_subject_is_projected_onto_subjectless_conjunct():
    result = seg.segment("The user logs in and receives a token")

    assert fragment_texts(result) == [
        "The user logs in",
        "The user receives a token",
    ]
    assert [item.subject_copied for item in result.fragments] == [False, True]
    assert len(result.cuts) == 1
    assert result.cuts[0].kind == "coordination"
    assert result.cuts[0].connective == "and"
    assert result.proposals == []


def test_conjunct_with_own_subject_is_not_projected():
    result = seg.segment("An invite is created and a notification email is sent")

    assert fragment_texts(result) == [
        "An invite is created",
        "a notification email is sent",
    ]
    assert not any(item.subject_copied for item in result.fragments)


def test_coordinated_nouns_are_not_split():
    result = seg.segment("apples and oranges are listed")

    assert fragment_texts(result) == ["apples and oranges are listed"]
    assert result.cuts == []


def test_semicolon_produces_two_fragments():
    result = seg.segment("The job runs; the report is sent")

    assert fragment_texts(result) == ["The job runs", "the report is sent"]
    assert len(result.cuts) == 1
    assert result.cuts[0].kind == "semicolon"


def test_compound_phrase_isolated_verbatim():
    result = seg.segment("The invite is sent and then a reminder is scheduled")

    assert fragment_texts(result) == [
        "The invite is sent",
        "a reminder is scheduled",
    ]
    assert len(result.cuts) == 1
    assert result.cuts[0].kind == "compound-phrase"
    assert result.cuts[0].connective == "and then"


# ─── blocks, offsets, and cleanup ────────────────────────────────────────────


def test_intro_and_bullet_items_are_separate_sentence_units():
    source = (
        "Next steps:\n"
        "- Send the invite\n"
        "* Schedule a reminder\n"
        "3) Archive the request\n"
    )
    result = seg.segment(source)
    items = result.fragments[1:]

    assert fragment_texts(result) == [
        "Next steps:",
        "Send the invite",
        "Schedule a reminder",
        "Archive the request",
    ]
    assert len({item.sentence for item in items}) == 3
    for item in items:
        raw = source[item.span[0] : item.span[1]]
        assert item.text in raw


def test_unsplittable_nested_clause_remnant_is_marked():
    source = "The service starts and records the time when the token expires"
    result = seg.segment(source)
    remnant = next(item for item in result.fragments if "records the time" in item.text)

    assert remnant.text == "The service records the time when the token expires"
    assert remnant.unsplit is True
    assert phrasing.atomicity_violations(remnant.text)


def test_clean_claim_fragments_clear_atomicity_categories():
    sources = (
        "On any Tuesday, he likes to eat pizza",
        "When the invite is sent, a reminder is scheduled",
        "A reminder is scheduled when the invite is sent",
        "The user logs in and receives a token",
        "The job runs; the report is sent",
    )
    for source in sources:
        for fragment in seg.segment(source).fragments:
            if fragment.role != "claim":
                continue
            categories = {
                item["category"] for item in phrasing.check(fragment.text, "event")
            }
            assert categories.isdisjoint({"compound", "precondition_in_text"})


def test_all_cut_spans_round_trip_to_connectives():
    sources = (
        "On any Tuesday, he likes to eat pizza",
        "When the invite is sent, a reminder is scheduled",
        "A reminder is scheduled when the invite is sent",
        "The user logs in and receives a token",
        "An invite is created and a notification email is sent",
        "apples and oranges are listed",
        "The job runs; the report is sent",
        "The invite is sent and then a reminder is scheduled",
        "Because the token expired, the request is rejected",
        "The service starts and records the time when the token expires",
        "Given the flag is set, the job runs",
    )
    for source in sources:
        for cut in seg.segment(source).cuts:
            assert source[cut.span[0] : cut.span[1]] == cut.connective


def test_empty_and_whitespace_only_input_return_empty_segmentation():
    for source in ("", " \n\t "):
        assert seg.segment(source) == seg.Segmentation([], [], [])
