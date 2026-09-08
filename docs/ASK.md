# Ask retrieval and streaming

`ask(question, depth="standard", verbose=False)` returns a compact result by
default over MCP and HTTP JSON/SSE:

- Answer: `{"outcome":"answered","answer":"…","confidence":"medium"}`.
- Clarification: `{"outcome":"needs_clarification","question":"…"}`.

Set `verbose: true` in the request arguments for the full result, including
interpretation, gaps, provenance and trace, or clarification candidates and
known_so_far. The cockpit requests this detailed result explicitly.
`run_ask` and server-side traces retain the full result. Verbosity changes only
response formatting, not reasoning, retrieval depth, or model latency.

## HTTP events

`POST /ask` opts into SSE with `Accept: text/event-stream`; the JSON body remains
`{"question":"…","depth":"standard"}`. Ordinary JSON requests retain the
finish-fast response and whitespace keepalives for slow calls. After headers
have been sent, JSON failures use `{"detail":"…"}` and SSE failures use an
`error` event; clients must inspect the body, not just HTTP 200.

Each SSE frame has `event: <type>` and one JSON `data:` payload:

| Type | Payload | Meaning |
| --- | --- | --- |
| `progress` | `phase`, `message` | Factual retrieval start/completion/failure, evidence checks, or answer composition. |
| `answer_delta` | `text` | Append provisional answer text. Never a thinking block or intermediate model narrative. |
| `answer_reset` | `message` | Discard the provisional answer, for example after invalid provenance. |
| `complete` | `result` | Replace provisional state with the validated structured result. May be clarification. |
| `error` | `message` | No completed result was available. |
| `cancelled` | `message` | The run ended through cancellation. |

Phases are `retrieval`, `evidence_check` and `composition`. Comment frames are
keepalives. Only `complete` commits an answer. EOF, invalid JSON, a network error
or cancellation before `complete` leaves an incomplete result, even if some text
was visible. Clients should not concatenate draft text with `complete.result.answer`.
There is no event replay/resume protocol; retry starts a fresh run.

The cockpit consumes events, displays provisional text and factual progress,
and provides Cancel. It aborts on navigation, retry and replacement questions,
and ignores events/results from older requests. Completed JSON remains a fallback
for a server that does not support the opt-in stream.

Both provider adapters stream tool arguments; Ask exposes only the `answer`
string from `submit_answer`. It does not add another model call for streaming.
Standard mode suppresses answer deltas until the evidence floor is satisfied.
Quick mode retains its existing relaxed floor. The complete tool input still
undergoes local schema and evidence validation. Malformed or interrupted output
is never accepted by truncating it into JSON. The existing bounded recovery can
produce an explicitly degraded, low-confidence result, or a synthetic fallback.
OpenAI retries transient failures before stream output using the existing retry
configuration; midstream output is reset rather than silently replayed.

## Combined retrieval

The reader tool `retrieve_context(query, names, entity_limit=3,
statement_limit=6, linked_limit=8)` is available through HTTP, MCP and read-tool
discovery. It performs name-prefix lookup across aliases, semantic name lookup
if no prefix candidates exist, entity hydration, query-relevant statement search
filtered by each selected entity, and one linked-statement fetch. Candidate
matches are explicitly candidates; they do not resolve ambiguity by themselves.

Input ranges are 1–3 supplied names, `entity_limit` 1–3, `statement_limit` 1–8,
and `linked_limit` 1–12. Output caps are global: up to 3 selected entities,
8 direct statements and 12 linked statements, with zero results possible when
nothing resolves or matches. Retrieval follows one hop and retains at most
20 entries per edge/name/mention list.
A call makes at most 13 primitive reads before the existing substrate retry.
It counts as one bounded tool operation in `op_count`; `combined_reads` records
the successful underlying primitive calls separately.

Statements are deduplicated by ID. Outgoing links, incoming links, condition
references and separate conditional variants keep their original direction and
full AND/OR/NOT trees. Linked retrieval also follows condition leaf IDs. Entity
relationships remain separate from statement relationships. `resolutions`,
`missing`, `limits`, `truncated`, and per-record `*_truncated` totals describe
what resolved and what was omitted. Existing truncation totals survive a tighter
combined limit. Use targeted reads for relevant omitted context or further hops.

This operation is targeted retrieval, not adjacency research. In standard mode,
a later `search_statements` or `survey_statements` call must supply
`adjacency_sources`: statement refs actually supplied by a completed earlier
targeted turn. Recon-only evidence, unread link targets, failed reads and sibling
reads in the same turn cannot qualify. Repeating the literal original question
does not qualify. Vocabulary reads do not count as targeted evidence retrieval.
The model must seed the search with the referenced concepts; the harness checks
source availability and turn ordering, not semantic truth or query relevance.

## Compact model output and provenance

Model-generated answer fields are `answer`, `confidence`, `gaps`, `provenance`
and nullable `interpretation`. An interpretation change contains only
`resolved_to` and `reason`. Code supplies the literal question, default resolved
question, `reframed`, full provenance IDs and trace metadata. The model still
reports contradictions, unresolved coverage, missing terms and interpretation
changes; there is no generated sub-question ledger or adjacency summary.

Complete supplied statement records receive short run-local refs (`s1`, `s2`, …).
Only those records can support provenance or subsequent adjacency sources.
Reference expansion rejects unknown refs, unknown statement IDs, entity IDs and
unread pointers. Known full statement IDs remain accepted for injected/older
model clients. Before returning the completed `Answered` result, `_finish_answer`
expands run-local provenance refs into full statement IDs. Clients receive those
IDs, not refs such as `s1`. These refs are internal evidence identifiers for
provenance and adjacency sources; they are not stable across runs and must not
appear as unexplained codes in answer prose or other final answer values.

Ask's 20,000-character tool-context budget omits whole entries and reports
`omitted_items`; it never slices a statement or condition tree. Omitted records
do not acquire usable refs. Recon retains conditions and reverse relationships.
Truncated context adds a deterministic coverage gap and caps high confidence at
medium; no cited evidence caps confidence at low. Forced finalization preserves
these gaps and adds its reason.

## Tracing and client limitations

Trace version 2 retains existing fields. `sub_question_ledger` is an empty
compatibility field; `adjacency_note` is a code-generated count on submitted
answers. New fields include `evidence_checks`, `combined_reads`, `evidence_refs`
and `supplied_context_chars`. `stream_timing_ms` distinguishes
`first_progress_ms`, `first_answer_text_ms` and `completion_ms`. First-text timing
measures first visible provisional text, including a draft later reset. Visibility
timings are absent for completed-only callers. Cancelled/error traces have no
completion timing. These are server emission times; browser paint and proxy
buffering are not measured.

MCP continues to return one completed structured result. It does not expose Ask's
SSE progress or answer deltas, and a client's own timeout may end the call first.
MCP request cancellation and HTTP disconnects signal the worker to stop. Sync
retrieval/model I/O is cooperative: an in-flight blocking call may finish or reach
its configured timeout before cancellation is observed; no further model
finalization is started once it is observed. HTTP stream queues are bounded.
Disconnect releases a producer blocked on that queue; a connected consumer that
blocks event delivery for 30 seconds also cancels the run and releases the worker
slot. A disconnected client cannot receive a cancellation event and must mark
its own result incomplete.

No deployed instance, private data or real model credentials are required for
verification:

```sh
uv run pytest -q
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
node --test tests/test_ask_client.mjs
```

The synthetic comparison in `test_ask_retrieval.py` exercises the same four
primitive reads and evidence with six model turns before consolidation versus
three after it. Its compact-output fixture is over 25% smaller than the former
generated payload while retaining uncertainty and interpretation changes. These
are controlled payload/turn comparisons, not production latency claims.
