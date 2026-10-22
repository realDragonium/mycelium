# Mycelium: project context

## Purpose

Mycelium stores connected knowledge that agents can retrieve, extend, and
project into human-facing documents. Relationships, concepts, and aliases
are first-class so consumers can follow conditions and interactions across
features.

The substrate holds accepted knowledge. User documentation, support content,
and internal wikis are generated projections. Source material supplies the
evidence for knowledge changes; generated prose must not feed back as new
evidence for its own claims.

## Consumers

- Coding assistants using MCP or HTTP retrieval tools.
- Research and documentation agents running on the server.
- Aurora's persistent memory integration, with its own knowledge directory.
- Future support and product reasoning workflows using the same primitives.

The server's model-driven actions (ask, ingest, research, documentation, draft
review and alias discovery) go through one provider boundary, `mycelium.ai`, and
an administrator chooses Claude or OpenAI GPT for each action. The substrate and
tool contracts work independently of the model provider.

## Ingestion

The intended experience starts with prose: hand over a paragraph, several
sentences, or lightly structured text and receive connected knowledge.

1. Split the prose into atomic statements while retaining the source context.
2. Identify relationships expressed by its connecting words, preserving their
   direction, negation, and scope.
3. Find existing statements that express the same claims and reuse those
   identities where warranted. Similarity supplies candidates for this decision.
4. Propose new statements and links, corrections, and unresolved questions
   together in a draft.
5. Review the proposed changes before applying them to accepted knowledge.

Current entry points serve different inputs: `ingest` and research runs use an
LLM to propose draft operations from prose; statements an agent has already
extracted go in through `upsert_statements` and `submit_draft`. The internal
draft reviewer then judges links, duplicates, and contradictions against the
graph.

Evaluation must start with source prose and expected statements, relationships,
and matches to existing knowledge. Measuring whether already-extracted
statements retain cues for an existing graph does not test this workflow.
The old link-pattern hit-rate reports were retired on 2026-09-06.

## Data model

- **Entity:** a long-lived domain referent with an opaque id and description.
- **Name:** an alias naming an entity, with its own embedding.
- **Statement:** an atomic unit of knowledge with text and a `kind`, connected
  to other statements by typed links. Mentions associate its text with names
  and entities.

The installed glossary defines the vocabulary. Seeded statement kinds cover
events, states, capabilities, rules, properties, procedures, actions, checks,
and causes. Definitions, defaults, calculations, and other domain claims
belong in statements of the appropriate kind.

**Annotations were removed.** They attracted knowledge that belonged in
statements. Do not add annotation records or introduce a parallel note store
for domain knowledge. Historical migrations and archive compatibility still
reference annotations; older databases may retain inert tables.

Statement links can carry `when` expressions over statements using AND, OR,
and NOT. Entity-to-entity links describe structural relationships. There are no
entity-to-statement links: schema 14 removed them (DRA-393), and an instance
that still holds any refuses to upgrade until their meaning has been rescued by
hand, as `docs/ENTITY_STATEMENT_MIGRATION.md` describes.

Kinds and link vocabulary can evolve. Direction checks, phrasing validation,
and candidate compatibility rules keep writes and proposals coherent.

## Review and documentation

Knowledge proposals accumulate in drafts. An internal reviewer judges each
submitted draft against the graph: duplicates, contradictions, link type and
direction, and missing links to live neighbours. It trusts the producer on what
the product does; it judges how the draft fits what is already known. In
`review-and-apply` mode it can make small corrections and then apply or reject
the draft without a person, and ingest and research submit their drafts to it
themselves. When the available knowledge cannot settle a question a person
could answer, the reviewer asks that question instead of rejecting: the draft
waits, a knowledge gap records the question, and a curator's answer starts a
fresh review. Rejections and resolved contradictions are filed as knowledge
gaps, and reviews that failed are retried. The reviewer has no tools of its own
to investigate sources; giving it that is the remaining step toward an AI
curator that resolves the whole draft. See `docs/DRAFT_REVIEW.md`.

Documentation starts with a concept and an intended audience, internal or
user-facing. Mycelium selects guidance and a template from configurable
guideline sets, writes and reviews the document internally, and keeps every
version as an immutable revision; revising a document adds a revision to the
same document. On request it opens or updates a GitHub pull request, through a
GitHub App connection or server credentials. After merge, the destination
repository's existing workflow owns deployment; Mycelium does not yet track
whether the pull request merged. Repeated requests should update the intended
document. Today that depends on a model choosing among existing titles, and
only over MCP: the UI always creates a new document. Generated documents remain
outputs and must not silently change the underlying knowledge.

## Implementation posture

SQLite persists relational knowledge; hnswlib indexes statements and names;
Ollama provides embeddings. MCP and HTTP expose the tools, and browser views
support inspection and curation. Write serialization is process-local; use
one server process per data directory.

Keep storage simple, core decisions testable, and external I/O at the edges.
Improve the existing implementation in small verified steps. New providers,
review capabilities, and documentation features should reuse the existing
tools, drafts, and registry.

Project plans, decisions, and delivery issues live in Linear.
