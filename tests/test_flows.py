"""The flow walker, against a dict-backed reader: no database, no I/O."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from mycelium import when_expression
from mycelium.docgen import flows
from mycelium.docgen.flows import FlowLink, FlowStatement, WhenTree

Link = tuple[str, str, str] | tuple[str, str, str, WhenTree]


class Graph:
    def __init__(self, statements: dict[str, str], links: Sequence[Link]) -> None:
        self.statements = statements
        self.links_from: dict[str, list[FlowLink]] = {}
        for link in links:
            when = link[3] if len(link) == 4 else None
            self.links_from.setdefault(link[0], []).append(
                FlowLink(target=link[2], link_type=link[1], when=when)
            )

    def statement(self, statement_id: str) -> FlowStatement | None:
        kind = self.statements.get(statement_id)
        if kind is None:
            return None
        return FlowStatement(kind=kind, text=f"Text of {statement_id}")

    def links(self, statement_id: str) -> Sequence[FlowLink]:
        return self.links_from.get(statement_id, [])


def events(*names: str) -> dict[str, str]:
    return dict.fromkeys(names, "event")


def draw(graph: Graph, start: str, stop: Sequence[str] = ()) -> flows.Drawing:
    drawing = flows.draw_flow(graph, start, stop)
    assert drawing is not None
    return drawing


def step_ids(drawing: flows.Drawing) -> list[str]:
    return [step.statement_id for step in drawing.steps]


def test_chain_draws_every_statement_as_a_step_including_the_last():
    graph = Graph(
        events("requested", "queued", "ready"),
        [("requested", "proceeds", "queued"), ("queued", "proceeds", "ready")],
    )
    drawing = draw(graph, "requested")
    assert step_ids(drawing) == ["requested", "queued", "ready"]
    assert [step.number for step in drawing.steps] == [1, 2, 3]
    assert [(a.to, a.joins) for a in drawing.steps[0].arrows] == [(2, False)]
    assert drawing.steps[1].reached_from == 1
    assert drawing.steps[1].reached_by == "next"
    assert not drawing.truncated
    assert drawing.statement_ids == ["requested", "queued", "ready"]
    assert flows.flow_lines(drawing) == [
        "1. Text of requested (event)",
        "   -> step 2",
        "2. Text of queued (event)",
        "   -> step 3",
        "3. Text of ready (event)",
    ]


def test_branch_puts_a_dead_end_at_the_side_when_the_step_continues():
    graph = Graph(
        {"check": "check", "retry": "action", "fix": "action", "done": "action"},
        [
            ("check", "on-failure", "retry"),
            ("check", "on-success", "fix"),
            ("fix", "next", "done"),
        ],
    )
    drawing = draw(graph, "check")
    assert step_ids(drawing) == ["check", "fix", "done"]
    assert drawing.steps[1].reached_by == "on-success"
    (outcome,) = drawing.steps[0].outcomes
    assert outcome.statement_id == "retry"
    assert flows.side_label(outcome.links) == "on failure"
    assert "   on failure: Text of retry" in flows.flow_lines(drawing)


def test_branches_that_all_end_are_steps():
    graph = Graph(
        {"check": "check", "retry": "action", "fix": "action"},
        [("check", "on-failure", "retry"), ("check", "on-success", "fix")],
    )
    drawing = draw(graph, "check")
    assert step_ids(drawing) == ["check", "retry", "fix"]
    assert drawing.steps[0].outcomes == []
    assert "   -> step 2: on failure" in flows.flow_lines(drawing)


def test_join_draws_a_statement_once_and_names_the_step_it_joins():
    graph = Graph(
        events("start", "card", "bank", "paid", "receipt"),
        [
            ("start", "proceeds", "card"),
            ("start", "proceeds", "bank"),
            ("card", "proceeds", "paid"),
            ("bank", "proceeds", "paid"),
            ("paid", "proceeds", "receipt"),
        ],
    )
    drawing = draw(graph, "start")
    assert step_ids(drawing) == ["start", "card", "bank", "paid", "receipt"]
    assert [(a.to, a.joins) for a in drawing.steps[1].arrows] == [(4, False)]
    assert [(a.to, a.joins) for a in drawing.steps[2].arrows] == [(4, True)]
    assert "   -> joins step 4" in flows.flow_lines(drawing)


def test_loop_ends_at_the_step_it_returns_to():
    graph = Graph(
        events("sent", "bounced"),
        [("sent", "proceeds", "bounced"), ("bounced", "proceeds", "sent")],
    )
    drawing = draw(graph, "sent")
    assert step_ids(drawing) == ["sent", "bounced"]
    assert [(a.to, a.joins) for a in drawing.steps[1].arrows] == [(1, True)]


def test_walk_does_not_continue_past_a_stop():
    graph = Graph(
        events("a", "b", "c", "d"),
        [("a", "proceeds", "b"), ("b", "proceeds", "c"), ("c", "proceeds", "d")],
    )
    drawing = draw(graph, "a", stop=["c"])
    assert step_ids(drawing) == ["a", "b", "c"]
    assert drawing.steps[2].arrows == []
    assert "d" not in drawing.statement_ids


def test_parallel_links_to_one_target_draw_one_arrow_keeping_each_link():
    condition: WhenTree = {
        "op": "and",
        "of": [
            {"statement_id": "sso"},
            {
                "op": "or",
                "of": [
                    {"statement_id": "admin"},
                    {"op": "not", "of": [{"statement_id": "trial"}]},
                ],
            },
        ],
    }
    graph = Graph(
        {
            **events("invited", "joined", "welcomed"),
            "sso": "state",
            "admin": "state",
            "trial": "state",
        },
        [
            ("invited", "proceeds", "joined"),
            ("invited", "triggers", "joined", condition),
            ("joined", "proceeds", "welcomed"),
        ],
    )
    drawing = draw(graph, "invited")
    (arrow,) = drawing.steps[0].arrows
    assert [(link.link_type, link.role) for link in arrow.links] == [
        ("proceeds", "next"),
        ("triggers", "separate-process"),
    ]
    assert arrow.links[1].when == condition
    assert drawing.conditions == {
        "admin": "Text of admin",
        "sso": "Text of sso",
        "trial": "Text of trial",
    }
    assert set(drawing.statement_ids) == {
        "invited",
        "joined",
        "welcomed",
        "sso",
        "admin",
        "trial",
    }
    assert flows.flow_lines(drawing)[1] == (
        "   -> step 2: then; or starts a separate process, when "
        '"Text of sso" and ("Text of admin" or not "Text of trial")'
    )


def test_step_limit_cuts_the_drawing_and_says_where_it_continues():
    names = [f"s{n}" for n in range(20)]
    graph = Graph(
        events(*names),
        [(a, "proceeds", b) for a, b in zip(names, names[1:], strict=False)],
    )
    drawing = draw(graph, "s0")
    assert len(drawing.steps) == flows.MAX_STEPS
    assert drawing.truncated
    assert [step.continues for step in drawing.steps] == [False] * 11 + [True]
    assert drawing.steps[-1].cut == [
        flows.CutStatement(statement_id="s12", text="Text of s12")
    ]
    assert flows.flow_lines(drawing)[-1] == ("   -> continues: Text of s12 (not drawn)")


def test_a_cut_names_at_most_three_statements_and_counts_the_rest():
    names = [f"s{n}" for n in range(flows.MAX_STEPS)]
    cut = [f"c{n}" for n in range(5)]
    graph = Graph(
        events(*names, *cut, "end"),
        [
            *((a, "proceeds", b) for a, b in zip(names, names[1:], strict=False)),
            *((names[-1], "proceeds", item) for item in cut),
            *((item, "proceeds", "end") for item in cut),
        ],
    )
    last = draw(graph, "s0").steps[-1]

    assert [item.statement_id for item in last.cut] == cut[:3]
    assert last.more_cut == 2
    assert flows.continues_text(last, lambda text: f"<{text}>") == (
        "continues: <Text of c0>; <Text of c1>; <Text of c2> (not drawn), and 2 more"
    )


def test_a_drawing_stored_before_cuts_were_recorded_keeps_the_old_words():
    step = flows.Step.model_validate(
        {
            "number": 1,
            "statement_id": "s",
            "text": "Text of s",
            "kind": "event",
            "continues": True,
        }
    )

    assert step.cut == [] and step.more_cut == 0
    assert flows.continues_text(step) == "continues beyond this drawing"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("A job profile is assigned", "a job profile is assigned"),
        ("An invoice is overdue", "an invoice is overdue"),
        ("The export is ready", "the export is ready"),
        ("Payment fails", "payment fails"),
        ("SSO is enforced", "SSO is enforced"),
        ("MagicToken expired", "MagicToken expired"),
        ("HBO-backed plan is active", "HBO-backed plan is active"),
        ("Workspace Owner approves", "Workspace Owner approves"),
        ("Workspaces are archived", "Workspaces are archived"),
        ("Workspacer runs", "workspacer runs"),
        ("already lower", "already lower"),
        ("", ""),
    ],
)
def test_a_condition_after_a_connective_starts_lower_case_unless_a_name(
    text: str, expected: str
) -> None:
    assert flows.condition_case(text, ("Workspace Owner", "Workspace")) == expected


def test_side_outcomes_beyond_the_fourth_are_counted():
    states = [f"state{n}" for n in range(7)]
    graph = Graph(
        {"paid": "event", "closed": "event", **dict.fromkeys(states, "state")},
        [
            ("paid", "proceeds", "closed"),
            *(("paid", "establishes", state) for state in states),
        ],
    )
    drawing = draw(graph, "paid")
    first = drawing.steps[0]
    assert [outcome.statement_id for outcome in first.outcomes] == states[:4]
    assert first.more_outcomes == 3
    assert not drawing.truncated
    assert "state5" not in drawing.statement_ids
    assert "   and 3 more" in flows.flow_lines(drawing)


def test_visit_limit_cuts_the_walk_before_the_step_limit():
    statements: dict[str, str] = {}
    links: list[Link] = []
    for n in range(12):
        statements[f"s{n}"] = "event"
        links.append((f"s{n}", "proceeds", f"s{n + 1}"))
        for m in range(6):
            statements[f"s{n}r{m}"] = "state"
            links.append((f"s{n}", "establishes", f"s{n}r{m}"))
    statements["s12"] = "event"
    drawing = draw(Graph(statements, links), "s0")
    assert drawing.truncated
    assert len(drawing.steps) < flows.MAX_STEPS
    seen = len(drawing.steps) + sum(
        len(step.outcomes) + step.more_outcomes for step in drawing.steps
    )
    assert seen == flows.MAX_VISITED


def test_contains_marks_steps_as_part_of_their_parent_in_stored_order():
    graph = Graph(
        {**events("export", "collect", "zip"), "limit": "rule"},
        [
            ("export", "contains", "limit"),
            ("export", "contains", "collect"),
            ("export", "contains", "zip"),
        ],
    )
    drawing = draw(graph, "export")
    assert step_ids(drawing) == ["export", "collect", "zip"]
    assert [step.reached_by for step in drawing.steps[1:]] == ["part-of", "part-of"]
    assert flows.flow_lines(drawing)[3] == (
        "2. Text of collect (event) - part of step 1"
    )


def test_procedure_contains_actions_but_not_other_kinds():
    graph = Graph(
        {"setup": "procedure", "open": "action", "input": "property"},
        [("setup", "contains", "input"), ("setup", "contains", "open")],
    )
    assert step_ids(draw(graph, "setup")) == ["setup", "open"]


def test_triggers_marks_a_separate_process():
    graph = Graph(
        events("invited", "emailed", "opened"),
        [("invited", "triggers", "emailed"), ("emailed", "proceeds", "opened")],
    )
    drawing = draw(graph, "invited")
    assert drawing.steps[1].reached_by == "separate-process"
    lines = flows.flow_lines(drawing)
    assert lines[1] == "   -> step 2: starts a separate process"
    assert lines[2] == (
        "2. Text of emailed (event) - a separate process started by step 1"
    )


def test_fallback_is_listed_under_its_step_as_otherwise():
    graph = Graph(
        {"workspace_rate": "rule", "plan_rate": "rule"},
        [("workspace_rate", "fallback-to", "plan_rate")],
    )
    drawing = draw(graph, "workspace_rate")
    assert step_ids(drawing) == ["workspace_rate"]
    (outcome,) = drawing.steps[0].outcomes
    assert outcome.statement_id == "plan_rate"
    assert flows.flow_lines(drawing, with_ids=True) == [
        "1. [workspace_rate] Text of workspace_rate (rule)",
        "   otherwise: [plan_rate] Text of plan_rate",
    ]


def test_establishes_draws_a_state_as_a_result_and_nothing_else():
    graph = Graph(
        {"paid": "event", "settled": "state", "refund": "event"},
        [
            ("paid", "establishes", "settled"),
            ("paid", "establishes", "refund"),
            ("paid", "enables", "refund"),
        ],
    )
    drawing = draw(graph, "paid")
    assert step_ids(drawing) == ["paid"]
    (outcome,) = drawing.steps[0].outcomes
    assert (outcome.statement_id, flows.side_label(outcome.links)) == (
        "settled",
        "result",
    )
    assert "refund" not in drawing.statement_ids


def test_links_the_reader_cannot_show_are_left_out():
    graph = Graph(
        events("a", "b", "c"),
        [
            ("a", "proceeds", "hidden"),
            ("a", "proceeds", "b", {"statement_id": "hidden"}),
            ("a", "proceeds", "c"),
        ],
    )
    drawing = draw(graph, "a")
    assert step_ids(drawing) == ["a", "c"]
    assert [link.target for link in drawing.link_set] == ["c"]
    assert flows.draw_flow(graph, "hidden") is None


def test_link_set_names_each_step_link_with_its_condition_hash():
    condition: WhenTree = {"statement_id": "sso"}
    statements = {**events("a", "b", "c"), "sso": "state"}
    links: list[Link] = [
        ("a", "proceeds", "b", condition),
        ("b", "proceeds", "c"),
        ("b", "enables", "c"),
    ]
    drawing = draw(Graph(statements, links), "a")
    assert [link.model_dump() for link in drawing.link_set] == [
        {
            "source": "a",
            "target": "b",
            "link_type": "proceeds",
            "when_hash": when_expression.hash_canonical(condition),
        },
        {
            "source": "b",
            "target": "c",
            "link_type": "proceeds",
            "when_hash": when_expression.HASH_NONE,
        },
    ]
    assert flows.link_set(Graph(statements, links), drawing) == drawing.link_set

    grown = Graph({**statements, "d": "event"}, [*links, ("c", "proceeds", "d")])
    assert flows.link_set(grown, drawing) != drawing.link_set
    unconditional = Graph(statements, [("a", "proceeds", "b"), *links[1:]])
    assert flows.link_set(unconditional, drawing) != drawing.link_set


def test_drawing_survives_json():
    graph = Graph(
        {**events("a", "b"), "s": "state", "c": "state"},
        [("a", "proceeds", "b", {"statement_id": "c"}), ("a", "establishes", "s")],
    )
    drawing = draw(graph, "a")
    assert flows.Drawing.model_validate_json(drawing.model_dump_json()) == drawing


def test_flow_starts_are_statements_nothing_else_in_the_set_leads_to():
    graph = Graph(
        events("a", "b", "c", "x", "y", "lonely", "outside"),
        [
            ("x", "proceeds", "y"),
            ("a", "proceeds", "b"),
            ("b", "proceeds", "c"),
            ("outside", "proceeds", "a"),
        ],
    )
    members = ["x", "y", "a", "b", "c", "lonely"]
    starts = flows.flow_starts(graph, members)
    assert [(start.statement_id, start.size) for start in starts] == [
        ("a", 3),
        ("x", 2),
    ]
    assert starts[0].text == "Text of a"
    assert [s.statement_id for s in flows.flow_starts(graph, members, limit=1)] == ["a"]


def test_flow_starts_offer_the_busiest_statement_of_a_loop():
    graph = Graph(
        events("a", "b", "c", "d"),
        [
            ("a", "proceeds", "b"),
            ("b", "proceeds", "c"),
            ("b", "proceeds", "d"),
            ("c", "proceeds", "a"),
            ("d", "proceeds", "a"),
        ],
    )
    starts = flows.flow_starts(graph, ["a", "b", "c", "d"])
    assert [(start.statement_id, start.size) for start in starts] == [("b", 4)]
    assert flows.flow_starts(graph, ["lonely"]) == []


def test_link_with_a_malformed_stored_condition_is_left_out():
    graph = Graph(
        events("requested", "queued", "ready"),
        [
            ("requested", "proceeds", "queued", {"op": "and", "of": []}),
            ("requested", "proceeds", "ready"),
        ],
    )
    drawing = draw(graph, "requested")
    assert step_ids(drawing) == ["requested", "ready"]


def condition_words(condition: flows.Condition) -> str:
    """A reading on one line, a list in square brackets."""
    if not condition.items:
        return " ".join(part for part in (condition.lead, condition.text) if part)
    items = "; ".join(condition_words(item) for item in condition.items)
    return f"{condition.lead} [{items}]"


def said_words(said: flows.Said) -> str:
    return "; or ".join(
        ", ".join(
            part
            for part in (
                meaning.label,
                meaning.condition and condition_words(meaning.condition),
            )
            if part
        )
        for meaning in said
    )


def shape(chain: Sequence[flows.Placed]) -> list[object]:
    """A laid-out chain as step numbers, the line under each, and groups."""
    out: list[object] = []
    for placed in chain:
        out.append((placed.step.number, placed.onward, said_words(placed.onward_said)))
        out += [
            (
                group.kind,
                group.label,
                [(said_words(b.said), shape(b.chain)) for b in group.branches],
            )
            for group in placed.groups
        ]
        out += [("joins", join.to, said_words(join.said)) for join in placed.joins]
    return out


def test_layout_of_a_chain_is_one_line_of_plain_steps():
    graph = Graph(
        events("a", "b", "c"), [("a", "proceeds", "b"), ("b", "proceeds", "c")]
    )
    chain = flows.layout(draw(graph, "a"))
    assert shape(chain) == [(1, "then", ""), (2, "then", ""), (3, None, "")]
    assert flows.line_kinds(chain) == {"then"}


def test_layout_hangs_a_branch_off_its_step_with_each_condition():
    graph = Graph(
        {**events("a", "b", "c", "d"), "big": "state"},
        [
            ("a", "proceeds", "b"),
            ("b", "proceeds", "c", {"statement_id": "big"}),
            ("b", "fallback-to", "d"),
            ("d", "proceeds", "a"),
            ("c", "proceeds", "d"),
        ],
    )
    chain = flows.layout(draw(graph, "a"))
    assert shape(chain) == [
        (1, "then", ""),
        (
            2,
            None,
            "",
        ),
        (
            "branch",
            "Then, depending on the condition",
            [
                ("when Text of big", [(3, None, ""), ("joins", (4,), "")]),
                ("otherwise", [(4, None, ""), ("joins", (1,), "")]),
            ],
        ),
    ]
    assert flows.line_kinds(chain) == {"then", "branch"}


def test_layout_collapses_joins_that_say_the_same():
    graph = Graph(
        events("a", "b", "c", "d"),
        [
            ("a", "contains", "b"),
            ("a", "contains", "c"),
            ("b", "proceeds", "d"),
            ("c", "proceeds", "a"),
            ("d", "proceeds", "b"),
            ("d", "proceeds", "c"),
        ],
    )
    chain = flows.layout(draw(graph, "a"))
    [part] = chain[0].groups
    # Numbered as drawn: b, then d under it, then c.
    assert part.kind == "part" and part.label == "Includes"
    assert part.numbers == [2, 3, 4]
    first = part.branches[0].chain
    assert [placed.step.number for placed in first] == [2, 3]
    assert first[1].joins == (flows.Join(to=(2, 4), said=()),)


def test_layout_of_five_separate_processes_is_one_group_beside_the_next_step():
    graph = Graph(
        events("start", "next", "p1", "p2", "p3", "p4", "p5"),
        [
            *(("start", "triggers", f"p{n}") for n in range(1, 6)),
            ("start", "proceeds", "next"),
        ],
    )
    chain = flows.layout(draw(graph, "start"))
    assert [placed.step.number for placed in chain] == [1, 7]
    assert chain[0].onward == "then"
    [separate] = chain[0].groups
    assert separate.kind == "separate" and separate.label == "Starts separately"
    assert separate.numbers == [2, 3, 4, 5, 6]
    assert [branch.said for branch in separate.branches] == [()] * 5
    assert flows.numbers_text(separate.numbers) == "steps 2–6"


def test_a_single_separate_process_is_the_line_under_its_step():
    graph = Graph(events("a", "b"), [("a", "triggers", "b")])
    chain = flows.layout(draw(graph, "a"))
    assert shape(chain) == [(1, "separate", "starts a separate process"), (2, None, "")]


def test_step_numbers_are_written_as_a_range_or_a_list():
    assert flows.numbers_text([4]) == "step 4"
    assert flows.numbers_text([2, 3]) == "steps 2 and 3"
    assert flows.numbers_text([2, 4, 7]) == "steps 2, 4 and 7"
    assert flows.numbers_text([3, 4], lambda n: f"<{n}>") == "steps <3> and <4>"


def numbers_down_the_page(chain: Sequence[flows.Placed]) -> list[int]:
    return list(flows.drawn_order(chain))


def test_layout_numbers_each_branch_before_the_step_under_it():
    graph = Graph(
        events("a", "x", "y", "b", "x1", "y1", "c"),
        [
            ("a", "triggers", "x"),
            ("a", "triggers", "y"),
            ("a", "proceeds", "b"),
            ("x", "proceeds", "x1"),
            ("y", "proceeds", "y1"),
            ("b", "proceeds", "c"),
        ],
    )
    drawing = draw(graph, "a")
    # The walk numbers breadth first.
    assert step_ids(drawing) == ["a", "x", "y", "b", "x1", "y1", "c"]
    chain = flows.layout(drawing)
    assert numbers_down_the_page(chain) == [1, 2, 3, 4, 5, 6, 7]
    [separate] = chain[0].groups
    assert [
        [(placed.step.number, placed.step.statement_id) for placed in branch.chain]
        for branch in separate.branches
    ] == [[(2, "x"), (3, "x1")], [(4, "y"), (5, "y1")]]
    assert separate.numbers == [2, 3, 4, 5]
    assert [(placed.step.number, placed.step.statement_id) for placed in chain] == [
        (1, "a"),
        (6, "b"),
        (7, "c"),
    ]
    assert [arrow.to for arrow in chain[0].step.arrows] == [2, 4, 6]
    assert separate.branches[0].chain[1].step.reached_from == 2


def test_layout_gives_nested_groups_the_steps_they_hold():
    graph = Graph(
        events("a", "p", "q", "b", "p1", "p2", "r", "c"),
        [
            ("a", "contains", "p"),
            ("a", "contains", "q"),
            ("a", "proceeds", "b"),
            ("p", "triggers", "p1"),
            ("p", "triggers", "p2"),
            ("p", "proceeds", "r"),
            ("p1", "proceeds", "a"),
            ("p2", "proceeds", "a"),
            ("r", "proceeds", "a"),
            ("q", "proceeds", "a"),
            ("b", "proceeds", "c"),
        ],
    )
    chain = flows.layout(draw(graph, "a"))
    assert numbers_down_the_page(chain) == [1, 2, 3, 4, 5, 6, 7, 8]
    [part] = chain[0].groups
    assert part.numbers == [2, 3, 4, 5, 6]
    p_chain, q_chain = (branch.chain for branch in part.branches)
    assert [(placed.step.number, placed.step.statement_id) for placed in p_chain] == [
        (2, "p"),
        (5, "r"),
    ]
    [nested] = p_chain[0].groups
    assert nested.numbers == [3, 4]
    assert q_chain[0].step.number == 6
    assert [placed.step.number for placed in chain] == [1, 7, 8]


def test_layout_renumbers_joins_into_earlier_and_later_steps():
    graph = Graph(
        events("a", "x", "y", "x1", "z"),
        [
            ("a", "triggers", "x"),
            ("a", "triggers", "y"),
            ("x", "proceeds", "x1"),
            ("x1", "proceeds", "y"),
            ("y", "proceeds", "z"),
            ("z", "proceeds", "a"),
        ],
    )
    drawing = draw(graph, "a")
    assert [step.number for step in drawing.steps if step.statement_id == "y"] == [3]
    chain = flows.layout(drawing)
    assert numbers_down_the_page(chain) == [1, 2, 3, 4, 5]
    [separate] = chain[0].groups
    x_chain, y_chain = (branch.chain for branch in separate.branches)
    assert [(placed.step.number, placed.step.statement_id) for placed in x_chain] == [
        (2, "x"),
        (3, "x1"),
    ]
    # x1 joins y, drawn after it; z joins a, drawn before.
    assert x_chain[1].joins == (flows.Join(to=(4,), said=()),)
    assert [(placed.step.number, placed.step.statement_id) for placed in y_chain] == [
        (4, "y"),
        (5, "z"),
    ]
    assert y_chain[1].joins == (flows.Join(to=(1,), said=()),)


A: WhenTree = {"statement_id": "a"}
B: WhenTree = {"statement_id": "b"}
C: WhenTree = {"statement_id": "c"}
TEXTS = {"a": "SSO is on", "b": "The plan is Team", "c": "An invoice is overdue"}


def AND(*of: WhenTree) -> WhenTree:  # noqa: N802
    return {"op": "and", "of": list(of)}


def OR(*of: WhenTree) -> WhenTree:  # noqa: N802
    return {"op": "or", "of": list(of)}


def NOT(of: WhenTree) -> WhenTree:  # noqa: N802
    return {"op": "not", "of": [of]}


def read(when: WhenTree) -> str:
    return condition_words(flows.condition_reading(when, TEXTS))


def test_a_single_condition_and_its_negation_stay_on_one_line():
    assert flows.condition_reading(A, TEXTS) == flows.Condition("when", "SSO is on")
    assert flows.condition_reading(NOT(A), TEXTS) == flows.Condition(
        "unless", "SSO is on"
    )
    # A statement the drawing has no text for reads as its id.
    assert read({"statement_id": "stm_x"}) == "when stm_x"


def test_each_kind_of_stored_condition_reads_as_its_own_words():
    cases: list[tuple[WhenTree, str]] = [
        (AND(A, B), "when all of: [SSO is on; The plan is Team]"),
        (OR(A, B), "when any of: [SSO is on; The plan is Team]"),
        (NOT(AND(A, B)), "when not all of: [SSO is on; The plan is Team]"),
        (NOT(OR(A, B)), "when none of: [SSO is on; The plan is Team]"),
        (
            AND(OR(A, B), C),
            "when all of: [any of: [SSO is on; The plan is Team]; "
            "An invoice is overdue]",
        ),
        (
            OR(AND(A, B), C),
            "when any of: [all of: [SSO is on; The plan is Team]; "
            "An invoice is overdue]",
        ),
        (AND(A, NOT(B)), "when all of: [SSO is on; not The plan is Team]"),
        (
            OR(A, NOT(AND(B, C))),
            "when any of: [SSO is on; not all of: [The plan is Team; "
            "An invoice is overdue]]",
        ),
        (
            AND(A, NOT(OR(B, C))),
            "when all of: [SSO is on; none of: [The plan is Team; "
            "An invoice is overdue]]",
        ),
        # Double negation is drawn as stored, not simplified.
        (NOT(NOT(A)), "unless not SSO is on"),
        (NOT(NOT(NOT(A))), "unless not not SSO is on"),
        (NOT(NOT(AND(A, B))), "unless not all of: [SSO is on; The plan is Team]"),
        (NOT(NOT(OR(A, B))), "unless none of: [SSO is on; The plan is Team]"),
        (AND(A, NOT(NOT(B))), "when all of: [SSO is on; not not The plan is Team]"),
        # A group of one, which canonical storage collapses but older rows hold.
        (AND(A), "when all of: [SSO is on]"),
    ]
    assert [read(when) for when, _ in cases] == [words for _, words in cases]


def _holds(when: WhenTree, values: dict[str, bool]) -> bool:
    if when_expression.is_leaf(when):
        return values[when["statement_id"]]
    results = [_holds(child, values) for child in when["of"]]
    if when["op"] == "not":
        return not results[0]
    return all(results) if when["op"] == "and" else any(results)


_IDS = {text: statement_id for statement_id, text in TEXTS.items()}


def _reads_true(condition: flows.Condition, values: dict[str, bool]) -> bool:
    """What a reader takes a reading to mean, from its words alone."""
    words = condition.lead.split()
    negate = False
    if words[:1] in (["when"], ["unless"]):
        negate = words.pop(0) == "unless"
    while words[:1] == ["not"] and words[1:2] != ["all"]:
        negate = not negate
        words.pop(0)
    lead = " ".join(words)
    if not condition.items:
        assert lead == ""
        found = values[_IDS[condition.text]]
    else:
        results = [_reads_true(item, values) for item in condition.items]
        found = {
            "all of:": all(results),
            "any of:": any(results),
            "not all of:": not all(results),
            "none of:": not any(results),
        }[lead]
    return found != negate


def _trees(depth: int) -> list[WhenTree]:
    if depth == 0:
        return [A, B, C]
    smaller = _trees(depth - 1)
    pairs = [(x, y) for x in smaller[:6] for y in smaller[-6:]]
    return [
        *smaller,
        *(NOT(tree) for tree in smaller),
        *(AND(x, y) for x, y in pairs),
        *(OR(x, y) for x, y in pairs),
    ]


def test_every_reading_means_exactly_what_its_tree_means():
    assignments = [
        {"a": a, "b": b, "c": c}
        for a in (False, True)
        for b in (False, True)
        for c in (False, True)
    ]
    trees = _trees(3)
    assert len(trees) > 300
    for tree in trees:
        reading = flows.condition_reading(tree, TEXTS)
        for values in assignments:
            assert _reads_true(reading, values) == _holds(tree, values), tree


def test_meanings_leave_out_what_the_line_already_says():
    plain = flows.DrawnLink(link_type="proceeds", role="next")
    failing = flows.DrawnLink(link_type="on-failure", role="on-failure", when=A)
    part = flows.DrawnLink(link_type="contains", role="part-of")
    assert flows.meanings([plain], TEXTS) == ()
    assert flows.meanings([part], TEXTS, own="part-of") == ()
    assert flows.meanings([failing], TEXTS) == (
        flows.Meaning("on failure", flows.Condition("when", "SSO is on")),
    )
    assert flows.meanings([plain], TEXTS, side=True) == (flows.Meaning("outcome"),)
    # Parallel links each keep their label.
    assert flows.meanings([part, failing], TEXTS, own="part-of") == (
        flows.Meaning("includes"),
        flows.Meaning("on failure", flows.Condition("when", "SSO is on")),
    )


def test_merged_links_say_a_shared_condition_once_and_the_same_meaning_once():
    plain = flows.DrawnLink(link_type="proceeds", role="next")
    part = flows.DrawnLink(link_type="contains", role="part-of")
    then_a = flows.DrawnLink(link_type="proceeds", role="next", when=A)
    part_a = flows.DrawnLink(link_type="contains", role="part-of", when=A)
    part_b = flows.DrawnLink(link_type="contains", role="part-of", when=B)
    when_a = flows.Condition("when", "SSO is on")
    # The same condition: the kinds joined by "or", the condition once.
    assert flows.meanings([part_a, then_a], TEXTS) == (
        flows.Meaning("includes or then", when_a),
    )
    # One kind under different conditions: the kind once, each condition.
    assert flows.meanings([part_a, then_a, part_b], TEXTS) == (
        flows.Meaning("includes or then", when_a),
        flows.Meaning("includes", flows.Condition("when", "The plan is Team")),
    )
    assert flows.meanings([part_a, part_b, part], TEXTS) == (
        flows.Meaning("includes", when_a),
        flows.Meaning("", flows.Condition("when", "The plan is Team")),
        flows.Meaning("includes"),
    )
    # The same meaning twice is said once.
    assert flows.meanings([part_a, part_a], TEXTS) == (
        flows.Meaning("includes", when_a),
    )
    assert flows.meanings([plain, part], TEXTS, side=True) == (
        flows.Meaning("outcome"),
    )


def test_plain_flow_lines_keep_brackets_and_quotes():
    graph = Graph(
        {**events("a1", "a2"), "a": "state", "b": "state", "c": "state"},
        [("a1", "proceeds", "a2", NOT(AND(A, OR(B, C))))],
    )
    assert flows.flow_lines(draw(graph, "a1"))[1] == (
        '   -> step 2: then, when not ("Text of a" and ("Text of b" or "Text of c"))'
    )
