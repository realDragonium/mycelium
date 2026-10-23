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
- Agents working in a product's codebase, which curate the knowledge base by
  claiming work and proposing changes with evidence from the code.
- Documentation agents running on the server.
- Support and product reasoning workflows, including external ones whose
  connection is scoped to an audience.

The server's model-driven actions (ask, ingest, documentation and its
planning, draft review, audience labelling, the connect pass and alias
discovery) go through one provider boundary, `mycelium.ai`, and an
administrator chooses Claude or OpenAI GPT for each action. Every model call
is recorded with its estimated cost. The substrate and
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

Current entry points serve different inputs: `ingest` uses an LLM to propose
draft operations from prose; statements an agent has already extracted go in
through `upsert_statements` and `submit_draft`. The internal draft reviewer then
judges links, duplicates, and contradictions against the graph.

Evaluation must start with source prose and expected statements, relationships,
and matches to existing knowledge. Measuring whether already-extracted
statements retain cues for an existing graph does not test this workflow.
The repository's evaluation sets for ingest and Ask use invented product data;
real knowledge bases are evaluated only outside the repository.

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
the draft without a person, and ingest submits its own drafts to it. When the
available knowledge cannot settle a question a person could answer, the
reviewer asks that question instead of rejecting: the draft waits, a knowledge
gap records the question, and a curator's answer starts a fresh review. Rejections and resolved contradictions are filed as knowledge
gaps, and reviews that failed are retried. The reviewer has no tools of its own
to investigate sources. Evidence comes from the producer instead: an agent
working in the product's codebase attaches the code, screen or document that
supports each proposed operation, and the reviewer weighs it. See
`docs/DRAFT_REVIEW.md`.

Knowledge health lists what needs a curator: isolated statements, statements
naming no concept, concepts without a description, unlabelled statements, open
gaps and out-of-date documents. A server-side connect pass proposes links for
the obvious cases; agents with access to the code claim the rest as curation
work. Either way the result is a draft. See `docs/KNOWLEDGE_HEALTH.md`.

Documentation is written for an audience. Audiences are configurable; the
default four are internal and external, each technical and non-technical. AI
labels which statements each audience may see, a curator can override a label,
and an unlabelled statement is visible to internal audiences only. A
documentation run can only read and cite what its audience may see; the same
boundary applies to Ask and MCP connections scoped to an audience. See
`docs/AUDIENCES.md`.

A writing profile targets one audience and supplies guidance and templates.
For each profile a planner proposes which documents should exist; approved
items are written and reviewed internally. Every version is kept as an
immutable revision. A document's identity is its profile, type and anchor
concept, so a repeated request revises the same document. A document whose
cited statements change goes out of date, and a profile can propose or make
the revision automatically. On request Mycelium opens or updates a GitHub pull
request and follows whether it merged; after merge, the destination
repository's workflow owns deployment. Generated documents remain outputs and
must not silently change the underlying knowledge.

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
