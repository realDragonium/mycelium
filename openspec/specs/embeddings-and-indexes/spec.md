# embeddings-and-indexes Specification

## Purpose
Turns statement and entity-name text into vectors through one configured embedding provider and keeps the statement and name vector indexes durable, consistent with the knowledge base, and usable in degraded form while the provider is unavailable.

## Requirements

### Requirement: Embedding provider selection
The system SHALL embed through the provider named by `MYCELIUM_EMBED_PROVIDER`, either `ollama` (the default) or `openai`; any other value MUST fail with an error naming the allowed values.

#### Scenario: Default provider
- **WHEN** `MYCELIUM_EMBED_PROVIDER` is unset
- **THEN** embeddings are requested from Ollama

#### Scenario: Unknown provider
- **WHEN** `MYCELIUM_EMBED_PROVIDER` is `cohere`
- **THEN** embedding fails with an error saying it must be one of `ollama`, `openai`

### Requirement: Embedding model selection
The system SHALL use the model named by `MYCELIUM_EMBED_MODEL`, defaulting to `nomic-embed-text` for Ollama, where the older `EMBED_MODEL` is honoured when `MYCELIUM_EMBED_MODEL` is unset, and to `text-embedding-3-small` for OpenAI. A blank model name MUST be rejected.

#### Scenario: Legacy model variable
- **WHEN** the provider is Ollama, `MYCELIUM_EMBED_MODEL` is unset and `EMBED_MODEL` is `custom-embed`
- **THEN** Ollama is asked for `custom-embed` embeddings

#### Scenario: OpenAI default model
- **WHEN** the provider is `openai` and no model is configured
- **THEN** `text-embedding-3-small` is used

### Requirement: Ollama endpoint
The Ollama provider SHALL send requests to `OLLAMA_URL`, defaulting to `http://localhost:11434`.

#### Scenario: Remote Ollama
- **WHEN** `OLLAMA_URL` is `http://embedder.internal:11434`
- **THEN** embedding requests go to that host

### Requirement: OpenAI embeddings
The OpenAI provider SHALL read `OPENAI_API_KEY` for each request, failing without one, send at most 100 texts per request and return vectors in input order. Its token usage MUST be recorded under the `embedding` action, and while AI spending is paused its requests MUST fail like an unavailable provider (see the `ai-providers` capability).

#### Scenario: Missing key
- **WHEN** the provider is `openai` and `OPENAI_API_KEY` is unset
- **THEN** embedding fails with an error saying the key is required

#### Scenario: Large batch
- **WHEN** 250 texts are embedded at once
- **THEN** three requests are sent and the 250 vectors come back in input order

### Requirement: Vector dimension
Every embedding SHALL have 768 dimensions; OpenAI requests MUST ask for 768 dimensions, and a response of any other size MUST be treated as an embedding failure naming the returned and expected sizes.

#### Scenario: Model returns the wrong size
- **WHEN** the configured Ollama model returns 1024-dimensional vectors
- **THEN** each embedding fails with an error reporting 1024 dimensions where 768 were expected

### Requirement: Embedding request timeout
Each embedding request SHALL time out after `EMBED_TIMEOUT_S` seconds, default 30; a value of zero or less MUST be rejected.

#### Scenario: Unresponsive provider
- **WHEN** the provider accepts a connection but never answers
- **THEN** the request fails after `EMBED_TIMEOUT_S` seconds instead of holding a worker thread

### Requirement: Embedding retries
The system SHALL retry a failed embedding request up to twice for connection errors and for HTTP 408, 409, 429 or 5xx responses, waiting 0.5 seconds doubling up to 4 seconds and honouring a `Retry-After` header up to 20 seconds; other HTTP errors and malformed responses MUST fail without retry.

#### Scenario: Rate limited
- **WHEN** OpenAI answers 429 with `Retry-After: 3` and then succeeds
- **THEN** the request is retried after about 3 seconds and the embedding succeeds

#### Scenario: Bad credentials
- **WHEN** OpenAI answers 401
- **THEN** the embedding fails at once without a retry

### Requirement: Fail fast after a provider failure
After an embedding request fails, the system SHALL fail every embedding request immediately for 30 seconds without contacting the provider, so dependent reads fall back at once rather than each waiting for timeouts.

#### Scenario: Searches during an outage
- **WHEN** an embedding fails and a search arrives 10 seconds later
- **THEN** the search's embedding fails immediately and the search uses its keyword fallback

### Requirement: Query embedding cache
The system SHALL cache up to 2,048 successful single-text embeddings, keyed by the embedder identity and the exact text, and MUST NOT cache failures.

#### Scenario: Repeated query
- **WHEN** the same search query is run twice
- **THEN** the provider is called once

#### Scenario: Failure then recovery
- **WHEN** an embedding fails and the same text is embedded after the provider recovers
- **THEN** the provider is called again and the new vector is used

### Requirement: Per-model similarity thresholds
The system SHALL take its similarity thresholds from the configured provider and model, and a model with no tuned values MUST use its provider's default model's values and log a warning the first time.

#### Scenario: nomic-embed-text values
- **WHEN** the embedder is Ollama `nomic-embed-text`
- **THEN** the write-time near-duplicate threshold is 0.85, the `find_duplicates` threshold 0.92, `discover_facts` exists 0.85 and near 0.6, the name-match and connection endpoint floors 0.5, entity search 0.3, entity duplicates 0.75 and decomposed sub-query deduplication 0.95

#### Scenario: text-embedding-3-small values
- **WHEN** the embedder is OpenAI `text-embedding-3-small`
- **THEN** those thresholds are 0.79, 0.88, 0.79 and 0.45, 0.35, 0.20, 0.66 and 0.93 respectively

#### Scenario: Untuned model
- **WHEN** the embedder is Ollama with a model that has no tuned values
- **THEN** the `nomic-embed-text` values are used and a warning is logged once

### Requirement: Statement and name vector indexes
The system SHALL keep two cosine-similarity vector indexes in the data directory: `mycelium.vec` over statement texts and `mycelium-names.vec` over entity names and aliases. Similarity scores reported by searches MUST be cosine similarity, 1 minus cosine distance.

#### Scenario: Identical text
- **WHEN** a search query is the exact text of a statement
- **THEN** that statement's cosine score is about 1.0

### Requirement: Index embedder identity
Each index file SHALL record the embedder that built it as `{"embedder": "<provider>/<model>/768"}` in a sidecar named `<index file>.meta.json`; an index with no sidecar MUST be treated as built by `ollama/nomic-embed-text/768`, and the sidecar is then written.

#### Scenario: Index predating sidecars
- **WHEN** the server starts with `mycelium.vec` but no `mycelium.vec.meta.json` and the embedder is the Ollama default
- **THEN** the index is loaded without re-embedding and `mycelium.vec.meta.json` is written

### Requirement: Startup index rebuild
At startup the system SHALL load each index only when its file exists, carries no dirty marker and its recorded embedder equals the configured one; otherwise it MUST discard the index and rebuild it by re-embedding every statement or name, so vectors from two embedders are never mixed. An unreadable sidecar MUST count as a mismatch.

#### Scenario: Switching provider
- **WHEN** the indexes were built with Ollama and the server restarts with `MYCELIUM_EMBED_PROVIDER=openai`
- **THEN** both indexes are rebuilt with OpenAI embeddings and their sidecars record the OpenAI embedder

#### Scenario: Missing index file
- **WHEN** `mycelium-names.vec` is absent, as after restoring a backup without vectors
- **THEN** the name index is rebuilt from the names in the database

### Requirement: Rebuild progress and failure
An index rebuild SHALL re-embed in batches of 100, log its progress (`rebuilding <label> vector index: <done>/<total> re-embedded`), and keep each row's existing vector id; a rebuild that cannot embed MUST fail startup with the reason rather than serve a partial index. Startup state reporting is defined by the `operations` capability.

#### Scenario: Provider down during a required rebuild
- **WHEN** the statement index must be rebuilt and the embedding provider is unavailable
- **THEN** startup fails and reports the embedding error

### Requirement: Index crash safety
Every write that changes an index SHALL create a `<index file>.dirty` marker before changing it and persist the index to disk before releasing the write lock, removing the marker only after the database transaction commits; a marker present at startup MUST cause that index to be rebuilt.

#### Scenario: Crash between index and database
- **WHEN** the process dies after an index change but before the marker is removed
- **THEN** the next startup rebuilds that index from the database

#### Scenario: Persist failure
- **WHEN** persisting the index or removing the marker fails after a commit
- **THEN** the write still succeeds, the marker stays until the next startup, and that startup rebuilds the index

### Requirement: Stranded name vectors are pruned
When the name index is loaded, the system SHALL remove vectors that no longer map to a name, so they cannot occupy search results.

#### Scenario: Names merged by a migration
- **WHEN** a migration removed name rows but left their vectors in `mycelium-names.vec`
- **THEN** startup deletes those vectors and persists the index

### Requirement: Writes succeed without embeddings
A statement or name write SHALL succeed when its text cannot be embedded, saving it without a vector; `upsert_statement`, `replace_text` and a text-changing `patch_statement` MUST then return `embedding_pending: true`, `upsert_statements` MUST list the affected statement ids in `embedding_pending`, and name responses are unchanged.

#### Scenario: Statement written during an outage
- **WHEN** the provider is down and a writer calls `upsert_statement` with "Invoice exports are ready"
- **THEN** the statement is saved, the response has `embedding_pending: true` and `near_duplicates: []`

#### Scenario: Batch with pending vectors
- **WHEN** `upsert_statements` writes three statements during an outage
- **THEN** `embedding_pending` lists the three new statement ids

### Requirement: Edited text never matches its old wording
When a statement's or name's text changes, the system SHALL replace its vector with one for the new text or, when the new text cannot be embedded, remove the old vector until the pending worker embeds the new text. A change that leaves the text unchanged, such as a kind-only `patch_statement`, MUST NOT re-embed or touch the index.

#### Scenario: Edit during an outage
- **WHEN** a statement reading "Workspace login uses the old form" is changed to "Workspace login uses SSO" while the provider is down
- **THEN** a later search for "Workspace login uses the old form" does not return that statement

#### Scenario: Kind-only patch
- **WHEN** a writer patches only a statement's `kind`
- **THEN** the embedder is not called and no dirty marker is written

### Requirement: Pending embeddings are retried in the background
The system SHALL run a background worker that, every 30 seconds, embeds statements and names that have no vector, up to 256 per pass and repeating while passes come back full, and that MUST skip any row whose text changed or that gained a vector meanwhile. Setting `MYCELIUM_DISABLE_EMBED_WORKER=1` MUST disable it, and startup logs the pending counts.

#### Scenario: Provider recovers
- **WHEN** a statement was saved without a vector and the provider becomes available
- **THEN** within about 30 seconds the statement is embedded and semantic search can return it without a `retrieval` marker

#### Scenario: Text edited while embedding
- **WHEN** a pending statement's text changes while its old text is being embedded
- **THEN** the stale vector is not stored and the statement stays pending

### Requirement: Pending statements stay out of semantic results
A statement or name without a vector SHALL NOT appear in vector-ranked results, including `search_statements`, `search_entities`, `discover_facts`, `find_duplicates` and write-time near-duplicate warnings, while exact reads such as `get_statements`, `list_statements` and `grep_statements` MUST still return it.

#### Scenario: Pending statement found by grep
- **WHEN** a statement is pending embedding
- **THEN** `grep_statements` finds it by a word in its text while `search_statements` with an available provider does not return it

### Requirement: Degraded reads while the provider is unavailable
While the embedding provider cannot embed a query, `search_statements` and `search_entities` SHALL fall back to keyword or name-substring matching marked `retrieval: "keyword"`, so Ask and documentation runs keep working with weaker retrieval, whereas `discover_facts` MUST report the error. `find_duplicates` compares only stored vectors and SHALL keep working. Fallback ranking is specified in the `search-and-ask` capability.

#### Scenario: Ask during an outage
- **WHEN** the provider is down and an asker calls `ask`
- **THEN** the run retrieves through keyword fallback and returns an answer rather than an error

#### Scenario: Duplicate audit during an outage
- **WHEN** the provider is down and a curator calls `find_duplicates`
- **THEN** it returns the near-duplicate pairs among statements that already have vectors

### Requirement: Write-time near-duplicate warning
After embedding a new or changed statement, `upsert_statement`, `upsert_statements` and a text-changing `patch_statement` SHALL report up to 5 existing statements whose cosine score is at or above the model's near-duplicate threshold, excluding the statement itself, each as `{id, text, score}` with `text` cut to 100 characters; `upsert_statements` reports them as a map from statement id to that list, listing only statements that have matches.

#### Scenario: Close wording exists
- **WHEN** a writer adds "An admin can export invoices to CSV" and "Admins can export invoices as CSV" exists with score 0.93 under `nomic-embed-text`
- **THEN** the response's `near_duplicates` includes the existing statement with its score

### Requirement: Audience-restricted vector ranking
Inside a documentation run's audience boundary, statement vector searches SHALL rank only the statements that audience may see, so a top-k result is the k nearest visible statements rather than what survives filtering of a global top-k. Visibility is defined by the `audiences` capability.

#### Scenario: Hidden near neighbours
- **WHEN** the 10 statements nearest a query are hidden from an external documentation run and the run searches with `limit: 5`
- **THEN** the run receives the 5 nearest statements visible to its audience
