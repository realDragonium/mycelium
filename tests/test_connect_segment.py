from mycelium import phrasing, store
from mycelium.connect import segment as seg


def fragment_texts(result):
    return [fragment.text for fragment in result.fragments]


def seeded_alias_lookup():
    conn = store.connect(":memory:")
    store.migrate(conn)
    try:
        return store.alias_lookup(conn)
    finally:
        conn.close()


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


def test_trailing_once_condition_uses_strip_table_vocabulary():
    result = seg.segment("The job runs once the flag is set")

    assert fragment_texts(result) == ["The job runs", "the flag is set"]
    assert [item.role for item in result.fragments] == ["claim", "condition"]
    assert result.proposals == [seg.ConditionProposal(claim=0, condition=1, cue="once")]


def test_trailing_multiword_condition_uses_textual_fallback():
    result = seg.segment("The job runs as soon as the flag is set")

    assert [(item.text, item.role) for item in result.fragments] == [
        ("The job runs", "claim"),
        ("the flag is set", "condition"),
    ]
    assert len(result.cuts) == 1
    assert result.cuts[0].kind == "conditional"
    assert result.cuts[0].connective == "as soon as"
    assert result.proposals == [
        seg.ConditionProposal(claim=0, condition=1, cue="as soon as")
    ]


def test_trailing_provided_that_condition_uses_textual_fallback():
    result = seg.segment("The job runs provided that the flag is set")

    assert [(item.text, item.role) for item in result.fragments] == [
        ("The job runs", "claim"),
        ("the flag is set", "condition"),
    ]
    assert result.cuts[0].connective == "provided that"
    assert result.proposals == [
        seg.ConditionProposal(claim=0, condition=1, cue="provided that")
    ]


def test_comparative_multiword_opener_without_right_clause_is_not_cut():
    source = "The timeout is as long as the interval"
    result = seg.segment(source)

    assert fragment_texts(result) == [source]
    assert result.cuts == []
    assert result.proposals == []


def test_if_then_conditional_outranks_the_phrase_cut():
    result = seg.segment("If the flag is set, then the job runs")

    assert [(item.text, item.role) for item in result.fragments] == [
        ("the flag is set", "condition"),
        ("then the job runs", "claim"),
    ]
    assert [item.kind for item in result.cuts] == ["conditional"]
    assert result.proposals == [seg.ConditionProposal(claim=1, condition=0, cue="If")]


def test_medial_clause_is_left_whole_and_flagged():
    source = "The invite, if the flag is set, is sent to the user"
    result = seg.segment(source)

    assert fragment_texts(result) == [source]
    assert result.cuts == []
    assert result.fragments[0].unsplit is True


def test_causal_clause_cuts_without_requires_proposal():
    result = seg.segment("Because the token expired, the request is rejected")

    assert fragment_texts(result) == [
        "Because the token expired",
        "the request is rejected",
    ]
    assert result.fragments[0].role == "condition"
    assert result.fragments[0].unsplit is True
    assert result.proposals == []
    assert len(result.cuts) == 1
    assert result.cuts[0].connective == "Because"


def test_openerless_comma_splice_keeps_both_sides_as_claims():
    result = seg.segment("Given the flag is set, the job runs")

    assert fragment_texts(result) == ["Given the flag is set", "the job runs"]
    assert [item.role for item in result.fragments] == ["claim", "claim"]
    assert result.cuts[0].kind == "comma-splice"
    assert result.proposals == []


def test_condition_with_internal_commas_survives_whole():
    result = seg.segment(
        "If the report contains apples, bananas, and oranges, publish it."
    )

    assert fragment_texts(result) == [
        "the report contains apples, bananas, and oranges",
        "publish it",
    ]
    assert result.proposals == [seg.ConditionProposal(claim=1, condition=0, cue="If")]


def test_initial_condition_without_comma_uses_parse_boundary():
    result = seg.segment("If the flag is set the job runs")

    assert fragment_texts(result) == ["the flag is set", "the job runs"]


def test_multiword_initial_opener_survives_parse_boundary():
    result = seg.segment("As soon as the flag is set, the job runs")

    assert fragment_texts(result) == ["the flag is set", "the job runs"]
    assert result.proposals == [
        seg.ConditionProposal(claim=1, condition=0, cue="As soon as")
    ]


def test_nonfinite_fronted_clause_is_left_whole():
    result = seg.segment("As discussed yesterday, the service restarts")

    assert fragment_texts(result) == ["As discussed yesterday, the service restarts"]
    assert result.cuts == []
    assert result.proposals == []


def test_participial_fronted_clause_is_not_cut():
    result = seg.segment("Smiling broadly, the user enters")

    assert fragment_texts(result) == ["Smiling broadly, the user enters"]
    assert result.cuts == []
    assert result.proposals == []


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


def test_subjectless_imperative_conjunct_is_flagged():
    result = seg.segment("Log in and receive a token")

    assert fragment_texts(result) == ["Log in", "receive a token"]
    assert result.fragments[1].unsplit is True
    assert result.fragments[1].subject_copied is False


def test_subject_is_projected_across_compound_phrase():
    result = seg.segment("The user logs in and then receives a token")

    assert fragment_texts(result) == [
        "The user logs in",
        "The user receives a token",
    ]
    assert [item.subject_copied for item in result.fragments] == [False, True]
    assert len(result.cuts) == 1
    assert result.cuts[0].kind == "compound-phrase"
    assert result.cuts[0].connective == "and then"


def test_embedded_compound_phrase_remnant_is_flagged():
    result = seg.segment("The admin says the user logs in and then receives a token")

    remnant = next(item for item in result.fragments if item.text == "receives a token")
    assert remnant.unsplit is True


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


def test_embedded_coordination_is_not_split_and_is_flagged():
    result = seg.segment("The admin says the user logs in and receives a token.")

    assert fragment_texts(result) == [
        "The admin says the user logs in and receives a token"
    ]
    assert "The admin says" in result.fragments[0].text
    assert result.fragments[0].unsplit is True
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


def test_comma_then_promotes_a_standalone_clause():
    result = seg.segment("The draft is created, then an embedding is queued.")

    assert fragment_texts(result) == [
        "The draft is created",
        "an embedding is queued",
    ]
    assert [fragment.unsplit for fragment in result.fragments] == [False, False]


def test_comma_then_keeps_a_subjectless_remnant_flagged():
    result = seg.segment("The draft is created, then queued.")

    assert fragment_texts(result) == ["The draft is created", "queued"]
    assert result.fragments[1].unsplit is True


def test_comma_then_cut_resolves_only_with_aliases():
    source = "The invite is sent, then a reminder is scheduled"
    aliases = {"then": frozenset({("proceeds", "forward")})}

    resolved = seg.segment(source, aliases=aliases)
    unresolved = seg.segment(source)

    assert resolved.cuts[0].connective == ", then"
    assert resolved.cuts[0].link_type == "proceeds"
    assert unresolved.cuts[0].link_type is None


def test_coordination_cut_is_absent_from_seeded_aliases():
    aliases = seeded_alias_lookup()

    assert "and" not in aliases
    result = seg.segment("The user logs in and receives a token", aliases=aliases)
    assert result.cuts[0].link_type is None


def test_ambiguous_connective_alias_resolves_to_nothing():
    aliases = {"then": frozenset({("proceeds", "forward"), ("next", "forward")})}
    result = seg.segment(
        "The invite is sent, then a reminder is scheduled", aliases=aliases
    )

    assert result.cuts[0].link_type is None


def test_conditional_cut_is_absent_from_seeded_aliases():
    aliases = seeded_alias_lookup()
    result = seg.segment("If the flag is set, the job runs", aliases=aliases)

    assert "if" not in aliases
    assert result.cuts[0].connective == "If"
    assert result.cuts[0].link_type is None


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


def test_wrapped_list_line_extends_its_list_item():
    result = seg.segment("- Send the invite\n  after approval")

    assert len({item.sentence for item in result.fragments}) == 1
    assert len(result.fragments) == 1
    assert "Send the invite" in result.fragments[0].text
    assert "after approval" in result.fragments[0].text


def test_wrapped_list_item_normalizes_newlines_only_in_final_fragments():
    source = "- The draft is created and an\n  embedding is queued.\n"
    result = seg.segment(source)

    assert fragment_texts(result) == [
        "The draft is created",
        "an embedding is queued",
    ]
    assert all("\n" not in fragment.text for fragment in result.fragments)
    raw = source[result.fragments[1].span[0] : result.fragments[1].span[1]]
    assert raw == "an\n  embedding is queued"


def test_fragment_spans_match_their_retained_surface_text():
    sources = (
        "The job runs.",
        "The user logs in and receives a token.",
        "When the invite is sent, a reminder is scheduled.",
        "The user logs in and receives a token, according to the policy.",
    )
    for source in sources:
        for fragment in seg.segment(source).fragments:
            raw = source[fragment.span[0] : fragment.span[1]]
            if not fragment.subject_copied:
                assert raw == fragment.text
            else:
                assert fragment.text.endswith(raw)


def test_medial_material_blocks_the_coordination_cut():
    source = "The user logs in and receives a token, according to the policy"
    result = seg.segment(source)

    # Splitting here would splice "The user logs in" onto ", according to the
    # policy" and stretch that fragment's span over the removed conjunct.
    assert fragment_texts(result) == [source]
    assert result.cuts == []
    assert result.fragments[0].unsplit is True


def test_a_list_items_trailing_newline_does_not_block_the_coordination_cut():
    # The block keeps the item's newline, which parses as a SPACE token after
    # the final period; the same sentence on its own splits, so must this one.
    result = seg.segment("- The user logs in and receives a token.\n- Blue widgets.")

    assert fragment_texts(result) == [
        "The user logs in",
        "The user receives a token",
        "Blue widgets",
    ]


def test_case_folding_expansion_cannot_forge_a_strip_table_opener():
    # "ß" casefolds to "ss", so an opener matched against the folded text can
    # cover raw characters that are not the opener.
    result = seg.segment("as soon aß the flag is set, the job runs")

    assert [(item.text, item.role) for item in result.fragments] == [
        ("as soon aß the flag is set", "claim"),
        ("the job runs", "claim"),
    ]
    assert result.proposals == []


def test_each_working_text_is_parsed_once_per_segmentation(monkeypatch):
    nlp = phrasing.get_nlp()
    parsed: list[str] = []

    def counting(text):
        parsed.append(text)
        return nlp(text)

    monkeypatch.setattr(phrasing, "get_nlp", lambda: counting)
    source = "The service starts and records the time when the token expires"
    seg.segment(source)

    # Sentence splitting and every cutter at every recursion level ask for the
    # same working texts; the atomicity re-check parses normalized leaf text.
    assert parsed.count(source) == 1
    assert parsed.count("The service records the time when the token expires") == 1


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


def test_conditional_cut_ignores_a_registered_alias():
    result = seg.segment(
        "When the flag is set, the job runs",
        aliases={"when": frozenset({("requires", "forward")})},
    )

    assert result.cuts[0].link_type is None
    assert result.proposals


def test_coordination_cut_ignores_a_registered_alias():
    result = seg.segment(
        "The user logs in and receives a token",
        aliases={"and": frozenset({("proceeds", "forward")})},
    )

    assert result.cuts[0].link_type is None
