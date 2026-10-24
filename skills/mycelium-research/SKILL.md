---
name: mycelium-research
description: Answer a question from a Mycelium knowledge base by researching it yourself with the read tools, the way the server's own Ask loop does — a decomposed recon search, targeted reads of statements and their links, conditions and concepts, one search seeded by what you found, then an answer that cites the statement ids it rests on and says "the knowledge base does not say" where it does not. Use when ask is missing from your tools or refuses because Ask is set to External agent, when you need an answer you can cite claim by claim, or when the user asks you to research a product question in Mycelium. For choosing tools and connecting, see mycelium-knowledge-source.
---

# Research a question in Mycelium

When Ask is set to **External agent**, the server runs no model for Ask:
`ask` is left out of `tools/list` and refuses a call. You are the agent that
answers, with the same read tools the server's loop uses. This skill is that
loop written down. It is also the way to answer when you need every claim
cited, whichever way Ask is set.

You need a connection with the `reader` role or higher. An `asker`
connection has only `ask`, so it has nothing to research with while Ask is
external: tell the user to ask an admin for a reader token.

## 1. Recon: map the question

Start with one wide search of the question as asked:

`search_statements(query=<the question>, limit=30, decompose=True)`

`decompose` splits the question on its conjunctions and searches each part,
so a question about two things returns both. Treat the hits as a map of what
the knowledge base holds near the question, not as the answer. Hits come
fully hydrated: text, kind, `mentions`, outgoing `links`, `incoming_links`
and `when_references`.

When the question holds an identifier, error code, setting name or quoted
UI label, also run `grep_statements(query=<the token>)`: semantic search
misses literal tokens.

## 2. Orient: settle what is being asked

From the recon, pick one:

- **The map is clean.** Go on.
- **The premise is off, but one real thing clearly fits.** Answer the
  question that serves the user's goal and say how you read it ("The
  knowledge base has no export scheduler; it describes scheduled invoice
  exports, which this answers").
- **Two or more distinct things fit and you cannot tell which.** Ask the
  user which they mean before reading further. Name each candidate and what
  it would cover; the recon makes them real.

## 3. Targeted reads: follow what matters

For the recon hits that bear on the question, read around them, several
calls at once where your client allows:

- **Links.** `get_statements(ids=[…])` on the `to_id`s of their links (and
  `from_id`s of incoming links) to walk the chain. Keep each edge's
  direction as stored: an incoming link does not reverse it.
  `list_link_types()` explains a link type you do not know.
- **Conditions.** A link with `when` holds only while its condition holds.
  The condition is a tree of statement references with AND, OR and NOT.
  Fetch the leaf statements when their meaning matters to the answer.
- **Concepts and aliases.** When the question uses a term, resolve it:
  `search_entities(query=<term>)`, then `get_entity(id=…)` for its names,
  aliases and description, and `list_statements(entity_id=…)` for what is
  said about it. An alias the user used may be the only way a concept is
  named in their question.
- **Relations.** For "how does A affect B", try
  `find_statement_connections(source=…, target=…)`.

## 4. Adjacency: search with what you have learned

The statement that matters most may have no link pointing at it; it is
reachable only through a shared concept or similar wording. So after the
targeted reads, run at least one more `search_statements` seeded by the
**concepts you gathered**, not by the question's wording: the entity names,
the specific settings and states the statements named. `mentions=[<concept
name>]` narrows a search to statements that mention a concept.

This step is what makes an answer complete rather than merely
plausible-looking. Skip it only for a lookup the targeted reads already
settled.

## 5. Stop when the question is covered

Check each part of the question against what you read. Stop once every part
is answered or known to be missing; do not repeat near-identical searches.
A low top score or no hits for a term means it is not there, not that you
phrased it badly. Try one other wording, then treat it as absent.

## Write the answer

- **Say only what the statements say.** Do not add purposes, mechanisms,
  defaults or general product knowledge they do not state. If you add your
  own inference, mark it as yours.
- **Carry conditions exactly**, NOT included. Never turn a condition into a
  requirement or the reverse.
- **Contradictions:** two statements giving different values for the same
  thing conflict. Give both with their ids and say they conflict; do not
  reconcile them or present them as two cases.
- **Absence:** when the knowledge base does not say, write "the knowledge
  base does not say" for that part. Never answer "no" from absence.
- **Cite** the statement ids each claim rests on, next to the claim, and
  quote a statement's text for a rule or a limit. Cite only statements you
  read, not ids you saw only as a link target.
- **Confidence** follows the gaps: high when the chain was walked, terms
  resolved and nothing conflicts; low when key terms returned nothing or the
  core of the question is unresolved.

Then call `report_knowledge_gap(text=…)` once per distinct missing fact, as
described in mycelium-knowledge-source.
