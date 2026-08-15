from mycelium.link_rules import LINK_DIRECTION, derive_kind_link_matrix


def test_unruled_link_type_is_admissible_for_every_kind_pair():
    kinds = {"event", "state"}

    matrix = derive_kind_link_matrix(kinds, {"contains"}, {})

    assert matrix == frozenset(
        {
            ("event", "event", "contains"),
            ("event", "state", "contains"),
            ("state", "event", "contains"),
            ("state", "state", "contains"),
        }
    )


def test_teaches_is_admissible_only_from_procedure_to_capability():
    kinds = {"procedure", "capability", "event"}

    matrix = derive_kind_link_matrix(kinds, {"teaches"})

    assert matrix == frozenset({("procedure", "capability", "teaches")})


def test_accepts_allows_any_source_but_only_property_targets():
    kinds = {"event", "procedure", "property"}

    matrix = derive_kind_link_matrix(kinds, {"accepts"}, LINK_DIRECTION)

    assert matrix == frozenset(
        {
            ("event", "property", "accepts"),
            ("procedure", "property", "accepts"),
            ("property", "property", "accepts"),
        }
    )


def test_derivation_returns_a_frozenset_of_triples():
    matrix = derive_kind_link_matrix(["event"], ["contains"], {})

    assert isinstance(matrix, frozenset)
    assert all(isinstance(row, tuple) and len(row) == 3 for row in matrix)
