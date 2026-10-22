# Recommendations

These recommendations are ranked by value within each group. Every item is written so it can be handed to a session as a brief. The evidence for each one is in `feature-inventory.md` (section references are given as §N).

Size key: **S** is under a day, **M** is 1–3 days, **L** is more than 3 days.

Items that need an owner decision before work starts are marked **[decision]**.

## What changed from the questions as posed

- **Entity↔statement links (DRA-393) are already removed.** The removal was merged on 2026-09-07 (`d40b369`, PR #63). The data migration was decided at the same time: users rescue their links by hand, and the server refuses to upgrade while any remain. That procedure is in `docs/ENTITY_STATEMENT_MIGRATION.md`. The only work left is correcting one sentence in `project_vision.md`.
- **GPT support has shipped.** All model loops go through `ai/` and can use Claude or OpenAI per action, but the vision still calls GPT support "next-phase".
- **Only one read tool is a real duplicate:** `survey_statements`. The other read tools each have a distinct contract and a real caller.
- **No duplicate-detection mechanism needs to go.** Two of them are wired wrongly, and both are covered under Fix below.

---

## Remove

| # | Item | Value | Size |
|---|---|---|---|
| R1 | `survey_statements` → fold into `search_statements` | High | M |
| R2 | `bench/` (broken), `docs/reports/2026-08-15-kind-shape-accuracy.md` (stale), `scripts/render_entity_graph.py` + the `matplotlib` dependency | Medium | S |
| R3 | `MYCELIUM_PROFILE` cProfile wrapper | Low–medium | S |
| R4 | Ops ledger, unless a consumer is named **[decision]** | Medium | S–M |
| R5 | Dead link-type-alias schema, and possibly the whole alias vocabulary **[decision]** | Low–medium | S / M |
| R6 | Legacy env-var import paths and the docs presenting them as configuration | Low | S |

**R1. Merge `survey_statements` into `search_statements(decompose: bool = False)`.**
- **Why.** Survey has its own code path (`server.py:2133`, calling `_idx().search` directly) with the same output shape as search. It lacks search's alias boost and its mention, kind and min_score filters, and its scores are on a different scale. The only thing it adds is query decomposition (`survey.py:152`) plus ranking by hit count. The cockpit throws that ranking away by re-sorting on score (`cockpit/api.js:150`).
- **How.**
  - When `decompose=True`, run each part produced by `survey.decompose` through `_search_statement_candidates`, then union and rank the results with `survey.rank_statements`.
  - Keep `survey.py`, which is pure logic.
  - Switch the recon steps in `ask/loop.py:488` and `docgen/loop.py:673` to the new mode.
  - Update the tool frozensets in `ask/loop.py` and `ingest/loop.py:71-76`.
  - Update the prompt and doctrine files that name survey (about 7), `cockpit/api.js:144-150`, and the README.
- **Tests.** About 5 tool-level tests in `test_survey.py`. Survey references in `test_ask.py`, `test_ask_streaming.py` and `test_docgen.py` are mostly renames. `test_ask.py:824` loses one entry from its pinned set.
- **Coordination.** The `cleanup/mcp-surface` session is changing the tool surface, so coordinate there. This is a breaking change for external MCP clients that call `survey_statements`.
- **Minimum if deferred.** Fix the cockpit re-sort (S). Today it makes "survey" mode a plain cosine search.

**R2. Delete dead artefacts.**
- `bench/`: about 960 lines. It calls `server.upsert_behavior`, `search_behaviors`, `server._conn` and a `behaviors` table, none of which exist (`bench/run.py:85,110,127-133`).
- `docs/reports/2026-08-15-kind-shape-accuracy.md`: it measures `connect/shapes.py`, which was deleted in `8064aab`.
- `scripts/render_entity_graph.py`: it is the only importer of matplotlib (`:28-29`) and nothing calls it.
- `matplotlib>=3.10.9` in `pyproject.toml` (25 MB installed). Also regenerate `uv.lock`.
- Do **not** touch `numpy`; `vector.py` and the layout baker use it.
- The `cleanup/quality-gates` session just brought `bench` under ruff (`57edcb8`), so tell them first.

**R3. Remove the `MYCELIUM_PROFILE` wrapper** (`server.py:84-130` and its call at about `:330`). It is undocumented and untested, and it duplicates `tracing.py`, which already produces pyinstrument profiles. About 75 lines.

**R4. Ops ledger [decision].**
- **What it costs.** `ops_ledger.py` (452 lines) writes a row to `mycelium-ops.db` for every tool call by default (`MYCELIUM_OPS_LEDGER` defaults to `1`). The wrapper is at `server.py:500-529`.
- **Who reads it.** Nobody. `/api/operations` has no UI or internal caller, the correlation columns are never filled (`ops_ledger.py:24-26`), and all its env vars are undocumented.
- **Options.**
  - (a) Remove the module, the route, the wrapper seam and `test_ops_ledger.py`. Size M because of the `tool()` wrapper edit.
  - (b) Default it off and document it. Size S.
  - (c) Name a consumer. One candidate: the merged UI's Activity screen.
- **Recommendation: (a)**, unless the owner uses it for production debugging. I could not determine whether they do.

**R5. Link-type aliases [decision].**
- **Remove regardless:** `link_type_alias_embed_queue`, the `link_type_aliases.embedding` column, and the enqueue code in `migrations.py:658,697,742`. This needs a new migration that drops them (S). `8064aab` already states that nothing reads them.
- **The decision:** the alias vocabulary itself. That means `list_`, `upsert_` and `delete_link_type_alias`, `store/link_type_aliases.py`, the `backup.py:102` table entry, and `scripts/audit_link_type_aliases.py`. It has **no reader** now that `connect/` is gone, even though `8064aab` deliberately kept it. Either give it a consumer (feed it to the ingest and reviewer prompts as synonym hints) or remove it (M; archive compatibility must keep importing the table).

**R6. Retire the legacy env-var import paths.** These variables only take effect during the one-time `models-and-review-controls` import (`prompt_store.py:143-171`, `model_settings.legacy_selection`):
- `MYCELIUM_{ASK,INGEST,DOCGEN,RESEARCH,DRAFT_REVIEW}_{PROVIDER,MODEL,OPENAI_MODEL}`
- `MYCELIUM_DRAFT_REVIEW_{MODE,USER_ID,CLAUDE_MODEL}`
- `MYCELIUM_REVIEWED_APPLY`
- `MYCELIUM_SOURCES`

**Docs-only now (S):** move them out of the configuration tables in `docs/AI_MODELS.md` and `docs/DRAFT_REVIEW.md` into an "upgrading from pre-settings versions" note. The code removal can wait until no pre-migration databases remain; I could not determine whether any do.

**Not recommended for removal:** `retrieve_context`, `discover_facts`, `find_duplicates`, `find_entity_duplicates`, alias suggestions, the research loop, the layout baker, `cimd.py`, `tracing.py`, `documentation_archive.py`, `backup.py`, `connect_page.py`, `mention_candidates.py`, `statement_connections.py`. Reasons are in the inventory. The Ollama/hnswlib embedding path is out of scope.

---

## Finish

| # | Item | Value | Size |
|---|---|---|---|
| F1 | No-human draft path: auto-submit, separate alias ops, recover stuck drafts | **Highest** | M |
| F2 | Documentation after merge: PR-state tracking and reconciling with edits made on GitHub | High | M |
| F3 | A deterministic "intended document" identity for repeat requests | High | S–M |
| F4 | Close the knowledge-gap loop | Medium–high | M |
| F5 | One browser UI **[decision]** | High (long-term) | L |
| F6 | Replace the `/api/data` full dump | Medium now, high at scale | L (S stopgap) |
| F7 | Reviewer escalation: ask a person instead of rejecting | Medium | M |
| F8 | Surface `find_entity_duplicates` in the Names workspace | Medium | M |
| F9 | Collapse repo skills onto server features **[decision]** | Medium | S–M |

**F1. Make submission-to-applied work without a person.** The core already works: `test_internal_draft_review.py:227` takes a drafter write through `submit_draft` to `approved`. Three things break it in practice.
1. **Ingest and research drafts are never submitted.**
   - Cause: `InProcessDraftEmitter.create` makes an open draft with `created_by=None` (`ingest/draft.py:87-95`), and research uses the same emitter (`research_runs.py:135`).
   - Fix: when the review mode is not `off`, submit at the end of `ingest` and at the end of a research run, through the same path as `submit_draft` (`server.py:5395`), so `draft_review_runs.on_submitted` fires.
   - Decide whether the HTTP/UI ingest path should also auto-submit. I recommend yes, behind the same mode check.
2. **One alias suggestion makes the whole draft advisory** (`draft_review_runs.py:433-438`).
   - Fix: at ingest time, emit `alias_suggestion` ops into a separate draft linked to the main one, so the knowledge part can be applied. Alternatively, let the reviewer apply everything except the alias ops.
   - Ingest emits these ops at `ingest/schema.py:31` and `ingest/loop.py:470`.
3. **Stuck drafts.**
   - These paths fail without `_follow_up`, so the draft stays `submitted` forever:
     - the reviewer cannot be resolved (`draft_review_runs.py:144-152`, `:312-316`);
     - a provider error on the second attempt (`:518`);
     - runs interrupted by a restart.
   - Fix: add a periodic sweep, inside the existing worker, that re-queues submitted drafts whose latest run failed or is missing. Cap it at N attempts with backoff.
   - Enabling review should also offer a one-time backlog sweep. Today it does not sweep (`docs/DRAFT_REVIEW.md`).
- **Tests:** extend `test_internal_draft_review.py`, and add an ingest → auto-submit → approved test with a stub model.

**F2. Close the loop after a document PR merges.**
- **Today.**
  - Delivery really creates blobs, trees, commits and refs, and reuses or opens PRs (`docgen/github_destination.py:253-332`, `:595-640`; tested with fake httpx in `test_document_destinations.py`).
  - Nothing tracks merge or close. `delivery_status` only knows `published` / `changes_pending` / `unpublished` (`docs_store.py:277-289`). There is no webhook (`docs/GITHUB_APP.md`: "Webhook: inactive").
- **Change.**
  1. Record the PR number and state on delivery.
  2. Refresh the state when the document is read, using the existing installation token, or add a GitHub App `pull_request` webhook. **Recommendation:** refresh on read, because it needs no public webhook endpoint.
  3. Surface `merged` / `closed` in the documentation workspace.
- **Also fix:** `revise_document` writes from the internal body (`doc_runs.py:105-113`), so once a reviewer commits to the PR branch, later revisions are refused at delivery ("document changed after generation", `github_destination.py:284-302`).
  - Fix: before revising, read the current file from the PR branch, or from the base branch after a merge, using the existing `github_destination.read` (`:170-197`). Only the MCP `match_existing` path does that today (`doc_runs.py:519-546`).
- **Optional (S):** update the PR title and body on re-delivery. They are fixed today.

**F3. A deterministic document identity for repeat requests.**
- **Today.** "Repeated requests should update the intended document" depends on one model turn choosing from a title listing (`docgen/loop.py:424-465`). That only happens over MCP, because the HTTP/UI route forces `match_existing=False` (`http.py:1452`).
- **Change.** Give requests an explicit identity, such as the existing `(guideline_set, document_type, slug)` key (`docs_store.py:837`) or an anchor entity or statement id.
  - When the identity matches, route the request to `revise_document`.
  - Keep model matching only as a suggestion that the UI shows.
- **[decision]** Which identity to use. I recommend an anchor entity id plus the document type, because a slug drifts with the title.

**F4. Close the knowledge-gap loop.**
- **Today.** Gaps are written by agents, the docgen loop and the reviewer. The reviewer files one automatically on every reject and every resolved contradiction (`draft_review_runs.py:478,490,544`). Only people close them (`PATCH /api/knowledge-gaps`), so they accumulate forever.
- **Change.**
  1. Store structured references on a gap: draft, statement or document ids (schema plus `store/gaps.py`).
  2. When a draft is applied, resolve the gaps that draft's earlier run filed.
  3. Offer "start research from this gap" (`start_research(topic=gap.text)`).
  4. Optionally, auto-dismiss reviewer-filed gaps after N days with no activity.
- **Do first (S, a bug):** add `knowledge_gaps` to `backup._DATA_TABLES` (`backup.py:89-103`). Gaps are lost on export/import today.

**F5. One browser UI [decision].**
- **Today.** `/ui` (about 9.5k lines) and `/cockpit` (about 4k lines) duplicate gaps, drafts, statement and entity detail, and settings. `/cockpit` already mounts 7 `/ui` components.
  - Only `/ui` can approve or reject drafts, administer users, show graphs and the glossary, and show activity.
  - Only `/cockpit` has Ask, Ingest, Research and server-side Find.
  - No doc mentions `/cockpit`.
- **Recommendation.** Keep the cockpit shell (it is AI-native: ask, ingest, find), port `/ui`'s unique screens into it, and delete the duplicated gaps and drafts implementations.
- **Sequencing.** The `cleanup/frontend-build` session owns the build migration. Decide the merge before or alongside it so the same screens are not ported twice.

**F6. Replace `/api/data`.**
- **Measured** on synthetic copies of the real schema, with 3 links per statement (§11):

  | Statements | Payload | Server time |
  |---|---|---|
  | 10k | 4.5 MB | 0.35 s |
  | 50k | 22 MB | 1.7 s |
  | 100k | 45 MB | 3.6 s |

  - Responses are uncompressed and uncached, and are refetched on every load.
  - Browser cost was not measured.
  - Production was about 1.6k statements per the August report, so this is not urgent.
- **Where it breaks first (inferred):**
  - around 10k statements, in `/ui`'s per-keystroke client-side `searchAll` (`components.jsx:137-165`) and in full-row renders;
  - around 20–50k statements, in page loads.
- **Stopgap (S):**
  - add `GZipMiddleware`;
  - add an ETag on a substrate change counter (the history DB or `max(updated_at)`);
  - load `when` trees in one query instead of one per conditional link (`read_models.py:99-102`).
- **Replacement (L, best folded into F5):** each screen moves to per-screen reads:
  - search uses `/search-statements`, `/grep-statements` and `/search-entities`, as cockpit Find already does;
  - detail views use `get_statements` and `get_entity`;
  - browse uses `list_entities` / `list_statements` (bounded);
  - drafts fetch only the records they touch;
  - graphs use a neighbourhood query;
  - Activity gets server-resolved labels;
  - the landing page gets a counts endpoint.

**F7. Let the reviewer escalate instead of rejecting.** `needs_context` is turned into a failure and then a rejection (`draft_review_runs.py:447`). The vision asks the reviewer to "surface the specific question requiring human input".
- **Change.** Allow a `needs_human` outcome that stores the question on the draft and files a structured gap (see F4). Show it in the drafts screen.
- **Do not** give the reviewer write tools beyond the existing corrections.

**F8. Entity-duplicate candidates in the Names workspace.** `find_entity_duplicates` (`server.py:4448`) is the only detector of existing entity duplicates, and no UI shows it. Add a "possible duplicates" panel that feeds the existing merge preview (`names_workspace.py`).

**F9. Repository skills [decision].**
- `mycelium-draft` writes proposals to local markdown files instead of substrate drafts, which bypasses the reviewer.
- `kb-authoring` duplicates server-side docgen and ships the same guideline set.
- `mycelium-draft-review` describes a human-only approval world: it says "no approve/reject MCP tool", which is false.
- **Recommendation:**
  - point `mycelium-draft` at `upsert_statements` with a drafter token;
  - replace `kb-authoring` with a thin wrapper around `request_documentation`;
  - rewrite `mycelium-draft-review` around `request_draft_review` and the reviewer's output.

---

## Fix

| # | Item | Value | Size |
|---|---|---|---|
| X1 | Wrong database file names in operations docs (lockout recovery and backup run against a file that does not exist) | **High** (operational risk) | S |
| X2 | Knowledge gaps missing from backups | High | S |
| X3 | Entities graph hangs when no layout file exists (Docker) | Medium–high | S |
| X4 | `find_duplicates` is miscast as an ingest/research reconcile read | Medium | S |
| X5 | Stale project docs: vision, `docs/mycelium.md`, roles, `init_kb` README text | Medium | M |
| X6 | Research in Docker (no git), refused GitHub App sources, stale cockpit hint | Medium | S |
| X7 | Unbounded `limit`/`k` on `search_statements`, `survey_statements`, `list_*` | Medium | S |
| X8 | Loop tool surface: drop un-prompted tools from loop offers | Low–medium | S |
| X9 | Small correctness and coverage items | Low | S |

**X1. Correct the database file names** in `docs/DEPLOYMENT.md:199,299-305`, `docs/USERS.md:104,169-180`, `docs/AUTH0.md:183`, and the comment at `auth_store.py:7`.
- **Wrong:** they name `main.db` and `history.db`.
- **Right:** the files are `mycelium.db`, `mycelium-history.db`, `mycelium-auth.db` (where users live) and `mycelium-prompts.db` (`server.py:942-960`).
- **Consequences of the wrong names:**
  - the documented `sqlite3 … main.db "SELECT … FROM users"` lockout recovery would fail;
  - the documented `.backup` would miss the auth, prompts and history databases.
- **Fix:** recommend `mycelium export` as the backup command.

**X2. Add `knowledge_gaps` to `backup._DATA_TABLES`** (`backup.py:89-103`). Add a round-trip assertion to `test_backup.py`.

**X3. Entities graph without positions.**
- **Problem.** `ui/entities-graph.jsx:263-313` waits forever when `/api/entity-positions` returns 404, whereas `graph.jsx:204-207` falls back. The 404 happens in the Docker image: `docker/.dockerignore:13` excludes `scripts/`, and `layout_baker.py:30` runs `scripts/build_entity_layout.py` from the repo, so the baker silently does nothing.
- **Fix:**
  1. Add the same fallback to `entities-graph.jsx`.
  2. Move `build_entity_layout.py` into the package, for example `mycelium/layout.py`, and invoke it with `python -m`.
- This finding comes from reading the code; I did not reproduce it in a browser.

**X4. Remove `find_duplicates` from `_RECONCILE_TOOLS`** (`ingest/loop.py:72`) and from the ingest and research prompts that name it as a reconcile read (`ingest/prompts.py:39,50,228`, `research/prompts.py:66,89,215`).
- **Why.** It audits the whole corpus and takes no candidate text, so calling it satisfies the reconcile gate without checking the candidates. Keep it as an MCP audit tool.
- **Also:** fix `test_research.py:492`, which calls it with a nonexistent `query` argument.

**X5. Bring the project docs up to date.**
- `project_vision.md`:
  - `:22-23`: GPT support has shipped.
  - `:70-72`: DRA-393 is merged; point to `docs/ENTITY_STATEMENT_MIGRATION.md`.
  - The "Review and documentation" paragraph should state what now exists: automatic review-and-apply, real PR delivery, and revisions.
- `docs/mycelium.md`:
  - It claims 24 tools (there are 87), lists 3 kinds (9 are seeded), and has stale tests, transport and `/api/data` sections and stale non-goals.
  - **Recommendation:** cut it down to the data-model and invariants sections and defer signatures to `/docs`. README already says the MCP schema and `/docs` are authoritative.
- The `upsert_statement` docstring's kind list (`server.py:2864-2869`) has the same stale text.
- `docs/USERS.md`: add the `asker` and `drafter` roles (`auth.py:46-62`).
- `init_kb.py:28,51-66,124`: remove the "regenerable from `ingest/` JSON payloads" and "re-run an ingest script" claims, and the `ingest/` directory if nothing uses it.
- `http.py:2126`: the comment still says "Coverage".
- Document `/cockpit` (or remove it via F5), the `export`/`import`/`users` CLI, and the undocumented env vars (inventory §17).

**X6. Research reachability.**
- Add `git` to the runtime stage of `docker/Dockerfile`, or document that a wrapping image must provide it. I inferred that clones fail without it; I did not run it.
- Accept GitHub App connections as research sources, as docgen does (`research/sources.py:66-69`).
- Replace the stale "set MYCELIUM_SOURCES" hint (`cockpit/research.jsx:102`) with a pointer to AI settings.

**X7. Bound result sizes.** Add an upper bound (`le=`), for example 100, to:
- `search_statements.limit`
- `survey_statements.k` (if kept)
- `list_statements.limit` and `list_entities.limit`

Hydrated output is unbounded today, whereas `retrieve_context` and `find_statement_connections` are capped. Coordinate with `cleanup/mcp-surface`.

**X8. Trim what loops are offered.** Ingest, docgen and research are offered `retrieve_context`, `find_statement_connections` and `get_mention_candidates` (and ask is offered the last one), but no prompt names them. Their schemas cost tokens every turn (inferred).
- Either add per-loop allowlists, or add `get_mention_candidates` to the shared denylist (`ask/substrate.py:45`), since it serves curation, not domain evidence.
- Update the pinned set at `tests/test_ask.py:824`.

**X9. Small items.**
- Fold `GET /api/mention-candidates` (`http.py:946`) into the generated tool route.
- `guidelines/kb-authoring/guidance.md:54`: it shows `get_entity(name=…)  # includes all linked statements`, but the tool takes `id` and returns no statements, and this text is served to the docgen loop.
- Add tool-level tests for `upsert_`/`delete_statement_kind` and `upsert_`/`delete_entity_link_type`.
- `tests/test_ask_client.mjs` is not run by CI. Either wire it into CI or remove it.
- **Not determined:** whether HTTP `POST /api/drafts/{id}/submit` (`http.py:1775`) should check that the caller created the draft.

---

## Owner decisions

1. **spaCy phrasing gate.** **Recommendation: keep.**
   - **Measured cost:**
     - 3.4 ms per statement write;
     - 0.64 s one-time model load;
     - about 50 MB RSS;
     - about 45 MB of packages plus about 17 transitive dependencies;
     - a wheel pinned by URL.
   - **Why keep.** It is a deterministic linter using a POS tagger, not judgement or generation. Replacing it with an API call would add seconds and cost to every write, and the automatic reviewer and replay now depend on its findings (`f9346aa`).
   - **If the "no local models" rule is meant to cover it:** reduce it to the regex-only checks. That loses the compound-clause, modal and copula/property checks (M).
2. **Ops ledger** (R4): remove, default it off, or name a consumer.
3. **Link-type alias vocabulary** (R5): wire it up or remove it.
4. **One UI** (F5): which shell survives. Decide before the frontend migration ports anything.
5. **Document identity** (F3): an anchor entity plus type, or the slug.
6. **Repository skills** (F9): fold them onto server features.
7. **Branch and worktree pruning** (inventory §18):
   - Every unmerged local branch is superseded by an equivalent commit on master.
   - The main checkout has 22 uncommitted files: an older copy of GitHub App work that has since merged. Inspect it before any cleanup.
   - Local `master` is 20 commits behind `origin/master`.
