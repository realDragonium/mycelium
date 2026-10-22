# Mycelium feature inventory

Audit of `origin/master` at `8064aab` (2026-10-22). This is a read-only audit: no product code was changed.
Test baseline: `uv run pytest`, 1663 passed in 86s.

**Conventions**

- **Surfaces:** MCP = MCP tool. HTTP = the auto-generated `POST /<kebab-name>` route every `@tool` gets (`http.py:364`), or a hand-written `/api/*` route. `/ui` and `/cockpit` = a browser UI calls it. Loops = it is offered to the internal model loops. Every reader-role tool is auto-offered to the ask, ingest, docgen and research loops (`ask/substrate.py:146`), except those on a denylist (`ask/substrate.py:45-80`).
- **Verdicts:** keep, complete, merge-into-X, remove, fix (works but has a defect).
- **Size:** S is under a day, M is 1–3 days, L is more than 3 days.
- **Evidence:** claims carry `file:line`. Anything inferred rather than read or run says *(inferred)*.

The MCP tool surface is **87 tools**, all in `src/mycelium/server.py`. The `cleanup/mcp-surface` session is changing this surface in parallel, so coordinate any tool removal listed here with it.

---

## 1. Read path

| Capability | What it does | Surfaces | Tests | Overlap | Verdict | Size |
|---|---|---|---|---|---|---|
| `search_statements` (`server.py:1878`) | Embeds the query and runs a vector search over hnsw. Adds a name/alias boost (`_alias_entity_boost` :1726) and filters by mentions, kind and min_score (:1752). Hits are fully hydrated. Optional BFS `depth`/`direction` expansion (`_expand_graph` :1795). `limit` has no upper bound. | MCP, HTTP, `/cockpit` Find "semantic" (`cockpit/api.js:144`), draft reviewer (`draft_review_runs.py:267`), `retrieve_context`, every loop prompt | 14 files | Canonical semantic read | **keep**. Cap `limit`. Optionally drop `depth` (see recommendations) | S |
| `survey_statements` (`server.py:2133`, `survey.py`) | Splits the query on conjunctions and punctuation (`survey.py:152`). Runs a **raw cosine** top-k per part, with no alias boost and no mention or kind filter. Unions the results and ranks them by how many parts hit. The output shape is the same as `search_statements`, and its own docstring calls the two "interchangeable to a consumer" (:2150). | MCP, HTTP, hard-coded recon step in ask (`ask/loop.py:488`) and docgen (`docgen/loop.py:673`), `/cockpit` Find "survey", ingest/research floor sets | `test_survey.py` (25) | **Duplicate of `search_statements`** plus a decomposition step. The cockpit discards survey's ranking by re-sorting on score (`cockpit/api.js:150`) | **merge into `search_statements(decompose=True)`** | M |
| `retrieve_context` (`server.py:4133`, `ask/retrieval.py`) | A composite read with no model turns: for 1–3 names it does an entity prefix or semantic lookup, then `get_entity`, then a mention search, then a one-hop `get_statements`. Hard caps of 3/8/12/20. | MCP, HTTP, ask prompt "Prefer retrieve_context" (`ask/prompts.py:81`) | `test_ask_retrieval.py` (14) | Pure composition of five public tools, added deliberately on 2026-09-07 (`63bf99f`) with a round-trip test (`test_ask_retrieval.py:270`) | **keep** | — |
| `discover_facts` (`server.py:4550`) | Batch pre-write check: each candidate text gets an `exists` / `near` / `new` verdict at cosine 0.85 / 0.6. | MCP, HTTP, ingest/research reconcile floor, 4 repo skills, docgen prompts | `test_http.py`, `test_ingest.py` | Same vector primitive, but a distinct batch-verdict contract | **keep** | — |
| `grep_statements` (`server.py:5053`) | Literal substring match plus alias-name mention expansion, paged. | MCP, HTTP, `/cockpit` Find "grep", `/ui` alias suggestions | `test_http.py`, `test_store.py` | Only lexical read | **keep** | — |
| `find_statement_connections` (`server.py:1979`, `statement_connections.py`, `store/connection_graph.py`) | Bounded BFS route-finding between ids or text-matched statements, with optional required branches. Hops ≤8, routes ≤20, about 64k characters of output. | MCP, HTTP, ask loop (auto-offered; no prompt names it) | `test_statement_connections.py` (22), `test_connection_graph.py` (15) | Only graph-route read | **keep** | — |
| `list_statements` (`server.py:4326`) | Pages statements, filtered by entity, name or kind. Returns text only. `limit` has no upper bound. | MCP, HTTP, ingest/research prompts | `test_http.py`, `test_store.py` | Enumeration; no UI uses it (the UIs use `/api/data`) | **keep**, cap `limit` | S |
| `get_statements` (`server.py:4077`) | Batch fetch by id, fully hydrated, plus a `missing` list. | MCP, HTTP, `/cockpit` inspect, draft reviewer, docgen review | 10 files | — | **keep** | — |
| `get_entity`, `list_entities`, `search_entities` (`server.py:4189/4233/4267`) | Entity hydrate, alias-aware prefix list, and semantic name-index search. | MCP, HTTP, `retrieve_context`, prompts | 5 / 8 / 4 files | Prefix vs semantic; both are used by `retrieve_context` | **keep** | — |
| `get_mention_candidates` (`server.py:1860`, `mention_candidates.py`) | Finds statements whose text matches an entity's names, for curating names. | MCP, HTTP, `/ui` names workspace via a **separate** `GET /api/mention-candidates` (`http.py:946`) | `test_mention_candidates.py` (4) | The GET route duplicates the auto-generated POST route. Offered to every loop, but no prompt names it | **keep**. Fold the GET route into the tool route, and consider adding it to the loop denylist | S |
| `ask` (`server.py:2229`, `ask/`) | Model loop: survey recon, then the read tools, then a structured answer. `depth` = standard or quick; `verbose` returns the full result. | MCP, HTTP + SSE streaming, `/cockpit` Ask | `test_ask*.py` (5 files) | Synthesis, not retrieval | **keep** | — |
| `/api/data` (`http.py:602`, `store/read_models.py:26`) | Dumps the whole substrate (see §11). | Both UIs, before they mount | `test_http.py` | Replaces per-screen reads | **fix, then replace** (§11) | S stopgap, L replacement |

**Loop tool surface (observation).** Every loop is offered every reader tool that is not on the denylist. That includes tools its prompt never names: `retrieve_context`, `find_statement_connections` and `get_mention_candidates` in ingest, docgen and research. Their schemas cost tokens on every turn *(inferred)*. Removing a read tool shrinks every loop's toolset. `tests/test_ask.py:824` pins the offered set.

---

## 2. Authoring (direct writes)

| Capability | What it does / where | Surfaces | Tests | Verdict |
|---|---|---|---|---|
| `upsert_statement`, `upsert_statements` (`server.py:2853`, `:3322`) | Typed statement writes. Batch writes support `@N` references, link-direction checks, the phrasing gate and `near_duplicates` hints (`_near_duplicates` :1484, cosine ≥0.85). | MCP, HTTP, ingest/draft replay | 16 / 6 files | **keep** |
| `patch_statement`, `replace_text` (`:3472`, `:3431`) | Focused edits. | MCP, HTTP, `/cockpit` inspect edit (`api.js:319`) | 4 / 6 files | **keep** |
| `add_links`, `remove_links` (`:3991`, `:4050`) | Statement links, including `when` trees. Entity endpoints are rejected (`link_authoring.reject_entity_statement_additions`, called at `server.py:472` and `:4019`; the two checks partly overlap). | MCP, HTTP | 5 / 1 files | **keep** |
| `merge_statements`, `delete_statement` (`:3786`, `:3868`) | Consolidation and removal; admin role. | MCP, HTTP | 4 / 7 files | **keep** |
| `when` expressions (`when_expression.py`) | AND/OR/NOT over statements on links. | via links | `test_when_*` | **keep** |
| Phrasing validation (`phrasing.py`, `phrasing_cues.py`; `_phrasing_gate` `server.py:1599`) | Runs on every statement write and at draft replay. A catalogue of compound, precondition, universal, hedge, modal and similar checks. **Loads spaCy `en_core_web_sm`.** | All write paths; the draft reviewer is shown the violations (`f9346aa`) | `test_phrasing.py` (90), `test_phrasing_endpoints.py` | **keep, with an owner decision.** See below |
| Mention derivation and worker (`mentions.py`, `mention_worker.py`, `store/statement_mentions.py`) | Derives statement↔name mentions from text and recomputes them when names change. | Internal | `test_mention_*` | **keep** |
| Plurals (`plurals.py`) | Generates a plural name for each name. | Internal | `test_plurals.py` | **keep** |

### spaCy phrasing gate: cost and verdict

**What it costs (measured on this machine):**
- 0.64s to load the model once per process (lazy).
- **3.4 ms per `phrasing.check`**.
- About +50 MB RSS: 152 MB with the model loaded vs 100 MB for the server import alone.
- About 45 MB on disk: `spacy` 22 MB, `en_core_web_sm` 15 MB, `thinc` 3.6 MB, `blis` 3.9 MB. spaCy also pulls in about 17 transitive packages (`catalogue`, `confection`, `cymem`, `preshed`, `srsly`, `thinc`, `typer`, `wasabi`, `weasel`, …).
- The model is pinned by wheel URL in `pyproject.toml` because it is not on PyPI.

**How much depends on spaCy:** `phrasing.py` makes 31 calls into the parse tree (`pos_`, `dep_`, `tag_`, `lemma_`, …). The structural checks need it (compound clauses, modals, copula and property shapes, precondition subordinators). Hedges and hidden event/state phrases are plain regex.

**Verdict: keep. It earns its place; it is not the kind of "local-model approach" the direction rules out.**
- **What it is:** a deterministic linter that uses a POS tagger. It is not where any judgement or generation happens.
- **No cheaper alternative:** replacing it with an LLM call would add 0.5–3 s and per-write cost to every statement write, including drafts and batch upserts *(inferred)*. Removing it would drop a guard that the automatic reviewer and replay now rely on (`f9346aa`, `_draft_operation_findings`).
- **Cost is small:** at 3.4 ms per statement, a 100-statement batch adds about 0.35 s.

**Owner decision needed:** does "local models are out except embeddings" also cover a POS tagger? If yes, the replacement is a regex-only catalogue: drop the structural checks and keep hedges, universals and hidden event/state. That is size M; `test_phrasing.py` would need rewriting. I do not recommend it.

---

## 3. Entities, names and aliases

| Capability | Where | Surfaces | Tests | Verdict |
|---|---|---|---|---|
| `upsert_entity`, `delete_entity`, `merge_entities` | `server.py:2802/3736/3585` | MCP, HTTP, `/cockpit` (`api.js:382`), names workspace | 12 / 5 / 3 files | **keep** |
| `upsert_name`, `rename_name`, `move_name`, `delete_name` | `server.py:3560–3705`. Write-time collision guard at `store/names.py:447` | MCP, HTTP, `/cockpit` | 3–5 files each | **keep** |
| Entity↔entity links (`add_entity_links`, `remove_entity_links`) | `server.py:4710/4757`, `store/entity_links.py` | MCP, HTTP, `/ui` entities graph | 3 / 1 files | **keep** |
| Names & aliases workspace | `names_workspace.py` (507 lines), `/api/names-workspace*` (`http.py:1187-1219`), `ui/names-workspace.jsx` (mounted in both UIs) | HTTP, `/ui`, `/cockpit` | `test_names_workspace.py` (16) | **keep** |
| Alias suggestions (AI proposes missing names) | `alias_suggestions.py` (582 lines), `/api/alias-suggestions*` (`http.py:2159-2215`), `ui/alias-suggestions.jsx`; ingest emits `alias_suggestion` ops (`ingest/prompts.py:98-106`) | HTTP, both UIs | `test_alias_suggestions.py` (21) | **keep, fix.** This is vocabulary growth, not duplicate detection. But an alias op inside a draft makes the whole draft advisory-only (§6) |
| **Entity↔statement links (DRA-393)** | **Removed.** Merged as PR #63 on 2026-09-07 (`d40b369`, an ancestor of master). Schema v14 drops `entity_statement_links` (`migrations.py:806-822`). New ones are rejected at 7 call sites (wrapper, `add_links`, draft submit/edit/replay, ingest normalisation). Upgrade gate: `require_rescued_entity_statement_links` (`migrations.py:783`). The data decision is documented in `docs/ENTITY_STATEMENT_MIGRATION.md`: rescue by hand, then refuse to upgrade until the table is empty. | Residue is read-only: history rendering of old audit rows (`http.py:626,646`, `ui/activity.jsx:12,243,333`), upgrade and archive guards (`backup.py:181,711-731`) | `test_entity_statement_links.py` (2), `test_migrations.py`, `test_backup.py` | **complete.** `project_vision.md:70-72` still calls it unmerged; fix that sentence. Keep the guards while pre-v14 databases or archives can exist. Keep the history rendering so the audit log stays readable |

---

## 4. Vocabulary (glossary)

| Capability | Where | Surfaces | Tests | Verdict |
|---|---|---|---|---|
| Statement kinds (`list_`/`upsert_`/`delete_statement_kind`) | `server.py:4781-4880`, `store/glossary.py` | MCP, HTTP, `/ui` glossary, `/cockpit` boot | list: 4 files; upsert/delete: **no tool-level test** (store-level coverage not checked) | **keep**. Add tool tests (S) |
| Link types (`list_`/`upsert_`/`delete_link_type`) | `server.py:4634-4920` | MCP, HTTP, `/ui` glossary | list: 7; upsert: 1; delete: 1 | **keep** |
| Entity link types | `server.py:4817`, `:5021-5050` | MCP, HTTP, `/ui` glossary | list: 3; upsert/delete: **no tool-level test** | **keep**. Add tool tests (S) |
| Kind↔link admissibility matrix | `store/kind_link_matrix.py`, `link_rules.py` | Internal write checks, backup | `test_kind_link_matrix.py` | **keep** |
| **Link-type aliases** (`list_`/`upsert_`/`delete_link_type_alias`) | `server.py:4925-5018`, `store/link_type_aliases.py`. The schema comment calls them "the vocabulary layer beneath cue matching" (`store/kernel.py:398-407`) | MCP, HTTP. **No code reads them** other than the list tool, backup (`backup.py:102`) and `scripts/audit_link_type_aliases.py`. The cue-matching consumer was `connect/`, deleted in `8064aab` | `test_link_type_aliases.py` (4 files) | **owner decision: remove or wire up.** `8064aab` explicitly kept this vocabulary, but nothing consumes it now. If kept, ingest/reviewer prompts should read it. Otherwise remove the tools, the table and the script (M) |
| Dead alias schema | `link_type_alias_embed_queue` table (`store/kernel.py:422-430`), `link_type_aliases.embedding` column; enqueue in `migrations.py:658,697,742` | Nothing reads or writes it (`8064aab` commit message) | — | **remove** via a migration (S) |

---

## 5. Ingestion and research

| Capability | What it does | Surfaces | Tests | Verdict | Size |
|---|---|---|---|---|---|
| `ingest` (`server.py:2288`, `ingest/`) | LLM loop that turns prose into an **open** draft (`ingest/draft.py:87-95`, `created_by=None`). A reconcile floor and an adjacency floor must be met before emit (`ingest/loop.py:71-76`). | MCP, HTTP, `/cockpit` Ingest | `test_ingest.py` | **keep, complete.** The draft is never submitted, so automatic review never starts (§6). `find_duplicates` is in `_RECONCILE_TOOLS` (`ingest/loop.py:72`) even though it takes no candidate text, so it lets the loop satisfy the reconcile gate without checking its own candidates *(inferred)* | S |
| Research runs (`start_research`, `list_research_runs`, `get_research_run`, `list_research_sources`; `research/`, `research_runs.py`, `research_store.py`) | Topic plus a configured GitHub repo. Shallow-clones the repo (`research/sources.py:141-205`), explores it with `ws_list_files`/`ws_grep`/`ws_read_file` (at least 3 reads, `research/loop.py`), then emits through ingest's draft writer. Async, with run records. | MCP, HTTP, `/cockpit` Research (`research.jsx`); settings in `/ui` | 5 test files | **keep, fix.** Not a duplicate of ingest: the input is code, not prose, and it reuses ingest's emitter, validation and `agentloop`. Problems: (a) open drafts are not submitted (same as ingest); (b) GitHub App connections are refused for sources (`sources.py:66-69`) although docgen accepts them; (c) the stale cockpit hint "set MYCELIUM_SOURCES" (`research.jsx:102`); (d) the Docker runtime image has no `git` (`docker/Dockerfile:39-41`), so clones fail there *(inferred)*. Whether it is used in production is not determined | S each |
| `agentloop.py` | Shared tool-loop driver for ask, ingest and research. | Internal | indirect | **keep** | — |

---

## 6. Drafts, review and curation

| Capability | What it does | Surfaces | Tests | Verdict |
|---|---|---|---|---|
| Draft routing | A drafter-role principal's mutation (any `_MUTATION_PREFIXES` tool, `server.py:567`) is queued on their session draft instead of written live (`server.py:478-493`). | MCP, HTTP | `test_drafts.py` | **keep** |
| Draft lifecycle: `get_draft`, `list_drafts`, `list_my_drafts`, `submit_draft`, `discard_draft_op`, `attach_draft_source`, `find_my_draft_by_source`, `set_draft_review_evidence`; HTTP `/api/drafts*` (`http.py:1624-1930`) | Inspect, edit, submit, withdraw, approve, reject. | MCP, HTTP, `/ui` (approve, reject, withdraw), `/cockpit` (submit, withdraw, review, **but no approve or reject**: `cockpit/api.js:366-374`) | `test_drafts.py`, `test_http.py` | **keep**. HTTP submit only requires a principal and does not check the caller is the draft's creator (`http.py:1775`). That may be intended for curators; *not determined* |
| Manual curation tools: `inspect_draft_review`, `append_draft_correction`, `revise_draft_operation`, `strike_draft_operation`, `record_draft_review`, `apply_reviewed_draft` (`server.py:5669-6590`) | Writer-role curation with knowledge preconditions and a durable receipt. | MCP, used internally by the reviewer | `test_reviewed_application.py` (32) | **keep**. These are also the recovery path |
| Internal AI reviewer (`draft_review_runs.py`, `draft_review_model.py`, `draft_review_settings.py`, `draft_review_store.py`; `request_draft_review`, `get_draft_review_run`) | Starts automatically on submit (`draft_review_runs.on_submitted` :156). One structured model call judges the draft against the 5 closest live statements per new statement. Up to 8 corrections; then record, then apply or reject. Retries once with the earlier failure attached (`ddc3a16`). Files knowledge gaps on reject and on contradictions. Settings live in `mycelium-prompts.db`. Modes: `off`, `review-only`, `review-and-apply`, plus a separate application gate. Fresh instances start with everything off. | MCP, HTTP `/api/drafts/{id}/review`, `/api/draft-review/settings`, both UIs (Run review) | `test_internal_draft_review.py` (34), `test_draft_review_settings.py` (18) | **keep, complete** |

**Can a draft reach applied knowledge with no human? Yes, but only in a narrow case.** `test_internal_draft_review.py:227` shows a drafter's `upsert_entity` going to `submit_draft` and ending `approved`, against a stub model. All of these must hold: mode `review-and-apply`, application gate on, a model set, a real writer service-account reviewer who is not the creator, and provider credentials present.

The chain breaks at these points (evidence):
1. **Ingest and research drafts are created open and never submitted** (`ingest/draft.py:87-95`, `research_runs.py:135`). Someone has to call `submit_draft` or click Submit.
2. **Any `alias_suggestion` op makes the entire draft advisory-only** (`draft_review_runs.py:433-438`). Ingest emits such ops, and once the aliases are decided nothing re-runs the review.
3. **Some failures leave the draft `submitted` with no retry and no sweep:**
   - the reviewer cannot be resolved (`draft_review_runs.py:144-152`, `:312-316`);
   - a provider error on the second attempt (`:518`);
   - a restart, which marks the run failed and starts nothing new;
   - enabling review, which does not sweep the existing backlog (`docs/DRAFT_REVIEW.md`).
4. **The reviewer has no investigation tools and cannot escalate a question to a person.** `needs_context` is converted into a failure, then a reject (`:447`). The vision's "surface the specific question requiring human input" is not built; a filed gap is the only trace.
5. **Mode off or no model:** the error is swallowed and the draft waits. This is by design.

---

## 7. Duplicate detection

| Mechanism | Detects | Algorithm | Surfaces | Verdict |
|---|---|---|---|---|
| `_near_duplicates` on write (`server.py:1484`) | Near-duplicates of a just-written statement | hnsw k=5, cosine ≥0.85 | Returned by statement writes | **keep** |
| `discover_facts` | Whether candidates already exist, before writing | k=5, 0.85 / 0.6 | Loops, MCP | **keep** |
| `find_duplicates` (`server.py:4377`) | Duplicate statement pairs across the whole corpus | k=20, ≥0.92 | MCP, HTTP, ingest/research reconcile set and prompts; no UI | **keep as an audit tool. Remove from `_RECONCILE_TOOLS` and the loop prompts.** `test_research.py:492` calls it with a `query` argument it does not accept; this only passes against the fake substrate |
| `find_entity_duplicates` (`server.py:4448`) | Names on different entities that collide after normalisation, or that are ≥0.9 similar in the name index | normalisation + hnsw | MCP, HTTP only. No UI, and no prompt names it | **keep, complete.** It is the only entity-dedupe detector; surface its results in the Names workspace as merge candidates (M) |
| Draft reviewer duplicate judgement | Statement duplicates and contradictions in a draft | LLM over the 5 nearest | Internal | **keep**. This is the layer that decides |
| Ingest classification (`skipped_duplicates`) | Duplicate candidates | LLM after the reconcile read | `ingest` | **keep** |
| Alias suggestions | **Not duplicate detection**: finds missing aliases | LLM + quote check | UI | keep (§3) |

**Which survives.** All of them. The vector tools supply candidates at different scopes and times, and the LLM layers (ingest and the reviewer) make the decision. That matches `project_vision.md:31`. The two real defects are that `find_duplicates` is miscast as a reconcile read, and that no UI shows entity duplicates.

---

## 8. Documentation generation

| Step | Where | Surfaces | Tests | Complete? |
|---|---|---|---|---|
| Request (`request_documentation`) | `server.py:2454`, `doc_runs.py:54-196` (snapshot, active-run cap, daemon thread) | MCP, HTTP `POST /api/documentation/runs`, both UIs (`ui/documentation-workspace.jsx`, shared) | `test_doc_runs`, `test_documentation_runs` | yes |
| Match an existing document (`match_existing`) | `docgen/loop.py:308-327,424-465`: one model turn picks a document from the registry listing | **MCP only.** The HTTP route forces `match_existing=False` (`http.py:1452`) | `test_docgen.py:377-427` | **partial.** Matching is non-deterministic and the UI cannot use it |
| Guidance and template selection | `docgen/loop.py:516-600`; profiles in `documentation_profiles.py`; guideline sets in `guidelines/`, `prompt_store.py` | MCP, HTTP, `/ui` profiles | `test_guideline_sets`, `test_documentation_profiles` | yes |
| Write + exposure/conformance review | Writer loop (`docgen/loop.py:770-806`); separate review conversation (`:860-960`); one rewrite, then refuse while keeping the findings | Internal | `test_docgen.py` (62) | yes. The review is a fresh context on the **same** provider and model, not an independent model |
| Registry and revisions | `docs_store.py` (`(set, type, slug)` key :837, immutable revisions); `list_generated_documents`, `get_generated_document`, `list_document_revisions`, `get_document_revision` | MCP, HTTP, UI | `test_document_revisions` | yes |
| `revise_document` | `server.py:2521`, `doc_runs.py:93-114` | MCP, HTTP, UI "Create revision" | `test_docgen.py:323`, `test_document_revisions.py:201` | **internally yes.** It works from the internal body, so edits a human made on the PR branch block later publication (`github_destination.py:284-302`, tested at `test_document_destinations.py:514`) |
| Manual edit (`document_edits.py`) | Same review gate on text the user supplies | HTTP, UI only (no MCP tool) | `test_documentation_workspace_http.py` | yes |
| Delivery (`deliver_document`) | `server.py:2685`, `docgen/destinations.py`, `docgen/github_destination.py`. **Real GitHub git-data API calls:** ref → blobs → trees → commits → refs (POST/PATCH) → reuse the open PR or `POST /pulls` (`:253-332`, `:595-640`). Branch `mycelium/docs/{slug}-{id}` | MCP, HTTP, UI "Create / update GitHub PR" | `test_document_destinations.py` (fake httpx) | yes, but only on an explicit call. PR title and body are fixed |
| GitHub App connections | `github_app.py`, `github_connect.py` (`/api/github/*`), `github_connections.py`, `github_credentials.py`, `ui/github-connection.jsx`, `ui/github-setup.html` | HTTP, both UIs (settings) | `test_github_connections.py` | yes |
| After merge | **Nothing.** No webhook, no polling, no merged or closed state. `delivery_status` is `published` / `changes_pending` / `unpublished` only (`docs_store.py:277-289`) | — | — | **not built** |

**Verdict:** keep, complete. What is missing is in `recommendations.md` (F1–F3).

---

## 9. Knowledge gaps

| Capability | Where | Surfaces | Verdict |
|---|---|---|---|
| Write | `report_knowledge_gap` (`server.py:5200`, reader role). Also filed by the docgen loop (`docgen/loop.py:225`) and automatically by the draft reviewer on every reject and every resolved contradiction (`draft_review_runs.py:478,490,544`). Ask and ingest are barred (`ask/substrate.py:47`) | MCP, HTTP, loops | keep |
| Read / close | `GET`/`PATCH /api/knowledge-gaps` (`http.py:893-943`): resolve, dismiss, reopen | `/ui` `gaps.jsx` **and** `/cockpit` `gaps.jsx` (duplicate screens) | **complete** |

**Does anything close a gap? No.** Nothing reads gaps programmatically. Research is not seeded from gaps, draft approval does not resolve related gaps, and gaps have no structured reference to a statement, draft or document, only free text. The docstring says "nothing is auto-pruned" (`server.py:5212`). Now that the reviewer files gaps automatically, they **accumulate forever** unless a person triages them.

**Gaps are also not backed up:** `knowledge_gaps` is missing from `backup._DATA_TABLES` (`backup.py:89-103`). This is a bug.

---

## 10. Settings, models, prompts

| Capability | Where | Surfaces | Verdict |
|---|---|---|---|
| Per-action model selection, Claude or OpenAI (`ai/claude.py`, `ai/openai.py`, `model_settings.py`) | Every loop goes through the `ai/` abstraction. `anthropic` is imported only in `ai/` and `model_credentials.py` | HTTP `/api/model-settings`, both UIs (AI settings) | **keep.** `project_vision.md:22-23` ("currently use Anthropic … GPT next-phase") is stale |
| Product settings (`product_settings.py`; loop limits, sources, destinations) | `mycelium-prompts.db` | HTTP `/api/product-settings`, `/ui` | keep |
| Editable prompts / AI instructions (`prompt_store.py`, `ai_prompts.py`; `save_`/`get_`/`list_`/`retire_`/`restore_prompt_text`, `list_prompt_text_versions`; `/api/ai-instructions*`, `/api/documentation/prompts*`) | Revisioned prompt texts | MCP, HTTP, `/ui` documentation profiles | keep |
| Documentation profiles (`list_`/`get_`/`save_`/`retire_documentation_profile`) | `documentation_profiles.py` | MCP, HTTP `/api/documentation/profiles*`, `/ui` | keep. The MCP tools `list_`/`get_`/`save_documentation_profile`, `list_documentation_models` and `get_draft_review_run` have no tool-level test references; profiles are tested through `/api/documentation/profiles` (`test_documentation_profiles.py`) |
| Model concurrency cap (`model_capacity.py`) | `server.py:270-310` | Internal | keep |

---

## 11. Browser UIs

| Capability | What | Verdict | Size |
|---|---|---|---|
| `/ui` (`src/mycelium/ui`, about 9.5k lines JSX+CSS) | Screens: landing, statement, entity, search (client-side substring scan over `/api/data`, `components.jsx:137-165`), graph, entities graph, browse, glossary, names, documentation, settings (users, tokens, invites, product, AI, GitHub), gaps, drafts (approve/reject), activity | **merge with `/cockpit` into one UI** | L |
| `/cockpit` (`src/mycelium/cockpit`, about 4k lines) | Find (semantic, survey, grep; server-side), Ask, Ingest, Research, names, documentation, AI settings, gaps, drafts (**no approve or reject**), statement, entity. Mounts 7 `/ui/*.jsx` files directly (`cockpit/index.html:72-81`). No doc mentions `/cockpit`. A stale comment at `http.py:2126` still lists "Coverage", which was replaced by gaps in `f06fc2b` | merge (above) | — |
| Overlap | Both have: names, documentation, gaps (two separate implementations), drafts (two implementations: 908 vs 571 lines), statement and entity detail, AI settings. Only in `/ui`: graphs, glossary, activity, user admin, approve/reject. Only in `/cockpit`: ask, ingest, research, server-side find | The `cleanup/frontend-build` session owns the build migration; the merge decision should be made before or with it | — |
| `/api/data` full dump | Five full-table selects plus a `when` tree query per conditional link (`read_models.py:99-102`). No embeddings, no pagination, no gzip (no `GZipMiddleware` in `http.py`), no ETag. Fetched before mount by both UIs and refetched after names and entity-link edits only. Other writes leave the copy stale until reload | **fix (stopgap), then replace** | S / L |
| Graph layout (`layout_baker.py`, `scripts/build_entity_layout.py`, `/api/entity-positions`) | **Live.** Bakes on startup if missing (`server.py:962-964`) and rebakes debounced in a subprocess after entity mutations (`server.py:2817,3775,4752,4776`). The UI fetches it (`graph.jsx:210`, `entities-graph.jsx:263`) | **keep, fix.** The baker runs a script from the repo's `scripts/` directory (`layout_baker.py:30`), which `docker/.dockerignore:13` excludes, so in Docker no layout is produced and **`entities-graph.jsx` waits forever** (no fallback, `:266,309-313`; `graph.jsx:204-207` has one). Move the script into the package and add the fallback | S |
| `scripts/render_entity_graph.py` + `matplotlib` dependency | The only importer of matplotlib (`render_entity_graph.py:28-29`); nothing calls it | **remove both** | S |
| UI tests | No JS tests run in CI. `tests/test_ask_client.mjs` exists, but nothing invokes it (`.github/workflows/lint-test.yml` runs `pytest` only; no Python test references it) | proposal | — |

**`/api/data` measured size.** Synthetic copies of the real schema, with 3 links per statement, 0.2 entities and 0.4 names per statement, and every link taking the `when`-tree lookup path (worst case for queries):

| Statements | Links | Payload | Server time (dump + `jsonable_encoder` + JSON) |
|---|---|---|---|
| 10k | 30k | 4.5 MB | ≈0.35 s |
| 50k | 150k | 22 MB | ≈1.7 s |
| 100k | 300k | 45 MB | ≈3.6 s |

That is about 450 bytes per statement including its share of links and names. Browser parse, index-build and render cost was **not measured**.

Production was about 1.6k statements per `docs/reports/2026-08-15` (≈1 MB), which is fine. Two effects hurt first *(inferred)*:
- **Around 10k statements:** full-row renders (browse, graphs) and the per-keystroke `searchAll` scan in `/ui`.
- **From about 20–50k statements:** every page load and refresh moves 10–20 MB or more uncompressed, with seconds of server time.

---

## 12. Identity and access

| Capability | Where | Verdict |
|---|---|---|
| Roles: asker < reader < drafter < writer < admin (`auth.py:46-62`) | Derived from the tool name prefix (`auth.required_role_for`), with `real_role` for live-only tools | keep. **`docs/USERS.md` documents only reader, writer and admin** |
| OIDC human login (`oidc.py`, `/auth/*`), JIT provisioning (`MYCELIUM_JIT_DOMAINS`, `MYCELIUM_JIT_DEFAULT_ROLE`) | | keep. JIT variables are undocumented |
| MCP OAuth 2.1 authorization server (`oauth_server.py`), CIMD (`cimd.py`, SSRF-hardened), DCR (deprecated, kept) | | keep |
| Tokens, service accounts, invites (`auth_store.py`, `/api/me/tokens*`, `/api/admin/*`, `/auth/invite/*`); `mycelium users` CLI; `deploy/myc` | `/ui` settings | keep |
| `/connect` setup page (`connect_page.py`); `/` redirects to it | Linked from `/ui` | keep |

---

## 13. Observability and operations

| Capability | Where | Surfaces | Verdict |
|---|---|---|---|
| Audit history (`history.history_events` in `mycelium-history.db`; `/api/history`) | `http.py:665` | `/ui` Activity | keep |
| **Ops ledger** (`ops_ledger.py`, 452 lines; `/api/operations`) | Records **every** tool call by default (`MYCELIUM_OPS_LEDGER` defaults to `1`, `ops_ledger.py:158`; wrapper `server.py:500-529`) into `mycelium-ops.db`. Correlation columns are unpopulated (`ops_ledger.py:24-26`) | HTTP only. **No UI and no internal reader** | **remove, or give it a consumer** (owner decision). It is write-mostly telemetry on the hot path |
| Tracing (`tracing.py`; `/api/traces*`, `/api/tracing*`) | Loop traces and HTML profiles (pyinstrument, optional import, `tracing.py:258`) | Admin HTTP only; routes untested | keep |
| `MYCELIUM_PROFILE` cProfile wrapper (`server.py:84-130`) | Wraps every tool when the env var is set; undocumented; untested | Env only | **remove** (it duplicates tracing) |
| Backup (`backup.py`, `documentation_archive.py`; `mycelium export` / `mycelium import`) | Full archive including settings and documents | CLI | keep, **fix: add `knowledge_gaps`** |
| `mycelium-init` (`init_kb.py`) | Scaffolds a knowledge base directory with `.mcp.json` | CLI | keep, **fix**: the README it writes promises "regenerable from `ingest/` JSON payloads" and "re-run an ingest script"; neither exists (`init_kb.py:28,51-66,124`) |
| Docker images (`docker/`), `deploy/` scripts | | | keep. Docker lacks `git` (research) and `scripts/` (layout); see §5 and §11 |

---

## 14. Scripts, bench, reports

| Item | State | Verdict |
|---|---|---|
| `scripts/audit_phrasing.py`, `recover_stranded_vectors.py`, `seed_guideline_sets.py` (tested and documented), `backfill_derived_mentions.py` (tested) | Run (`--help` passes, imports resolve) | keep |
| `scripts/build_entity_layout.py` | Live through the baker | keep, move into the package |
| `scripts/embed_bench.py` | Needs a live Ollama; embedding work | keep (embeddings are out of scope for removal) |
| `scripts/audit_link_type_aliases.py` | Audits `auto` aliases that nothing writes any more | remove, or keep with the alias decision (§4) |
| `scripts/render_entity_graph.py` | Not called; only matplotlib user | **remove** |
| `bench/` (`run.py` 748 lines, README 211) | **Broken.** Calls `server.upsert_behavior`, `search_behaviors`, `server._conn` and a `behaviors` table (`bench/run.py:85,110,127-133`), none of which exist. Last touched 2026-07-09 | **remove** |
| `docs/reports/2026-08-15-kind-shape-accuracy.md` | Measures `connect/shapes.py`; both that file and the generator were deleted in `8064aab`. It is exactly the kind of evaluation `project_vision.md` retired | **remove** |

---

## 15. Repository skills (`.claude/skills/`, agent-facing)

| Skill | Issue | Verdict |
|---|---|---|
| `mycelium-authoring`, `mycelium-guide-authoring` | Current | keep |
| `mycelium-draft-review` | Says "there is no approve/reject MCP tool … the operator decides … in the Mycelium UI". That is now false: the `record_draft_review`/`apply_reviewed_draft` tools exist, and so does `review-and-apply`. It also conflicts with the no-human direction | **fix** (rewrite around the internal reviewer), or remove |
| `mycelium-draft` | Writes proposed mutations to local `context/mycelium-drafts/*.md` instead of a substrate draft. That is a parallel draft mechanism that bypasses the reviewer | **merge into substrate drafts** (have it call `upsert_statements` with a drafter token). Owner decision |
| `kb-authoring` | A local agent writes Diátaxis docs from the substrate, which is what server-side docgen does (and it ships the same guideline set, `src/mycelium/guidelines/kb-authoring`) | **merge into `request_documentation`**. Owner decision |
| `guidelines/kb-authoring/guidance.md:54` (served to the docgen loop) | Shows `get_entity(name=…)  # includes all linked statements`. The tool takes `id` and returns no statements | **fix** |

---

## 16. Documentation accuracy

| File | Status |
|---|---|
| `README.md`, `SETUP.md` | Accurate. All 11 read-path tools named exist; no leftovers from `8064aab` |
| `project_vision.md` | Stale. `:22-23` (GPT is "next-phase", but it is shipped); `:70-72` (DRA-393 "unmerged", but it merged on 2026-09-07) |
| `docs/mycelium.md` (807 lines) | **Badly stale.** `:189` says "twenty-four tools" (there are 87; 64 are not mentioned). `:51-55` lists 3 kinds, but 9 are seeded (the same stale text is in the `upsert_statement` docstring, `server.py:2864-2869`). `:770-780` describes 3 test files and `store.py`. `:683-689` gives the wrong `/api/data` shape. `:679-762` omits about 70 routes and `/cockpit`. `:797-807` "non-goals" is contradicted by `find_duplicates`, `find_entity_duplicates` and export |
| `docs/DEPLOYMENT.md:199,299-305`, `docs/USERS.md:104,169-180`, `docs/AUTH0.md:183` | Name `main.db` and `history.db`. The real files are `mycelium.db`, `mycelium-history.db`, `mycelium-auth.db` and `mycelium-prompts.db` (`server.py:942-960`); users live in `mycelium-auth.db`. **The documented lockout-recovery SQL and backup command target a file that does not exist.** The backup command would also miss the auth, prompts and history databases; `mycelium export` exists for this. `auth_store.py:7` has the same wrong comment |
| `docs/USERS.md:21-25,135-137` | Missing the `asker` and `drafter` roles |
| `docs/ENTITY_STATEMENT_MIGRATION.md` | Describes shipped work; now upgrade history. Keep |
| `docs/MENTION_CORRECTION_DESIGN.md` | Historical design, labelled as such; its `asserted_mentions` idea was not built. Could be archived |
| `AI_MODELS`, `AI_PROMPTS`, `ALIAS_SUGGESTIONS`, `ASK`, `CONNECTIONS`, `DOCUMENTATION_MODELS`, `DRAFT_REVIEW`, `GITHUB_APP`, `GUIDELINE_SETS`, `MENTIONS`, `NAMES_AND_ALIASES`, `STYLE` | Spot-checked; no false claims found |
| **Undocumented** | `/cockpit`; CLI `export`/`import`/`users`; `/api/history`, `/api/operations`, `/api/traces*`, `/api/admin/*`, `/api/me/tokens*`; about 33 tools (draft editing, vocabulary management, research, documentation profiles, gaps); `docker/`; `scripts/`; and the env vars in §17 |

---

## 17. Configuration

**Documented but unread.** No documented `MYCELIUM_*` variable is entirely unread. The other names that appear only in docs are placeholders (`MYCELIUM_HOST` in GITHUB_APP.md, `COMPANY_GITHUB_TOKEN` in AI_MODELS.md) or build and deploy variables (`UV_*`, `SSH_*`, `MALLOC_ARENA_MAX`).

**Effectively dead: read only by the one-time legacy import.** `prompt_store.py:143-171` returns early once the `models-and-review-controls` migration row exists, so on any instance initialised or upgraded since then these variables do nothing:
- `MYCELIUM_{ASK,INGEST,DOCGEN,RESEARCH,DRAFT_REVIEW}_PROVIDER`
- `…_MODEL`, `…_OPENAI_MODEL`, `MYCELIUM_DRAFT_REVIEW_CLAUDE_MODEL` (`model_settings.legacy_selection`, `model_settings.py:117-135`)
- `MYCELIUM_DRAFT_REVIEW_MODE`, `MYCELIUM_DRAFT_REVIEW_USER_ID`, `MYCELIUM_REVIEWED_APPLY` (`prompt_store.py:166-171`)

Similarly, `MYCELIUM_SOURCES` is a legacy import path only (`research/sources.py:1-7,89`). `docs/DRAFT_REVIEW.md` and `docs/AI_MODELS.md` still present these as configuration in variable tables, with a note that they are imported once.

**Read but undocumented** (`src/`):
- Ops ledger: `MYCELIUM_OPS_LEDGER`, `MYCELIUM_OPS_CAPTURE`, `MYCELIUM_OPS_RETENTION_DAYS`, `MYCELIUM_OPS_RETENTION_ROWS`
- Profiling and tracing: `MYCELIUM_PROFILE`, `MYCELIUM_PROFILE_DIR`, `MYCELIUM_TRACE_ENABLED`, `MYCELIUM_TRACE_DIR`
- Per-loop tracing and pricing: `MYCELIUM_{ASK,INGEST,DOCGEN,RESEARCH}_{TRACE_DIR,TRACE_LOG,INPUT_PER_MTOK,OUTPUT_PER_MTOK}`
- Doctrine paths: `MYCELIUM_{INGEST,DOCGEN,RESEARCH}_DOCTRINE_PATH`
- Run limits: `MYCELIUM_DOCGEN_MAX_ACTIVE`, `MYCELIUM_RESEARCH_MAX_ACTIVE`, `MYCELIUM_RESEARCH_CLONE_TIMEOUT_S`, `MYCELIUM_MODEL_LOOP_MAX_CONCURRENT`
- Feature switches: `MYCELIUM_DISABLE_MCP_HTTP`, `MYCELIUM_DISABLE_MENTION_WORKER`
- Provisioning: `MYCELIUM_JIT_DOMAINS`, `MYCELIUM_JIT_DEFAULT_ROLE`
- `MYCELIUM_INGEST_MODEL` (legacy fallback)
- Embeddings: `EMBED_DIM`, `EMBED_TIMEOUT_S`

**Dead schema (not configuration):** `link_type_alias_embed_queue` and `link_type_aliases.embedding` (§4).

---

## 18. Branches and worktrees (nothing deleted)

**Local `master` is 20 commits behind `origin/master`.** Merge status below is against `origin/master`.

### Local branches

| Branch | Status vs `origin/master` | Last commit |
|---|---|---|
| `cleanup/feature-audit`, `cleanup/mcp-surface`, `t3/clean-up-product-ui` | equal (active cleanup sessions) | 2026-10-22 |
| `cleanup/frontend-build`, `cleanup/quality-gates` | +1 each (active sessions) | 2026-10-22 |
| `implement-research-loop` | +3, 484 behind. **Superseded**: the same work landed as `7803448` (#2) | 2026-07-08 |
| `improve-ask-for-intercom` | +2, 484 behind. **Superseded** by `d5fcda6` (#3) | 2026-07-08 |
| `linear/dra-346-document-delivery-destination` | +1, 241 behind. **Superseded** by `9796992` | 2026-08-17 |
| `integration/docgen-local-test` | +1 (a merge-only integration branch), 233 behind. Superseded | 2026-08-17 |
| `master` | merged; stale, 20 behind | 2026-09-08 |
| Fully merged, safe to prune by merge status: `codex/docgen-review-body`, `codex/github-direct-install`, `codex/github-repository-connection`, `fix/tech-7442-asgi-auth-middleware`, `linear/dra-387…`, `linear/dra-388…`, `linear/dra-389…`, `linear/dra-412…`, `linear/dra-416…`, `refactor/smaller-cleanups`, `t3/fix-auth-middleware-disconnect`, `t3/investigate-sentry-error`, `t3code/editable-prompt-config`, `t3code/editable-prompt-config-1`, `t3code/fix-same-run-document-guard`, `t3code/guided-documentation-generation`, `t3code/improve-ask-workflow`, `t3code/investigate-intercom-response-format`, `t3code/investigate-stateless-mcp-support`, `t3code/mcp-authz-followups`, `t3code/oauth-cimd`, `t3code/test-intercom-json-optimization`, `worktree-agent-a1f2f818…`, `worktree-agent-a292fe86…`, `worktree-agent-a3a10b5c…`, `worktree-agent-a79e4d55…`, `worktree-agent-aa6847d0…` | merged | 2026-07-08 – 2026-10-06 |

### Remote branches

`origin` has 67 branches besides `master`. 64 are merged. The three that are not: `implement-research-loop` and `improve-ask-for-intercom` (superseded, as above) and `refactor/tier1-singleton-accessors` (0 patch-unique commits, so its content is already in master).

### Worktrees

| Worktree | Branch / HEAD | Merged? | Dirty files |
|---|---|---|---|
| `~/projects/mycelium-base` (main checkout) | `master` (stale) | — | **22**: an uncommitted, older copy of the GitHub App work (`github_app.py` etc. untracked) that has since landed as PR #102. Inspect before any cleanup |
| `/private/tmp/vm2`, `/private/tmp/vm3` | detached | merged | directory **missing**, prunable |
| `.t3/worktrees/…/cleanup-*` (4) | active cleanup sessions | — | frontend-build 2, quality-gates 4 (in use) |
| `.t3/worktrees/…/t3-64774075` | `t3/clean-up-product-ui` | equal | 0 (a session is active on it) |
| `.t3/worktrees/…/t3-8da267e6`, `t3-ee5920d4`, `t3code-123f6e31`, `t3code-38a6895a`, `t3code-682a85a2`, `t3code-6afab21c`, `t3code-80ff6808`, `t3code-86f2ba2e`, `t3code-880c6d0b` (detached), `t3code-930c2abe` | merged branches | merged | 0 |
| `~/projects/mycelium-base-ask-debug` | detached at `d40b369` | merged | 0 |
| `~/projects/mycelium-base-worktrees/{docgen-fix, docgen-review-body, dra-387, dra-388, dra-389, dra-416, github-direct-install, github-repository-connection}` | merged branches | merged | 0 |
| `~/projects/mycelium-base-worktrees/{dra-346, implement-research-loop, improve-ask-for-intercom}` | superseded branches | no (superseded) | 0 |
| `~/projects/mycelium-base-worktrees/integration` | `integration/docgen-local-test` | no (superseded) | **1** (`guidelines/kb-authoring/guidance.md`) |
