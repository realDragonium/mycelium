"""The exported site's search ranking, run as the page runs it: the ranking
in site.js, called by Node on a tiny invented index."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import mycelium.docgen
from mycelium.docgen import flows, render, site
from mycelium.docgen.schema import StoredFlow

SCRIPT = Path(mycelium.docgen.__file__).parent / "site.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(
    NODE is None, reason="Node is not installed; site.js's ranking needs it to run"
)

_RUN = """
const { rank } = require(process.argv[1]);
const { entries, queries } = JSON.parse(require("fs").readFileSync(0, "utf8"));
console.log(JSON.stringify(queries.map((query) => rank(entries, query).map(
  (hit) => [hit.entry.href, hit.anchor || "", hit.detail || "", hit.alias || ""]))));
"""


def _section(text: str, heading: str = "", anchor: str = "") -> dict[str, str]:
    return {"anchor": anchor, "heading": heading, "text": text}


def _entry(
    href: str,
    title: str,
    *sections: dict[str, str],
    stub: bool = False,
    aliases: tuple[str, ...] = (),
) -> dict[str, object]:
    entry: dict[str, object] = {"title": title, "href": href, "sections": sections}
    if stub:
        entry["stub"] = True
    if aliases:
        entry["aliases"] = aliases
    return entry


def _rank(entries: list[dict[str, object]], *queries: str) -> list[list[list[str]]]:
    assert NODE is not None
    done = subprocess.run(
        [NODE, "-e", _RUN, str(SCRIPT)],
        input=json.dumps({"entries": entries, "queries": queries}),
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    found: list[list[list[str]]] = json.loads(done.stdout)
    return found


def _hrefs(entries: list[dict[str, object]], *queries: str) -> list[list[str]]:
    return [[hit[0] for hit in hits] for hits in _rank(entries, *queries)]


_CALL = """
const search = require(process.argv[1]);
const { name, args } = JSON.parse(require("fs").readFileSync(0, "utf8"));
const out = search[name](...args);
console.log(JSON.stringify(name === "suggest" ? out.map((s) => [s.entry.href, s.name]) : out));
"""


def _call(name: str, *args: object) -> object:
    assert NODE is not None
    done = subprocess.run(
        [NODE, "-e", _CALL, str(SCRIPT)],
        input=json.dumps({"name": name, "args": args}),
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return json.loads(done.stdout)


def _marked(text: str, words: list[str], squashed: str = "") -> list[str]:
    spans = _call("marks", text, words, squashed)
    assert isinstance(spans, list)
    return [text[start:end] for start, end in spans]


def test_a_whole_word_ranks_above_a_word_start_and_inside_a_word_is_dropped():
    entries = [
        _entry("inside.html", "Corrections", _section("Reinvoice a customer.")),
        _entry("start.html", "Backlog", _section("Invoiced work piles up.")),
        _entry("whole.html", "Paying", _section("Each invoice is paid.")),
    ]

    assert _hrefs(entries, "invoice") == [["whole.html", "start.html"]]


def test_a_title_holding_the_word_inside_another_does_not_outrank_text():
    entries = [
        _entry("average.html", "Average", stub=True),
        _entry("era.html", "Billing", _section("Prices from an earlier era.")),
    ]

    assert _hrefs(entries, "era") == [["era.html"]]


def test_only_matches_inside_words_are_kept_ranked_as_text_and_marked():
    entries = [
        _entry("block.html", "Blocklist", _section("Rows are kept.")),
        _entry(
            "unlock.html",
            "Workspaces",
            _section("Owners can unlock a workspace after a failed payment."),
        ),
        _entry("other.html", "Exports", _section("Nightly.")),
    ]

    found = _call("rank", entries, "lock")
    assert isinstance(found, list)
    assert [(hit["entry"]["href"], hit["inside"]) for hit in found] == [
        ("block.html", True),
        ("unlock.html", True),
    ]
    assert "unlock" in found[1]["detail"]
    assert _call("marks", "Blocklist", ["lock"], "", True) == [[1, 5]]
    # Without a hit inside words, nothing inside one is marked.
    assert _marked("Blocklist", ["lock"]) == []


def test_a_word_of_two_letters_never_matches_inside_a_word():
    entries = [
        _entry("sso.html", "Sessions", _section("Ends idle sessions.")),
        _entry("es.html", "Locale", _section("Set ES for Spanish.")),
    ]

    assert _hrefs(entries, "ss", "es") == [[], ["es.html"]]


def test_a_written_page_ranks_above_a_stub_and_a_stub_title_above_stub_text():
    entries = [
        _entry("sign-in.html", "Sign-in", _section("Uses SSO."), stub=True),
        _entry("sso-stub.html", "SSO", stub=True),
        _entry("sso.html", "SSO"),
    ]

    assert _hrefs(entries, "sso") == [["sso.html", "sso-stub.html", "sign-in.html"]]


def test_the_whole_query_as_written_ranks_first_and_picks_the_excerpt():
    entries = [
        _entry("apart.html", "Export", _section("Each invoice is sent.")),
        _entry(
            "text.html",
            "Billing",
            _section("An export holds each invoice.", "Runs", "runs"),
            _section("Each night an invoice export runs.", "Nightly", "nightly"),
        ),
        _entry("heading.html", "Exports", _section("Rows.", "Invoice export", "ie")),
        _entry("title.html", "Invoice export"),
    ]

    assert _rank(entries, "invoice export") == [
        [
            ["title.html", "", "", ""],
            ["heading.html", "ie", "Invoice export", ""],
            ["text.html", "nightly", "Each night an invoice export runs.", ""],
            ["apart.html", "", "Each invoice is sent.", ""],
        ]
    ]


def test_words_match_in_any_order_and_a_query_can_find_nothing():
    entries = [_entry("paying.html", "Paying", _section("Each invoice is paid."))]

    assert _hrefs(entries, "paid invoice", "invoice missing", "zz") == [
        ["paying.html"],
        [],
        [],
    ]


def test_another_name_is_found_as_a_title_and_named_in_the_result():
    entries = [
        _entry("mentions.html", "Sign-in", _section("Uses SSO and a single sign-on.")),
        _entry("sso.html", "Single sign-on", aliases=("SSO", "Federated login")),
        _entry("export.html", "Data export", aliases=("e-export",), stub=True),
        _entry("start.html", "Login", _section("Federated sign-in.")),
    ]

    assert _rank(entries, "sso", "federated login", "e-export", "federated") == [
        [
            ["sso.html", "", "", "SSO"],
            ["mentions.html", "", "Uses SSO and a single sign-on.", ""],
        ],
        [
            ["sso.html", "", "", "Federated login"],
            ["start.html", "", "Federated sign-in.", ""],
        ],
        [["export.html", "", "", "e-export"]],
        [
            ["sso.html", "", "", "Federated login"],
            ["start.html", "", "Federated sign-in.", ""],
        ],
    ]
    # Where the title says it as well, the title is reason enough.
    assert _rank(entries, "single sign-on")[0][0] == ["sso.html", "", "", ""]


def test_a_concepts_own_page_ranks_above_pages_that_mention_it():
    mentions = [
        _entry(
            f"mention-{n}.html", f"Page {n}", _section("Turn on audit logging first.")
        )
        for n in range(3)
    ]
    stub = _entry("audit-logging.html", "Audit logging", stub=True)
    written = _entry("logging.html", "Logging", _section("Audit logging is kept."))

    # The whole query as a stub's title puts the stub first, ahead of written
    # pages that only mention it.
    assert (
        _hrefs([*mentions, written, stub], "audit logging")[0][0]
        == "audit-logging.html"
    )
    # Unless a written page has that title or that name.
    same = _entry("audit.html", "Audits", aliases=("Audit logging",))
    assert _hrefs([*mentions, stub, same], "audit logging")[0][:2] == [
        "audit.html",
        "audit-logging.html",
    ]
    # A written page's own title puts it first.
    assert _hrefs([*mentions, stub, written], "logging")[0][0] == "logging.html"


def test_titles_holding_a_word_come_before_text_written_first_among_them():
    entries = [
        _entry("text.html", "Billing", _section("Each invoice is paid.")),
        _entry("stub.html", "Invoice line", stub=True),
        _entry("written.html", "Invoice numbering"),
        _entry("heading.html", "Payments", _section("Rows.", "Invoice status", "s")),
    ]

    assert _hrefs(entries, "invoice") == [
        ["written.html", "stub.html", "heading.html", "text.html"]
    ]


def test_a_title_holding_the_word_ranks_above_another_name_holding_it():
    entries = [
        _entry("sso.html", "SSO", aliases=("Guest sign-in",)),
        _entry("guest.html", "Guest access policies"),
    ]

    assert _rank(entries, "guest") == [
        [["guest.html", "", "", ""], ["sso.html", "", "", "Guest sign-in"]]
    ]


def test_equal_matches_rank_written_then_shorter_titles_then_alphabetically():
    entries = [
        _entry("rules.html", "Invoice numbering rules"),
        _entry("stub.html", "Invoice line", stub=True),
        _entry("tax.html", "Invoice tax"),
        _entry("due.html", "Invoice due"),
    ]

    assert _hrefs(entries, "invoice") == [
        ["due.html", "tax.html", "rules.html", "stub.html"]
    ]


def test_a_plural_query_finds_the_singular_title_first():
    entries = [
        _entry("notes.html", "Notes", _section("Usage scores are kept per workspace.")),
        _entry("bands.html", "Score bands", stub=True),
        _entry("score.html", "Usage score", _section("One per pair.")),
    ]

    assert _hrefs(entries, "usage scores", "scores") == [
        ["score.html", "notes.html"],
        ["score.html", "bands.html", "notes.html"],
    ]


def test_the_word_as_written_wins_a_tie_with_another_form():
    entries = [
        _entry("page.html", "Export flows page", stub=True),
        _entry("flow.html", "Flow"),
        _entry("flows.html", "Flows", stub=True),
    ]

    assert _hrefs(entries, "flows", "flow") == [
        ["flows.html", "flow.html", "page.html"],
        ["flow.html", "flows.html", "page.html"],
    ]


def test_a_singular_query_finds_a_regular_plural_as_a_whole_word():
    entries = [
        _entry("start.html", "Backlog", _section("Invoiced work piles up.")),
        _entry("plural.html", "Billing", _section("All invoices are sent.")),
    ]

    assert _rank(entries, "invoice") == [
        [
            ["plural.html", "", "All invoices are sent.", ""],
            ["start.html", "", "Invoiced work piles up.", ""],
        ]
    ]


def test_ies_and_es_plurals_match_both_ways():
    entries = [
        _entry("policy.html", "Retention policy"),
        _entry("rules.html", "Rules", _section("Two policies apply.")),
        _entry("box.html", "Inbox", aliases=("Mail box",)),
        _entry("boxes.html", "Storage", _section("Exports land in boxes.")),
    ]

    assert _hrefs(entries, "policies", "policy", "boxes", "box") == [
        ["policy.html", "rules.html"],
        ["policy.html", "rules.html"],
        ["box.html", "boxes.html"],
        ["box.html", "boxes.html"],
    ]


def test_a_title_starting_with_what_is_typed_comes_before_text_holding_it():
    entries = [
        _entry("billing.html", "Billing", _section("You can pay by card.")),
        _entry("sso.html", "SSO", _section("Admins can turn it on.")),
        _entry("cancel.html", "Cancellation", _section("Ends a plan.")),
    ]

    assert _hrefs(entries, "can", "cancel") == [
        ["cancel.html", "billing.html", "sso.html"],
        ["cancel.html"],
    ]


def test_a_whole_word_title_ranks_above_a_word_start_title():
    entries = [
        _entry("exporter.html", "Exporter"),
        _entry("export.html", "Workspace export"),
    ]

    assert _hrefs(entries, "export") == [["export.html", "exporter.html"]]


def test_text_only_matches_are_not_ordered_by_title_length():
    entries = [
        _entry("tax.html", "Tax", _section("An invoice once.")),
        _entry("billing.html", "Billing settings", _section("An invoice once.")),
        _entry("often.html", "Workspace plans", _section("An invoice, an invoice.")),
        _entry("stub.html", "Ab", _section("An invoice, an invoice."), stub=True),
    ]

    assert _hrefs(entries, "invoice") == [
        ["often.html", "billing.html", "tax.html", "stub.html"]
    ]


def test_underscores_and_hyphens_read_as_spaces_when_nothing_is_found_as_typed():
    entries = [
        _entry("settings.html", "Settings", _section("Set max_exports to 5.")),
        _entry("export.html", "Workspace export"),
        _entry("other.html", "Limits", _section("Max exports per day.")),
    ]

    assert _hrefs(
        entries,
        "workspace_export",
        "workspace-export",
        "max_exports",
        "max-exports",
        "max exports",
    ) == [
        ["export.html"],
        ["export.html"],
        ["settings.html"],
        ["other.html", "settings.html"],
        ["other.html", "settings.html"],
    ]


_NAMED = [
    _entry("score.html", "Usage score", _section("Ranks a pair.", "Scale", "scale")),
    _entry("profile.html", "Seat plan", aliases=("Licence plan",)),
    _entry("groups.html", "Billing group config", stub=True),
    _entry("notes.html", "Notes", _section("A seat plan is kept.", "Kept", "kept")),
]


def test_a_name_typed_as_one_word_or_in_camel_case_is_found_first():
    found = _hrefs(
        _NAMED,
        "usagescore",
        "UsageScore",
        "usage_score",
        "usagescores",
        "seatPlan",
        "licenceplan",
        "billinggroupconfig",
        "BillingGroupConfig",
    )

    assert [hits[0] for hits in found] == [
        "score.html",
        "score.html",
        "score.html",
        "score.html",
        "profile.html",
        "profile.html",
        "groups.html",
        "groups.html",
    ]


def test_camel_case_finds_the_words_in_text_when_no_name_is_it():
    entries = [
        _entry("billing.html", "Billing", _section("Each invoice line is sent."))
    ]

    assert _hrefs(entries, "invoiceLine", "InvoiceLine") == [
        ["billing.html"],
        ["billing.html"],
    ]


def test_the_start_of_a_name_typed_as_one_word_finds_it_from_four_letters():
    assert _hrefs(
        _NAMED, "usag", "usagesc", "usage_s", "billinggr", "seatp", "usa"
    ) == [
        ["score.html"],
        ["score.html"],
        ["score.html"],
        ["groups.html"],
        ["profile.html"],
        ["score.html"],
    ]
    # A lone "s" typed after a word starts the next one; it is no plural.
    assert _hrefs([_entry("m.html", "Usage"), *_NAMED], "usage_s") == [["score.html"]]


def test_a_page_found_by_name_opens_at_its_top_with_how_it_starts():
    entries = [
        _entry(
            "cancellation.html",
            "Cancellation",
            _section("A cancellation ends a subscription."),
            _section("Admins can remove one.", "What you can do", "can-do"),
        ),
        _entry("billing.html", "Billing", _section("You can pay.", "Paying", "pay")),
    ]

    assert _rank(entries, "can", "cancellat", "cancellation") == [
        [
            ["cancellation.html", "", "A cancellation ends a subscription.", ""],
            ["billing.html", "pay", "You can pay.", ""],
        ],
        [["cancellation.html", "", "A cancellation ends a subscription.", ""]],
        [["cancellation.html", "", "A cancellation ends a subscription.", ""]],
    ]


def test_marks_fall_on_whole_words_and_word_starts_of_two_letters_or_more():
    assert _marked("Sets a usage score", ["usage", "s"]) == ["usage"]
    assert _marked("Stored and redone", ["red"]) == ["red"]
    assert _marked("Invoices are sent", ["invoice"]) == ["Invoices"]


def test_a_name_matched_with_its_words_joined_is_marked_as_far_as_typed():
    assert _marked("Usage score", ["usagesc"], "usagesc") == ["Usage sc"]
    assert _marked("Usage scores", ["usagescore"], "usagescore") == ["Usage scores"]
    assert _marked("Usage score", ["usage", "s"], "usages") == ["Usage s"]


def test_a_query_finding_nothing_is_offered_names_close_to_it():
    entries = [
        _entry("invoice.html", "Invoice"),
        _entry("sso.html", "Single sign-on", aliases=("SSO",)),
        _entry("export.html", "Workspace export"),
    ]

    assert _call("suggest", entries, "invoce") == [["invoice.html", "Invoice"]]
    assert _call("suggest", entries, "workspcae exprt") == [
        ["export.html", "Workspace export"]
    ]
    assert _call("suggest", entries, "WorkspaceExpotr") == [
        ["export.html", "Workspace export"]
    ]
    assert _call("suggest", entries, "ssx") == [["sso.html", "SSO"]]
    assert _call("suggest", entries, "billing") == []


_WORDS = [
    _entry(
        "sso.html",
        "Single sign-on",
        _section("An assessment of each identity provider is kept."),
    ),
    _entry("invoice.html", "Invoice", _section("Each invoice has a due date.")),
    _entry("export.html", "Workspace export", _section("Exports run nightly.")),
    _entry("audit.html", "Audit log", _section("The audit log keeps every export.")),
]


def _looked_up(entries: list[dict[str, object]], query: str) -> tuple[object, ...]:
    out = _call("lookup", entries, query)
    assert isinstance(out, dict)
    corrected = out["corrected"]
    return (
        corrected and corrected["query"],
        [hit["entry"]["href"] for hit in out["found"]],
        [hit["entry"]["href"] for hit in out["suggested"]],
    )


def test_a_misspelled_word_is_corrected_and_its_results_shown():
    assert _looked_up(_WORDS, "assesment") == ("assessment", ["sso.html"], [])
    # A word under four letters is left to the whole-name suggestions.
    assert _looked_up(_WORDS, "audit lgo") == (None, [], ["audit.html"])
    assert _looked_up(_WORDS, "nightly exprots") == (
        "nightly exports",
        ["export.html"],
        [],
    )
    # A word the index knows, as a word, a form or a start, is kept.
    assert _call("correct", _WORDS, "invoices assesmnt") == {
        "query": "invoices assessment",
        "words": [
            {"word": "invoices", "changed": False},
            {"word": "assessment", "changed": True},
        ],
    }
    assert _call("correct", _WORDS, "nigh exprot") == {
        "query": "nigh export",
        "words": [
            {"word": "nigh", "changed": False},
            {"word": "export", "changed": True},
        ],
    }


def test_equally_near_corrections_prefer_the_more_frequent_then_alphabetical():
    entries = [
        _entry("a.html", "Notes", _section("A batch, a batch, a match.")),
        _entry("b.html", "More", _section("A latch and a hatch.")),
    ]

    correct = _call("correct", entries, "xatch")
    assert isinstance(correct, dict) and correct["query"] == "batch"
    alphabetical = _call("correct", entries, "hatcx")
    assert isinstance(alphabetical, dict) and alphabetical["query"] == "hatch"
    tied = _call("correct", entries, "zatch")
    assert isinstance(tied, dict) and tied["query"] == "batch"
    entries[1] = _entry("b.html", "More", _section("A latch, a latch, a latch."))
    more = _call("correct", entries, "zatch")
    assert isinstance(more, dict) and more["query"] == "latch"


def test_short_or_distant_words_are_not_corrected():
    assert _call("correct", _WORDS, "dte") is None
    assert _call("correct", _WORDS, "zzzzzz") is None
    assert _looked_up(_WORDS, "zzzzzz") == (None, [], [])


def test_whole_names_are_still_suggested_when_no_correction_finds_anything():
    entries = [
        _entry("profile.html", "Seat plan"),
        _entry("score.html", "Usage score"),
    ]

    assert _looked_up(entries, "seatpla") == (None, ["profile.html"], [])
    assert _looked_up(entries, "usagescroe") == (None, [], ["score.html"])


def test_a_correction_replaces_matches_found_only_inside_words():
    entries = [
        _entry("block.html", "Notes", _section("Each block is kept.")),
        _entry("lockout.html", "Sign-in", _section("A lockout follows five tries.")),
    ]

    assert _looked_up(entries, "lockut") == ("lockout", ["lockout.html"], [])
    assert _looked_up(entries, "lock") == (None, ["lockout.html"], [])


def test_a_short_fragment_found_inside_words_is_not_corrected():
    entries = [
        _entry("payment.html", "Notes", _section("Each payment and shipment is kept.")),
        _entry("menu.html", "Layout", _section("The menu opens on the left.")),
    ]

    assert _looked_up(entries, "ment") == (None, ["payment.html"], [])


def test_the_status_says_which_query_the_results_are_for():
    assert _call("statusOf", 2, 2, [], "assessment", "assesment") == (
        "No results for assesment. Showing results for assessment. 2 results. "
        "Use the arrow keys to choose one."
    )


def test_a_seven_letter_word_is_corrected_by_one_edit_only():
    entries = [
        _entry("active.html", "Notes", _section("Only active workspaces are billed."))
    ]

    assert _call("correct", entries, "archive") is None
    assert _looked_up(entries, "actve")[0] == "active"


def test_list_items_after_an_added_full_stop_start_with_a_capital():
    reader = site._Text()
    reader.feed(
        "<ul><li>keeps the score</li><li>the assessment</li>"
        "<li><code>max_exports</code> is set</li><li>done.</li><li>more</li></ul>"
    )
    reader.close()

    assert " ".join("".join(reader.sections[0][2]).split()) == (
        "keeps the score. The assessment. max_exports is set. Done. More."
    )


def test_the_status_names_the_suggestions_or_says_nothing_was_found():
    assert _call("statusOf", 0, 0, []) == "Nothing found."
    assert _call("statusOf", 0, 0, [{"name": "Invoice"}, {"name": "SSO"}]) == (
        "Nothing found. Did you mean Invoice or SSO? Use the arrow keys to choose one."
    )
    assert _call("statusOf", 30, 20, []) == (
        "30 results, showing the first 20. Use the arrow keys to choose one."
    )


class _Export:
    """An export includes a run, which leads on to a file, and has a check as
    an outcome."""

    def statement(self, statement_id: str) -> flows.FlowStatement | None:
        return flows.FlowStatement("event", f"The export {statement_id}")

    def links(self, statement_id: str) -> list[flows.FlowLink]:
        return {
            "is requested": [
                flows.FlowLink("runs", "contains", None),
                flows.FlowLink("is checked", "contains", None),
            ],
            "runs": [flows.FlowLink("is ready", "proceeds", None)],
        }.get(statement_id, [])


def _flow_page(href: str, prose: str) -> dict[str, object]:
    drawing = flows.draw_flow(_Export(), "is requested")
    assert drawing is not None
    html = render.render_markdown(
        f"{prose}\n\n```flow\nf\n```\n",
        flows={
            "f": StoredFlow(name="f", title="", start="is requested", drawing=drawing)
        },
    )
    assert '<p class="flow-via">includes</p>' in html and "outcome:" in html
    reader = site._Text()
    reader.feed(html)
    reader.close()
    text = " ".join("".join(reader.sections[0][2]).split())
    return _entry(href, "Exports", _section(text))


def test_a_flows_way_finding_words_find_nothing():
    entries = [
        _flow_page("flow-only.html", "Exports run nightly."),
        _flow_page("prose.html", "The plan includes SSO."),
    ]

    assert _hrefs(entries, "includes", "outcome", "then", "runs") == [
        ["prose.html"],
        [],
        [],
        ["flow-only.html", "prose.html"],
    ]
