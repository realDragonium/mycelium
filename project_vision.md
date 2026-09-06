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

The server's model-driven loops currently use Anthropic. Supporting GPT as
another provider is a next-phase goal. The substrate and tool contracts
should work independently of the model provider.

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

Current entry points serve different inputs: `ingest_text` runs deterministic
segmentation and connection; `submit_connected_batch` accepts statements an
agent has already extracted; `ingest` and research runs use an LLM to propose
draft operations. Input the deterministic path cannot resolve becomes a flag
for further work.

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
and NOT. Entity-to-entity links describe structural relationships. The current
implementation also supports entity-to-statement links; their removal is
unmerged work in DRA-393 and requires a decision about existing data.

Kinds and link vocabulary can evolve. Direction checks, phrasing validation,
and candidate compatibility rules keep writes and proposals coherent.

## Review and documentation

Today, knowledge proposals accumulate in drafts until a curator resolves and
applies them. The next phase should give an AI curator the tools to investigate,
revise, and resolve the whole draft, including corrections and reconciliation.
When evidence is unavailable, it should surface the specific question requiring
human input. An independent review is the first useful delivery on that path.

Documentation starts with a concept and an intended audience, internal or
user-facing. Mycelium should select suitable guidance and a template, write
and review the document internally, and open a GitHub pull request. After
merge, the destination repository's existing workflow owns deployment.
Repeated requests should update the intended document.

Requests, configurable guideline sets, a document registry, and independent
exposure/conformance review already exist. Complete delivery, repeat updates,
and automated draft curation are next-phase work. Generated documents remain
outputs and must not silently change the underlying knowledge.

## Implementation posture

SQLite persists relational knowledge; hnswlib indexes statements and names;
Ollama provides embeddings. MCP and HTTP expose the tools, and browser views
support inspection and curation. Write serialization is process-local; use
one server process per data directory.

Keep storage simple, core decisions testable, and external I/O at the edges.
Improve the existing implementation in small verified steps. New providers,
automated review, and documentation delivery should reuse the existing tools,
drafts, and registry.

Project plans, decisions, and delivery issues live in Linear.
