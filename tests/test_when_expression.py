import pytest

from mycelium import when_expression as we


# ─── shape predicates ───────────────────────────────────────────────────────


def test_is_leaf_and_is_internal():
    assert we.is_leaf({"statement_id": "stm_x"})
    assert not we.is_internal({"statement_id": "stm_x"})
    assert we.is_internal({"op": "and", "of": [{"statement_id": "stm_x"}]})
    assert not we.is_leaf({"op": "or", "of": []})


# ─── validation ─────────────────────────────────────────────────────────────


def test_validate_accepts_leaf_and_internal():
    we.validate({"statement_id": "stm_x"})
    we.validate(
        {"op": "and", "of": [{"statement_id": "stm_x"}, {"statement_id": "stm_y"}]}
    )
    we.validate(
        {"op": "or", "of": [{"statement_id": "stm_x"}]}
    )  # 1-child internal allowed


def test_validate_rejects_non_dict():
    with pytest.raises(ValueError, match="must be a dict"):
        we.validate("stm_x")


def test_validate_rejects_mixed_keys():
    with pytest.raises(ValueError, match="both"):
        we.validate({"statement_id": "stm_x", "op": "and"})


def test_validate_rejects_extra_leaf_keys():
    with pytest.raises(ValueError, match="leaf must have only"):
        we.validate({"statement_id": "stm_x", "extra": 1})


def test_validate_rejects_empty_statement_id():
    with pytest.raises(ValueError, match="non-empty string"):
        we.validate({"statement_id": ""})


def test_validate_rejects_unknown_op():
    with pytest.raises(ValueError, match="must be 'and', 'or', or 'not'"):
        we.validate({"op": "xor", "of": [{"statement_id": "stm_x"}]})


def test_validate_accepts_not():
    we.validate({"op": "not", "of": [{"statement_id": "stm_x"}]})


def test_validate_rejects_not_with_multiple_children():
    with pytest.raises(ValueError, match="'not' must have exactly one child"):
        we.validate(
            {
                "op": "not",
                "of": [
                    {"statement_id": "stm_x"},
                    {"statement_id": "stm_y"},
                ],
            }
        )


def test_validate_rejects_not_with_empty_of():
    # The shared "'of' must be non-empty" check fires before the not-specific one.
    with pytest.raises(ValueError, match="non-empty"):
        we.validate({"op": "not", "of": []})


def test_validate_rejects_empty_of():
    with pytest.raises(ValueError, match="non-empty"):
        we.validate({"op": "and", "of": []})


def test_validate_rejects_non_list_of():
    with pytest.raises(ValueError, match="list"):
        we.validate({"op": "and", "of": {"statement_id": "stm_x"}})


def test_validate_recurses():
    with pytest.raises(ValueError, match="non-empty string"):
        we.validate(
            {
                "op": "and",
                "of": [
                    {"statement_id": "stm_x"},
                    {"statement_id": ""},  # invalid leaf nested
                ],
            }
        )


def test_validate_allows_at_refs_in_leaves():
    # @-refs are valid intermediate state during batch resolution
    we.validate({"statement_id": "@2"})
    we.validate({"op": "or", "of": [{"statement_id": "@0"}, {"statement_id": "stm_x"}]})


# ─── canonicalize: leaves ───────────────────────────────────────────────────


def test_canonicalize_leaf_is_identity():
    leaf = {"statement_id": "stm_x"}
    assert we.canonicalize(leaf) == {"statement_id": "stm_x"}


# ─── canonicalize: associativity (flatten same-op nesting) ─────────────────


def test_canonicalize_flattens_nested_and():
    expr = {
        "op": "and",
        "of": [
            {"statement_id": "stm_a"},
            {"op": "and", "of": [{"statement_id": "stm_b"}, {"statement_id": "stm_c"}]},
        ],
    }
    out = we.canonicalize(expr)
    assert out["op"] == "and"
    assert sorted(c["statement_id"] for c in out["of"]) == ["stm_a", "stm_b", "stm_c"]


def test_canonicalize_flattens_deeply_nested():
    # AND(X, AND(Y, AND(Z, W))) → AND(X, Y, Z, W)
    expr = {
        "op": "and",
        "of": [
            {"statement_id": "stm_x"},
            {
                "op": "and",
                "of": [
                    {"statement_id": "stm_y"},
                    {
                        "op": "and",
                        "of": [
                            {"statement_id": "stm_z"},
                            {"statement_id": "stm_w"},
                        ],
                    },
                ],
            },
        ],
    }
    out = we.canonicalize(expr)
    assert sorted(c["statement_id"] for c in out["of"]) == [
        "stm_w",
        "stm_x",
        "stm_y",
        "stm_z",
    ]


def test_canonicalize_does_not_flatten_across_different_ops():
    # AND(X, OR(Y, Z)) stays as AND(X, OR(Y, Z))
    expr = {
        "op": "and",
        "of": [
            {"statement_id": "stm_x"},
            {"op": "or", "of": [{"statement_id": "stm_y"}, {"statement_id": "stm_z"}]},
        ],
    }
    out = we.canonicalize(expr)
    assert out["op"] == "and"
    assert len(out["of"]) == 2
    or_branch = next(c for c in out["of"] if "op" in c)
    assert or_branch["op"] == "or"


# ─── canonicalize: dedup + collapse ────────────────────────────────────────


def test_canonicalize_dedupes_identical_children():
    expr = {
        "op": "and",
        "of": [
            {"statement_id": "stm_x"},
            {"statement_id": "stm_x"},
        ],
    }
    # Dedupes to one child, then collapses.
    assert we.canonicalize(expr) == {"statement_id": "stm_x"}


def test_canonicalize_collapses_single_child_internal():
    assert we.canonicalize({"op": "and", "of": [{"statement_id": "stm_x"}]}) == {
        "statement_id": "stm_x"
    }
    assert we.canonicalize({"op": "or", "of": [{"statement_id": "stm_x"}]}) == {
        "statement_id": "stm_x"
    }


def test_canonicalize_dedupes_structurally_equal_subtrees():
    # AND(OR(X, Y), OR(Y, X)) — both children canonicalize to the same OR.
    expr = {
        "op": "and",
        "of": [
            {"op": "or", "of": [{"statement_id": "stm_x"}, {"statement_id": "stm_y"}]},
            {"op": "or", "of": [{"statement_id": "stm_y"}, {"statement_id": "stm_x"}]},
        ],
    }
    out = we.canonicalize(expr)
    # Both branches dedupe to one OR, then the surrounding AND collapses.
    assert out["op"] == "or"
    assert sorted(c["statement_id"] for c in out["of"]) == ["stm_x", "stm_y"]


# ─── canonicalize: commutativity (sort children) ───────────────────────────


def test_canonicalize_sort_makes_order_irrelevant():
    e1 = we.canonicalize(
        {"op": "and", "of": [{"statement_id": "stm_x"}, {"statement_id": "stm_y"}]}
    )
    e2 = we.canonicalize(
        {"op": "and", "of": [{"statement_id": "stm_y"}, {"statement_id": "stm_x"}]}
    )
    assert e1 == e2


def test_canonicalize_idempotent():
    expr = {
        "op": "or",
        "of": [
            {"op": "and", "of": [{"statement_id": "stm_z"}, {"statement_id": "stm_a"}]},
            {"statement_id": "stm_m"},
        ],
    }
    once = we.canonicalize(expr)
    twice = we.canonicalize(once)
    assert once == twice


# ─── hash_canonical ─────────────────────────────────────────────────────────


def test_hash_canonical_sentinel_for_none():
    assert we.hash_canonical(None) == "NONE"
    assert we.HASH_NONE == "NONE"


def test_hash_canonical_deterministic():
    expr = {"op": "and", "of": [{"statement_id": "stm_x"}, {"statement_id": "stm_y"}]}
    h1 = we.hash_canonical(expr)
    h2 = we.hash_canonical(expr)
    assert h1 == h2
    assert len(h1) == 64  # sha-256 hex


def test_hash_canonical_invariant_under_reorder():
    a = {"op": "and", "of": [{"statement_id": "stm_x"}, {"statement_id": "stm_y"}]}
    b = {"op": "and", "of": [{"statement_id": "stm_y"}, {"statement_id": "stm_x"}]}
    assert we.hash_canonical(a) == we.hash_canonical(b)


def test_hash_canonical_invariant_under_redundant_nesting():
    # AND(X, AND(Y, Z)) should hash the same as AND(X, Y, Z).
    nested = {
        "op": "and",
        "of": [
            {"statement_id": "stm_x"},
            {"op": "and", "of": [{"statement_id": "stm_y"}, {"statement_id": "stm_z"}]},
        ],
    }
    flat = {
        "op": "and",
        "of": [
            {"statement_id": "stm_x"},
            {"statement_id": "stm_y"},
            {"statement_id": "stm_z"},
        ],
    }
    assert we.hash_canonical(nested) == we.hash_canonical(flat)


def test_hash_canonical_distinguishes_and_from_or():
    a = {"op": "and", "of": [{"statement_id": "stm_x"}, {"statement_id": "stm_y"}]}
    o = {"op": "or", "of": [{"statement_id": "stm_x"}, {"statement_id": "stm_y"}]}
    assert we.hash_canonical(a) != we.hash_canonical(o)


# ─── canonicalize: NOT ──────────────────────────────────────────────────────


def test_canonicalize_not_preserves_single_child():
    expr = {"op": "not", "of": [{"statement_id": "stm_x"}]}
    assert we.canonicalize(expr) == {"op": "not", "of": [{"statement_id": "stm_x"}]}


def test_canonicalize_double_negation_folds():
    expr = {
        "op": "not",
        "of": [
            {"op": "not", "of": [{"statement_id": "stm_x"}]},
        ],
    }
    assert we.canonicalize(expr) == {"statement_id": "stm_x"}


def test_canonicalize_triple_negation_is_single_not():
    expr = {
        "op": "not",
        "of": [
            {
                "op": "not",
                "of": [
                    {"op": "not", "of": [{"statement_id": "stm_x"}]},
                ],
            },
        ],
    }
    assert we.canonicalize(expr) == {"op": "not", "of": [{"statement_id": "stm_x"}]}


def test_canonicalize_not_inside_and():
    # AND(X, NOT(Y)) — NOT is preserved as its own subtree.
    expr = {
        "op": "and",
        "of": [
            {"statement_id": "stm_x"},
            {"op": "not", "of": [{"statement_id": "stm_y"}]},
        ],
    }
    out = we.canonicalize(expr)
    assert out["op"] == "and"
    assert len(out["of"]) == 2
    not_branch = next(c for c in out["of"] if c.get("op") == "not")
    assert not_branch == {"op": "not", "of": [{"statement_id": "stm_y"}]}


def test_canonicalize_does_not_flatten_nested_not():
    # NOT(NOT(X)) folds (handled by double-negation), but NOT does NOT
    # absorb other ops — NOT(AND(X, Y)) stays as-is structurally.
    expr = {
        "op": "not",
        "of": [
            {"op": "and", "of": [{"statement_id": "stm_x"}, {"statement_id": "stm_y"}]},
        ],
    }
    out = we.canonicalize(expr)
    assert out["op"] == "not"
    assert out["of"][0]["op"] == "and"


def test_hash_canonical_distinguishes_not_from_leaf():
    leaf = {"statement_id": "stm_x"}
    negated = {"op": "not", "of": [leaf]}
    assert we.hash_canonical(leaf) != we.hash_canonical(negated)


def test_hash_canonical_and_not_y_invariant_under_reorder():
    a = {
        "op": "and",
        "of": [
            {"statement_id": "stm_x"},
            {"op": "not", "of": [{"statement_id": "stm_y"}]},
        ],
    }
    b = {
        "op": "and",
        "of": [
            {"op": "not", "of": [{"statement_id": "stm_y"}]},
            {"statement_id": "stm_x"},
        ],
    }
    assert we.hash_canonical(a) == we.hash_canonical(b)


def test_hash_canonical_distinguishes_different_leaves():
    assert we.hash_canonical({"statement_id": "stm_x"}) != we.hash_canonical(
        {"statement_id": "stm_y"}
    )


# ─── leaves() ───────────────────────────────────────────────────────────────


def test_leaves_of_none_is_empty():
    assert we.leaves(None) == set()


def test_leaves_of_leaf():
    assert we.leaves({"statement_id": "stm_x"}) == {"stm_x"}


def test_leaves_walks_tree():
    expr = {
        "op": "or",
        "of": [
            {"op": "and", "of": [{"statement_id": "stm_a"}, {"statement_id": "stm_b"}]},
            {"statement_id": "stm_c"},
        ],
    }
    assert we.leaves(expr) == {"stm_a", "stm_b", "stm_c"}


def test_leaves_walks_through_not():
    expr = {
        "op": "not",
        "of": [
            {"op": "and", "of": [{"statement_id": "stm_a"}, {"statement_id": "stm_b"}]},
        ],
    }
    assert we.leaves(expr) == {"stm_a", "stm_b"}


def test_leaves_dedupe_repeated_references():
    expr = {
        "op": "or",
        "of": [
            {"statement_id": "stm_x"},
            {"op": "and", "of": [{"statement_id": "stm_x"}, {"statement_id": "stm_y"}]},
        ],
    }
    # Pre-canonicalization the tree has stm_x twice; leaves still returns a set.
    assert we.leaves(expr) == {"stm_x", "stm_y"}


# ─── substitute_leaves() ────────────────────────────────────────────────────


def test_substitute_leaves_remaps_leaves():
    expr = {"op": "and", "of": [{"statement_id": "@0"}, {"statement_id": "@1"}]}
    mapping = {"@0": "stm_aaa", "@1": "stm_bbb"}.__getitem__
    out = we.substitute_leaves(expr, mapping)
    assert out == {
        "op": "and",
        "of": [{"statement_id": "stm_aaa"}, {"statement_id": "stm_bbb"}],
    }


def test_substitute_leaves_preserves_structure_and_op():
    expr = {
        "op": "or",
        "of": [
            {"op": "and", "of": [{"statement_id": "@0"}, {"statement_id": "stm_x"}]},
            {"statement_id": "stm_y"},
        ],
    }
    out = we.substitute_leaves(expr, lambda x: "stm_REMAPPED" if x == "@0" else x)
    assert out["op"] == "or"
    inner_and = next(c for c in out["of"] if "op" in c)
    assert inner_and["op"] == "and"
    assert {c["statement_id"] for c in inner_and["of"]} == {"stm_REMAPPED", "stm_x"}


def test_substitute_leaves_walks_through_not():
    expr = {
        "op": "and",
        "of": [
            {"statement_id": "@0"},
            {"op": "not", "of": [{"statement_id": "@1"}]},
        ],
    }
    out = we.substitute_leaves(expr, {"@0": "stm_aaa", "@1": "stm_bbb"}.__getitem__)
    assert out == {
        "op": "and",
        "of": [
            {"statement_id": "stm_aaa"},
            {"op": "not", "of": [{"statement_id": "stm_bbb"}]},
        ],
    }


def test_substitute_leaves_does_not_mutate_input():
    expr = {"op": "and", "of": [{"statement_id": "stm_x"}]}
    we.substitute_leaves(expr, lambda x: "DIFFERENT")
    assert expr == {"op": "and", "of": [{"statement_id": "stm_x"}]}
