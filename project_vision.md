# Mycelium — Project Context

## What it is

Mycelium is an AI-native knowledge base. It is designed to be written by AI, read by AI, and interfaced with by humans through AI rather than directly. Storage is not human-readable and that's intentional — the substrate is optimized for AI retrieval and relational queries, not for human browsing.

Human-facing artifacts (user docs, support content, internal wikis) are projections generated from Mycelium when needed. They are outputs, not the source of truth.

## Why it exists

The team has an existing product knowledge base stored as markdown in git, auto-generated from a codebase via a GitHub Action. It works for simple feature documentation but fails at cross-feature interactions and emergent capabilities — anything where the value lives in how features compose rather than what each feature does in isolation.

The diagnosis: feature-local markdown can't represent relationships well, and the generation pipeline has no concept of cross-feature behavior. The fix isn't better markdown or better prompting — it's a substrate where relationships, concepts, and aliases are first-class, and where AI consumers can query the structure directly.

## Primary consumers (all forms of Claude)

- Coding assistant (primary use case)
- Documentation generation agent
- Future: internal support, error/issue context, user-doc generation, feature design and system-interaction reasoning

Models without MCP access or vision capability are out of scope. Mycelium can assume modern Claude on the consumer side.

## Stack

**Custom naive substrate** — a small in-house store for entities, statements, annotations, names, and their links. SQLite as the persistence layer. No Cypher, no graph DB engine. Built deliberately stupid: correctness over speed, single-writer, no concurrent-write safety, no production-grade guarantees. Acceptable because Mycelium is internal infrastructure during the MVP phase. If it proves out, the substrate gets rebuilt with real engineering; until then, naive wins on iteration speed and on letting the data model evolve without fighting an engine.

**Embedding model** — currently `nomic-embed-text` via Ollama as MVP placeholder. A deliberate choice (Voyage or OpenAI candidates) is a known future step; the model meaningfully affects retrieval quality.

**Vector index** — `hnswlib`. The one place naivete bites soon, so this part isn't naive. Separate indexes for statements and annotations.

**MCP server** — thin layer in front of the substrate. Exposes a small set of retrieval *primitives* to Claude consumers (vector search, neighborhood expansion, statement-by-mention lookup, etc.). Consumers compose these; they never write or read a query language. The substrate's internal shape is hidden behind the MCP surface.

**Ingestion layer** — where most of the system's intelligence lives. Agent-driven extraction with deterministic normalization and validation.

Explicitly not in the stack: Kùzu (archived October 2025) or any of its forks for now, separate vector DBs, separate full-text search, ORMs, graph visualization tools.

## Architecture — two pipelines

**Write pipeline:** Source → Extraction agent → Normalization → Validation → Substrate writer.

- Agent at the front for intelligence (deciding entities, statements, annotations, names, links, kinds).
- Deterministic code in the middle for consistency (canonicalization, embedding generation, dedup checks).
- Transactional write at the end.
- Slow and careful by design. Flags ambiguities for review rather than guessing.

**Read pipeline:** Claude → MCP server → Primitive dispatch → Substrate → Claude.

- Thin MCP layer.
- MCP primitives chosen so consumers can express what they need without a query language.
- Fast and confident. Latency-sensitive.

The asymmetry is intentional: writes are careful, reads are fast.

## Data model

The substrate has three record kinds — **Entity**, **Statement**, **Annotation** — plus **Name** for aliases. Links are typed where useful and untyped where they only need to express association.

**Records**

- **Entity** — name + description. The nouns of the domain (features, concepts, capabilities, surfaces). Same shape for every entity in v1; subtypes deferred until forced.
- **Statement** — text + `kind` discriminator + outgoing typed links to other statements + mentions of entities. The unit that carries truth-claims about the system. The `kind` field is one of:
  - **`event`** — instantaneous occurrence. *"A step gets completed."* Composes via outgoing `triggers` (other events), `produces` (states it brings into being), `ends` (states it terminates).
  - **`state`** — condition that holds over a duration. *"Participant status is Shared."* Composes via `enables` (capabilities), `requires` (other states).
  - **`capability`** — modal claim about what is possible. *"Company user can view full report."* Composes via `requires` (gating states), `varies-by` (states that change its content), `part` (sub-capabilities).
- **Annotation** — text + `kind` discriminator + attachments to one or more statements or entities + mentions of entities. Descriptive metadata that doesn't fit the truth-claim shape of statements: definitions, defaults, calculation rules, examples, notes. Starting `kind` vocabulary: `definition`, `default`, `example`, `note`. Vocabulary grows as needed.
- **Name** — text + the entity it names. For aliases and varied phrasings; gets its own embedding so AI consumers can find entities through any term.

Both Statement and Annotation use a `kind` discriminator, but they discriminate on different axes: `Statement.kind` is about *shape of claim* (when is this true?), `Annotation.kind` is about *purpose of note* (why is this here?). Same plumbing, different axis.

Kinds are discriminator fields, not separate tables. Trivial to add a new kind to either record when the data forces one.

**Links**

- **Statement → Statement**, *typed*. Vocabulary grows as needed (`triggers`, `produces`, `ends`, `enables`, `requires`, `part`, `varies-by`, others as they appear). Edge semantics depend on the kinds being linked — `triggers` only makes sense event→event, `enables` only makes sense state→capability — but the substrate enforces nothing. It trusts the writer to use types coherently. Cycles allowed, multi-parent allowed.

  Each Statement→Statement link may carry an optional **when-condition**: a boolean expression (AND/OR tree) over other statements that must hold for the edge to be active. Expresses "X enables Y, but only when Z is true" without inflating the statement count.

- **Annotation → Statement | Entity**, *attached*. The parent the annotation is about. An annotation can be attached to multiple parents.
- **Statement | Annotation → Entity**, untyped, called `mentions`. Just association — references to entities from inside the body text. Both records use the same mechanism.
- **Entity → Entity**, *typed*. Structural relationships between entities ("checklist step is part of selection flow"). Open vocabulary like statement-link types.
- **Name → Entity**, called `names`.

**Why this shape**

- Statements are n-ary by nature (one fact can mention 3+ entities), which the property-graph "edges are binary" model can't represent without duplication. Making the statement its own record solves it.
- Splitting statements by kind matches their semantic differences: events are instantaneous and trigger things, states persist and enable things, capabilities are modal and conditional. Conflating them into one bucket forces awkward phrasing ("X happens" for things that don't happen) and weakens the meaning of edge types.
- Annotations exist because not all knowledge fits the truth-claim shape. Definitions, defaults, calculation rules, examples — these describe *how something is defined or behaves*, not *what is true at a moment*. Forcing them into Statement form produces vacuous capabilities ("the system can calculate match score") or passive-voice states. Better to give descriptive metadata its own record kind and keep statements pure claims.
- When-conditions on edges express conditional facts directly, rather than forcing them into multiple parallel edges or into extra statements. The condition is metadata about the link, not a separate truth-claim.
- Entity → Entity edges keep structural relationships about referents directly addressable. Statements describe what the system *does*; entity-edges describe what the system *is composed of*. Both are useful traversal primitives.
- Cross-kind links are first-class and structurally trivial — same edge mechanism regardless of kinds. The kinds give validation and consumer queries something to grip without adding plumbing.
- Nesting via typed links lets a consumer drill into any statement to get sub-parts, conditions, variants, or causal follow-ons — progressive disclosure rather than flat prose.
- No global structure is imposed. Any statement is a valid entry point. Traversal is local; the graph as a whole has no starting node.
- Skipping constraints (cycles, multi-parent, type vocab, kind-edge compatibility) is deliberate, not negligent — substrate evolution is a stated value, and constraints fight evolution.

Specific entity kinds, statement link types, entity link types, and annotation kinds are not enumerated upfront. They are introduced as the data forces them.

**Discipline for writers**

When you have something to record, ask which question it answers:

- *"What happens?"* → Statement, kind `event`. Named by what occurs.
- *"What is true?"* → Statement, kind `state`. Named by the condition that holds.
- *"Who can do what, under what conditions?"* → Statement, kind `capability`. Named by what is possible.
- *"How does this work? What is this defined as? What's the default?"* → Annotation, attached to the relevant entity or statement.

Phrasing tells:

- Events are named by *what happens*. States are named by *what is true*. Capabilities are named by *what is possible*. If a sentence resists all three statement kinds, it's probably an annotation — or two facts smashed together.
- Phrases like *"is set to"*, *"becomes"*, *"transitions to"*, *"gets marked as"* usually conceal two statements — an event and the state it produces. Decompose them and link with `produces`.
- When the actual event behind a state transition can't be named, that's a knowledge gap surfacing — not a modeling limitation. Capture what's known and flag the rest.

## Deployment direction

Local-first for development. Eventually hosted, with auth on the MCP server, so non-technical teammates can use it through Claude. They never touch the substrate directly. The substrate doesn't change between local and hosted — only the deployment.

## Project values / posture

- Optimal AI-usage outcomes over operational maturity. Battle-tested infrastructure is not a priority for this project.
- Naive MVP first. If it proves the thesis, real engineering follows; if it doesn't, no infrastructure was wasted on something that didn't matter.
- Markdown-as-source-of-truth is rejected. The bet is that AI-as-interface is reliable enough to be the only interface.
- Substrate evolution is a feature, not a risk — the schema is expected to change as understanding improves.
- Ingestion is where intelligence lives. Storage and retrieval are mostly plumbing; the agent that decides what knowledge looks like is the thing worth designing carefully.
