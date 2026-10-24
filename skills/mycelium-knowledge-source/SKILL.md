---
name: mycelium-knowledge-source
description: Use a Mycelium server as the source of product knowledge from a coding, support or research agent. Covers connecting over MCP (browser sign-in or a token), choosing between ask, search_statements and get_statements, citing statement ids and reporting knowledge gaps. Use this whenever you answer a product question from Mycelium, cite what it says, or find that it does not know something. For writing knowledge use mycelium-authoring; for proposing it through review use mycelium-draft.
---

# Mycelium as a knowledge source

Mycelium stores product knowledge as **statements**: short typed claims
(`stm_…` ids) with a `kind` (`event`, `state`, `capability`, `rule`,
`property`, and the guide kinds `procedure`, `action`, `check`, `cause`),
typed **links** between them, and **entities** (concepts with names and
aliases) that statements mention. This skill is about reading that knowledge
well and saying honestly what it does not hold.

## Connect

The server's own **Connect** page (`https://<host>/connect`) gives the exact
snippets for the host you are on. The two ways in:

- **Browser sign-in (people).** `claude mcp add --transport http mycelium
  https://<host>/mcp`, then `/mcp` in a Claude Code session and sign in. The
  client gets an OAuth token and renews it itself.
- **Token (CI, scripts, service accounts).** Mint one under **Settings → Account &
  tokens**, scoped no higher than the job needs, and pass it as a header:
  `claude mcp add --transport http mycelium https://<host>/mcp --header
  "Authorization: Bearer myc_…"`.

A local checkout serves stdio with `uv run python -m mycelium` (see
`SETUP.md`); with authentication off you act as a local admin.

**What you can call depends on the connection's role**, and `tools/list`
shows only what you may call:

| Role | Sees |
|---|---|
| `reader` | `ask`, the read tools, `report_knowledge_gap` |
| `drafter`, `writer`, `admin` | reads plus authoring (see the authoring and draft skills) |

If a tool this skill names is missing from your list, your role does not
include it. Say so rather than working around it.

## Ask, search or get

| You need | Call |
|---|---|
| A synthesized answer to a natural-language question | `ask(question)` |
| The statements themselves, to reason over or quote | `search_statements(query)` |
| A statement you already have the id of, with its links | `get_statements(ids=[…])` |
| An identifier, setting name or quoted string | `grep_statements(query)` |
| Everything about one concept | `search_entities(query)` or `list_entities(prefix=…)`, then `list_statements(entity_id=…)` |
| How two things relate | `find_statement_connections(source, target)` |

**`ask`** runs the server's own answer loop: it searches, follows links and
returns `{outcome: "answered", answer, confidence}`, or
`{outcome: "needs_clarification", question}`, in which case re-ask with the
clarified question. Pass `verbose=True` when you need to cite: the result
then carries `provenance` (the statement ids the answer rests on; `[n]` in the
answer text is the n-th of them) and `gaps` (what it could not find).
`depth="quick"` trades thoroughness for latency when your client drops long
calls; a quick answer can miss unlinked knowledge, so read its confidence.
`ask` costs a model run on the server; for a fact you can look up directly,
prefer the reads.

When Ask is set to **External agent**, the server runs no model for it: `ask`
is missing from `tools/list` and refuses a call. Research the question
yourself with the reads, as mycelium-research describes.

**`search_statements`** is semantic retrieval with alias boosting. Useful
arguments: `limit` (at most 100), `min_score`, `kind`, `mentions=[entity
names]` to restrict to a concept, and `depth=1` or `2` with `direction` to
pull linked neighbours into the result. Scores rank results; they are not
probabilities, and a low top score usually means the knowledge is not there.

**`get_statements`** hydrates ids: full text, kind, outgoing `links` and
`incoming_links`, each with its `link_type` and any `when` condition. A link
with `when` holds only while the referenced statements hold; read the
condition before stating the link as unconditional. `list_link_types()`
explains what each link type means.

Semantic search misses literal tokens. When the question contains an
identifier, an error code or a quoted UI label, also run `grep_statements`.

## Cite what you used

When you answer from Mycelium, say which statements carry the answer: their
ids, and their text when the reader cannot look them up. Prefer quoting a
statement's text over paraphrasing a rule or a limit. Do not cite a statement
you did not read, and do not present your own inference as a statement: mark
it as yours. When statements contradict each other, show both with their ids
instead of picking one.

## Report what is missing

When the knowledge you needed is not there, or a statement is wrong, call
`report_knowledge_gap(text)` once per distinct gap. Write the text as the
missing fact or the question a curator should answer ("Invoice export row
limit for the Starter plan is not recorded"), not as a log of your search.
Name what it concerns when you know it: `statement_id` for a statement that
is wrong or incomplete, `document_id` for a generated document that lacks
something. Curators see gaps under **Curate → Knowledge gaps**.

Do not fill a gap from memory or from the code and present it as Mycelium's
answer. If you can verify it elsewhere, say where the answer came from.
