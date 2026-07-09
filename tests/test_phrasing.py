from mycelium import phrasing

# ─── normalization ──────────────────────────────────────────────────────────


def test_normalize_lowercases_and_keeps_ascii():
    assert phrasing.normalize("User Logs In") == "user logs in"


def test_normalize_folds_curly_quotes():
    assert phrasing.normalize("user can’t log in") == "user can't log in"
    assert phrasing.normalize("“click” the button") == '"click" the button'


def test_normalize_folds_dash_variants():
    for dash in ("–", "—", "―", "‒", "−"):
        assert phrasing.normalize(f"a{dash}b") == "a-b"


def test_normalize_folds_nbsp_and_zero_width():
    # NBSP, narrow NBSP, zero-width space, ideographic space, regular tab
    assert phrasing.normalize("user\xa0must log​in　now") == "user must log in now"


def test_normalize_collapses_whitespace_runs():
    assert phrasing.normalize("user   must  log    in") == "user must log in"


def test_normalize_handles_ligature_via_nfkc():
    # ﬁ (U+FB01) decomposes to "fi"
    assert phrasing.normalize("ﬁrst") == "first"


def test_normalize_folds_eszett_via_casefold():
    # ß casefolds to ss
    assert phrasing.normalize("Straße") == "strasse"


# ─── positives: each pattern must fire ──────────────────────────────────────


def categories(violations):
    return [v["category"] for v in violations]


def matched(violations):
    return [v["matched_text"] for v in violations]


def test_compound_semicolon():
    v = phrasing.check("user logs in; session is created")
    assert "compound" in categories(v)


def test_compound_and_then():
    v = phrasing.check("user clicks login and then is redirected to dashboard")
    assert "compound" in categories(v)


def test_compound_and_also():
    v = phrasing.check("system sends email and also logs the event")
    assert "compound" in categories(v)


def test_compound_comma_then():
    v = phrasing.check("user submits the form, then waits for a response")
    assert "compound" in categories(v)


def test_rule_must():
    v = phrasing.check("user must verify their email before logging in")
    assert "rule_shaped" in categories(v)


def test_rule_must_not():
    v = phrasing.check("password must not contain whitespace")
    assert "rule_shaped" in categories(v)


def test_rule_should():
    v = phrasing.check("session should expire after timeout")
    assert "rule_shaped" in categories(v)


def test_rule_never():
    v = phrasing.check("password is never logged")
    assert "rule_shaped" in categories(v)


def test_rule_always():
    v = phrasing.check("response always includes a request id")
    assert "rule_shaped" in categories(v)


def test_possibility_modals_are_clean():
    # may / might / could / would describe a possibility, capability, or
    # hypothetical — there's no underlying statement for a rule statement
    # to link to, so they're treated as ordinary phrasing.
    for text in (
        "admin may delete any post",
        "user might be redirected",
        "system could fail under load",
        "admin would receive a notification",
    ):
        v = phrasing.check(text)
        assert "rule_shaped" not in categories(v), (
            f"unexpected rule_shaped for {text!r}"
        )


def test_sequencing_will():
    # "will" usually names a follow-up statement; it gets its own category
    # so the recommendation can point at split-and-link.
    v = phrasing.check(
        "user submits the form and the system will send a confirmation email"
    )
    assert "sequencing" in categories(v)


def test_can_variants_are_clean():
    # "can" and its negations describe a standalone capability — there is
    # no underlying statement for a permission/prohibition rule to link
    # to. Treated as ordinary phrasing.
    for text in (
        "multiple links can be added to a single statement",
        "user cannot delete their own posts",
        "guest can't access settings",
        "system can not write to readonly storage",
    ):
        v = phrasing.check(text)
        cats = categories(v)
        assert "rule_shaped" not in cats, f"unexpected rule_shaped for {text!r}: {cats}"


def test_rule_is_required_to():
    v = phrasing.check("user is required to enable 2FA")
    assert "rule_shaped" in categories(v)


def test_rule_is_allowed_to():
    v = phrasing.check("admin is allowed to bypass rate limits")
    assert "rule_shaped" in categories(v)


def test_rule_needs_to_has_to():
    for text in (
        "worker needs to acknowledge the job",
        "user has to confirm via email",
    ):
        v = phrasing.check(text)
        assert "rule_shaped" in categories(v), f"expected rule_shaped for {text!r}"


def test_property_is_a():
    v = phrasing.check("session is a short-lived authentication token")
    assert "property_shaped" in categories(v)


def test_property_is_an():
    v = phrasing.check("user is an account with credentials")
    assert "property_shaped" in categories(v)


def test_property_has_a():
    v = phrasing.check("user has a profile")
    assert "property_shaped" in categories(v)


def test_property_consists_of():
    v = phrasing.check("auth flow consists of login, verify, and redirect")
    assert "property_shaped" in categories(v)


def test_property_belongs_to():
    v = phrasing.check("project belongs to a workspace")
    assert "property_shaped" in categories(v)


def test_hedge_words():
    for text in (
        "user mostly clicks the home button",
        "session usually expires after 30 days",
        "request often fails on cold start",
        "server typically returns within 200ms",
        "system sometimes retries the upload",
        "users generally prefer dark mode",
        "in most cases the cache hit ratio is above 90%",
    ):
        v = phrasing.check(text)
        assert "hedge" in categories(v), f"expected hedge for {text!r}"


# ─── negatives: clean statements must NOT fire ──────────────────────────────


def test_clean_passive_event_with_is():
    # "is redirected" is passive voice for an event, not "is a / is required"
    assert phrasing.check("user is redirected to login") == []


def test_clean_passive_event_with_is_invalidated():
    assert phrasing.check("session token is invalidated on logout") == []


def test_clean_active_event():
    assert phrasing.check("user clicks the login button") == []
    assert phrasing.check("system sends a verification email") == []
    assert phrasing.check("service returns the cached response") == []


def test_clean_event_with_word_containing_must_substring():
    # "mustard" contains "must" but not as a word — \b should prevent match
    assert phrasing.check("user uploads mustard recipe") == []


def test_clean_event_with_word_containing_is_substring():
    # "island", "this", "history" — none should trigger \bis\s+an?\b
    for text in (
        "user navigates to the island page",
        "system updates this record",
        "user views their history",
    ):
        assert phrasing.check(text) == [], f"unexpected hit on {text!r}"


def test_clean_event_with_has_substring():
    # "phase", "hash" contain "has" but not as a word — \b should prevent match
    for text in (
        "system advances to the next phase",
        "service computes a hash of the payload",
    ):
        assert phrasing.check(text) == [], f"unexpected hit on {text!r}"


def test_clean_event_with_can_substring():
    # "scan", "candle" contain "can" but not as a word
    assert phrasing.check("system scans uploaded files") == []


def test_clean_and_in_compound_object():
    # bare " and " is allowed (lots of false positives) — only "and then",
    # "and also", and ", then" trigger
    assert phrasing.check("user enters email and password") == []


def test_clean_no_hedge_in_normal_word():
    # "often" is a word; "soften" contains it but not at boundary
    assert phrasing.check("system softens the rate limit gradually") == []


# ─── multi-violation ───────────────────────────────────────────────────────


def test_multiple_violations_in_one_text():
    text = "user must log in and then is required to confirm via email"
    v = phrasing.check(text)
    cats = categories(v)
    assert "rule_shaped" in cats  # must
    assert "compound" in cats  # and then
    # "is required to" is also rule_shaped
    assert cats.count("rule_shaped") >= 2


def test_violations_ordered_by_position():
    text = "user must log in and then is required to confirm"
    v = phrasing.check(text)
    positions = [item["position"] for item in v]
    assert positions == sorted(positions)


# ─── position fidelity: positions point into the ORIGINAL text ─────────────


def test_position_into_original_with_extra_whitespace():
    # double space should NOT shift the reported position relative to original
    text = "the  user  must  log  in"
    v = phrasing.check(text)
    must_hit = next(x for x in v if "must" in x["matched_text"].lower())
    assert text[must_hit["position"] : must_hit["position"] + len("must")] == "must"


def test_position_with_curly_quote_in_text():
    # spaCy splits "shouldn't" into separate tokens; the modal lemma=should
    # is detected and the position points into the original text past the
    # curly-quote-bearing region.
    text = "user shouldn’t do this"
    v = phrasing.check(text)
    rule_hit = next(x for x in v if x["category"] == "rule_shaped")
    assert text[rule_hit["position"]] == "s"


def test_position_with_uppercase():
    text = "USER MUST log in"
    v = phrasing.check(text)
    must_hit = next(x for x in v if x["category"] == "rule_shaped")
    # positions point into original text; matched_text preserves original case
    assert text[must_hit["position"] : must_hit["position"] + 4] == "MUST"


# ─── bypass-via-unicode resistance ──────────────────────────────────────────


def test_em_dash_does_not_hide_violation():
    # someone tries to slip "must" past by surrounding with em-dashes
    v = phrasing.check("user—must—log in")
    assert "rule_shaped" in categories(v)


def test_nbsp_does_not_hide_violation():
    # NBSP between "is" and "a" must still trigger property_shaped
    v = phrasing.check("session\xa0is\xa0a\xa0token")
    assert "property_shaped" in categories(v)


def test_uppercase_does_not_hide_violation():
    v = phrasing.check("USER MUST LOG IN")
    assert "rule_shaped" in categories(v)


def test_zero_width_space_does_not_hide_violation():
    v = phrasing.check("user m​ust log in")
    # Note: ZWSP inside a word DOES break the word-boundary match; this is
    # a known limitation. The test pins current statement.
    # If we later want to strip ZWSP entirely (rather than fold to space),
    # this test should be flipped to assert the violation IS caught.
    # For now: documents that ZWSP between letters slips past, but ZWSP
    # surrounded by spaces does not.
    _ = v  # statement unspecified for this edge case; do not assert


def test_full_width_chars_via_nfkc():
    # full-width Latin (ｕｓｅｒ ｍｕｓｔ) decomposes via NFKC to ASCII
    v = phrasing.check("ｕｓｅｒ ｍｕｓｔ ｌｏｇ ｉｎ")
    assert "rule_shaped" in categories(v)


# ─── edge cases ─────────────────────────────────────────────────────────────


def test_empty_text():
    assert phrasing.check("") == []


def test_whitespace_only_text():
    assert phrasing.check("   \t\n  ") == []


def test_violation_payload_shape():
    v = phrasing.check("user must log in")
    assert len(v) == 1
    item = v[0]
    assert set(item.keys()) == {
        "category",
        "matched_text",
        "position",
        "rule",
        "recommendation",
    }
    assert item["category"] == "rule_shaped"
    assert isinstance(item["position"], int)
    assert isinstance(item["rule"], str) and item["rule"]
    assert isinstance(item["recommendation"], str) and item["recommendation"]


# ─── spaCy-only: structural catches the regex version would miss ────────────


def test_obligation_modal_variants_caught_by_pos():
    # spaCy tags obligation modals as AUX with the right lemma — no
    # surface-string enumeration needed.
    for text in (
        "the response shall include a request id",
        "user ought to confirm via email",
    ):
        v = phrasing.check(text)
        assert "rule_shaped" in categories(v), f"expected rule_shaped for {text!r}"


def test_copula_variants_caught_by_pos():
    # "are a / was a / were an" — all forms of "be" + indefinite
    for text in (
        "sessions are a short-lived token",
        "the request was a duplicate",
        "users were an unverified set",
    ):
        v = phrasing.check(text)
        assert "property_shaped" in categories(v), (
            f"expected property_shaped for {text!r}"
        )


def test_clause_compound_without_explicit_phrase():
    # spaCy catches general clause coordination — not just "and then"
    v = phrasing.check("system retries the request and logs the failure")
    assert "compound" in categories(v)


def test_clause_compound_under_modal():
    # "must verify and submit" — two verbs under one modal
    v = phrasing.check("user must verify and submit the form")
    assert "compound" in categories(v)
    assert "rule_shaped" in categories(v)  # also catches "must"


# ─── precondition_in_text: SCONJ-driven, new category ───────────────────────


def test_precondition_when():
    v = phrasing.check("user logs in when 2FA is enabled")
    assert "precondition_in_text" in categories(v)


def test_precondition_before_after_while_until():
    for text in (
        "user verifies email before activating account",
        "session expires after 30 minutes",
        "spinner shows while the request is pending",
        "retry continues until the server responds",
    ):
        v = phrasing.check(text)
        assert "precondition_in_text" in categories(v), (
            f"expected precondition for {text!r}"
        )


def test_precondition_if_unless_because():
    for text in (
        "system retries if the request fails",
        "request is rejected unless the token is valid",
        "user is logged out because the session expired",
    ):
        v = phrasing.check(text)
        assert "precondition_in_text" in categories(v), (
            f"expected precondition for {text!r}"
        )


def test_precondition_recommendation_mentions_when_expression():
    v = phrasing.check("user logs in when 2FA is enabled")
    pre = next(x for x in v if x["category"] == "precondition_in_text")
    assert "`when`" in pre["recommendation"]


# ─── conservative: noun lists are NOT compound ──────────────────────────────


def test_noun_list_with_and_is_not_compound():
    # spaCy distinguishes coordinated noun lists from coordinated clauses
    for text in (
        "user enters email and password",
        "system receives a name and an address",
    ):
        v = phrasing.check(text)
        assert "compound" not in categories(v), f"unexpected compound on {text!r}"


def test_perfect_tense_has_is_not_property():
    # "has logged in" — has is AUX (perfect tense), not a property statement
    v = phrasing.check("user has logged in successfully")
    assert "property_shaped" not in categories(v)


# ─── universal quantifiers (every / all / each / any / everyone / ...) ─────


def test_universal_det_quantifier():
    for text in (
        "every user must verify email",
        "all requests are logged",
        "each session expires after timeout",
        "any admin can delete posts",
    ):
        v = phrasing.check(text)
        assert "universal_claim" in categories(v), (
            f"expected universal_claim for {text!r}"
        )


def test_no_determiner_is_allowed():
    # "no" can read as a universal ("no user can bypass auth") OR as
    # legitimate atomic phrasing ("no flow is specified"). The former
    # used to be rejected; the determiner was carved out because the
    # latter case is more common in product-level statement text.
    v = phrasing.check("no flow is specified")
    assert "universal_claim" not in categories(v)


def test_universal_pron_quantifier():
    for text in (
        "everyone can view public posts",
        "nobody is exempt from rate limits",
        "anybody is allowed to comment",
    ):
        v = phrasing.check(text)
        assert "universal_claim" in categories(v), (
            f"expected universal_claim for {text!r}"
        )


def test_universal_recommendation_mentions_rule_statement():
    v = phrasing.check("every user must verify email")
    uni = next(x for x in v if x["category"] == "universal_claim")
    assert "kind='rule'" in uni["recommendation"]


def test_all_as_pronoun_is_not_flagged():
    # "all is well" uses "all" as PRON, not the universal-quantifier DET
    v = phrasing.check("all is well")
    assert "universal_claim" not in categories(v)


# ─── per-kind dispatch: state ───────────────────────────────────────────────


def test_state_allows_copula_property():
    """`is a / is an` describes a state; should NOT flag for kind='state'."""
    v = phrasing.check("session is an authentication token", kind="state")
    assert "property_shaped" not in categories(v)


def test_state_allows_have_property():
    v = phrasing.check("user has a profile", kind="state")
    assert "property_shaped" not in categories(v)


def test_state_allows_structural_verbs():
    v = phrasing.check("auth flow consists of three steps", kind="state")
    assert "property_shaped" not in categories(v)


def test_state_rejects_obligation_modal():
    v = phrasing.check("session must expire", kind="state")
    assert "rule_shaped" in categories(v)


def test_state_rejects_capability_modal():
    v = phrasing.check("user can edit the profile", kind="state")
    assert "capability_in_state" in categories(v)


def test_state_rejects_is_able_to():
    v = phrasing.check("user is able to leave", kind="state")
    assert "capability_in_state" in categories(v)


def test_state_rejects_sequencing():
    v = phrasing.check("user will be logged in", kind="state")
    assert "sequencing" in categories(v)


# ─── per-kind dispatch: capability ──────────────────────────────────────────


def test_capability_allows_modal_can():
    v = phrasing.check("admin can revoke any session", kind="capability")
    assert "capability_in_state" not in categories(v)
    assert "rule_shaped" not in categories(v)


def test_capability_allows_may_and_might():
    for text in ("user may submit feedback", "user might cancel checkout"):
        v = phrasing.check(text, kind="capability")
        assert "capability_in_state" not in categories(v)


def test_capability_rejects_obligation_modal():
    v = phrasing.check("admin must approve every request", kind="capability")
    assert "rule_shaped" in categories(v)


def test_capability_rejects_sequencing():
    v = phrasing.check("user will be logged out", kind="capability")
    assert "sequencing" in categories(v)


# ─── per-kind dispatch: event (default + open kinds) ────────────────────────


def test_event_default_kind_runs_full_event_catalog():
    """No kind → defaults to event-style validation (back-compat)."""
    v = phrasing.check("session is an authentication token")
    assert "property_shaped" in categories(v)


def test_event_explicit_rejects_property_shape():
    v = phrasing.check("session is an authentication token", kind="event")
    assert "property_shaped" in categories(v)


def test_open_kind_falls_back_to_event_catalog():
    """Unknown kinds inherit the event catalog (open-vocabulary posture)."""
    v = phrasing.check("session is an authentication token", kind="policy")
    assert "property_shaped" in categories(v)


# ─── hidden_event_state: applies to ALL kinds ───────────────────────────────


def test_is_set_to_rejected_as_event():
    v = phrasing.check("status is set to active", kind="event")
    assert "hidden_event_state" in categories(v)


def test_becomes_rejected_as_state():
    v = phrasing.check("status becomes active", kind="state")
    assert "hidden_event_state" in categories(v)


def test_transitions_to_rejected_as_event():
    v = phrasing.check("workflow transitions to review", kind="event")
    assert "hidden_event_state" in categories(v)


def test_gets_marked_as_rejected():
    v = phrasing.check("invite gets marked as expired", kind="event")
    assert "hidden_event_state" in categories(v)


def test_hidden_event_state_recommendation_explains_split():
    v = phrasing.check("invite is set to expired", kind="event")
    h = next(x for x in v if x["category"] == "hidden_event_state")
    assert "split" in h["recommendation"].lower()
    assert "kind='event'" in h["recommendation"]
    assert "kind='state'" in h["recommendation"]


# ─── common catalog runs for every kind ─────────────────────────────────────


def test_compound_phrases_flagged_for_state():
    v = phrasing.check("user logs in; session active", kind="state")
    assert "compound" in categories(v)


def test_universal_quantifier_flagged_for_capability():
    v = phrasing.check("every admin can revoke any session", kind="capability")
    assert "universal_claim" in categories(v)


def test_hedge_flagged_for_state():
    v = phrasing.check("session is usually short-lived", kind="state")
    assert "hedge" in categories(v)


# ─── clean texts per kind ────────────────────────────────────────────────────


def test_event_clean_text_passes():
    assert phrasing.check("user logs in to the application", kind="event") == []


def test_state_clean_text_passes():
    assert phrasing.check("session is active", kind="state") == []


def test_capability_clean_text_passes():
    assert phrasing.check("admin can revoke the session", kind="capability") == []
