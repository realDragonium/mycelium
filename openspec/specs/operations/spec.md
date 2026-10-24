# operations Specification

## Purpose
Run a Mycelium server process predictably: how it starts and reports startup, which requests it accepts, how background workers run, how it can open a copy of production data safely, and how operators see errors and slow requests.

## Requirements

### Requirement: Server entry points
The system SHALL serve HTTP, the REST mirror of every tool, the browser app and the MCP endpoint `/mcp` from `mycelium-http`, bound to `MYCELIUM_HTTP_HOST` (default `127.0.0.1`) and `MYCELIUM_HTTP_PORT` (default `8765`), and SHALL serve MCP over stdio from `mycelium` or `mycelium serve`.

#### Scenario: Default bind
- **WHEN** `mycelium-http` starts with no host or port configured
- **THEN** it listens on `127.0.0.1:8765`

#### Scenario: HTTP without MCP
- **WHEN** `mycelium-http` starts with `MYCELIUM_DISABLE_MCP_HTTP=1`
- **THEN** the REST routes and `/api/*` are served and `/mcp` is not

### Requirement: One server process per data directory
The system SHALL serialise writes only within one process, so an operator MUST run at most one server process against a data directory; the system does not detect or prevent a second one.

#### Scenario: Two processes on one directory
- **WHEN** an operator starts both `mycelium-http` and `mycelium serve` on the same data directory
- **THEN** both start, and their writes are not serialised against each other

### Requirement: Listening before startup finishes
The system SHALL start listening before migrations and index loading finish, run startup in the background, and report its state as `starting`, `migrating`, `indexing`, `ready` or `failed`.

#### Scenario: Health check during a slow start
- **WHEN** a load balancer probes `/api/server-info` while migrations run
- **THEN** it receives 503 with `state` `migrating`, a `detail` naming the step under way and `elapsed_s`

#### Scenario: Ready
- **WHEN** startup has finished
- **THEN** `/api/server-info` answers 200 with `"state": "ready"`

### Requirement: Startup gate
The system SHALL, until startup is ready, answer every HTTP request itself before any layer reads a database: `/api/server-info` and API calls with 503, a `Retry-After: 5` header and the startup state, and browser navigations with a 503 page that reloads itself every 5 seconds.

#### Scenario: API call while starting
- **WHEN** a client calls `POST /search-statements` while the indexes load
- **THEN** it receives 503 with `Retry-After: 5` and a detail ending "Try again shortly."

#### Scenario: Browser while starting
- **WHEN** a person opens the web app while the server starts
- **THEN** the page says Mycelium is starting and reloads itself

### Requirement: Startup progress reporting
The system SHALL use each migration and index-rebuild progress log line as the startup `detail` while that step runs, and SHALL log "startup finished in" with the seconds taken when startup is ready.

#### Scenario: Index rebuild progress
- **WHEN** the statement index is being rebuilt by re-embedding
- **THEN** `/api/server-info` shows the latest rebuild progress line as its detail

### Requirement: Failed startup exits
The system SHALL, when background startup fails, log one `MYCELIUM_ERROR` line with `where=startup`, report `failed` with the reason, stop serving and exit with status 1; the startup page MUST NOT reload itself after a failure.

#### Scenario: Refused migration
- **WHEN** startup fails because the substrate's schema version is newer than the build's
- **THEN** a `MYCELIUM_ERROR where=startup` line is logged and `mycelium-http` exits with status 1

### Requirement: Contradictory configuration refuses to start
The system MUST refuse to start, before listening, when the email domain policy is contradictory (see the `access-control` capability).

#### Scenario: Just-in-time domain not allowed
- **WHEN** `MYCELIUM_JIT_DOMAINS` names a domain that `MYCELIUM_ALLOWED_EMAIL_DOMAINS` does not allow
- **THEN** `mycelium-http` exits without ever listening

### Requirement: Interrupted work is marked on restart
The system SHALL, on startup, mark documentation runs, documentation plans and document maintenance that a previous process left unfinished as failed or interrupted, and SHALL log how many documentation runs were orphaned.

#### Scenario: Restart during a documentation run
- **WHEN** the server restarts while a documentation run is running
- **THEN** that run is marked failed as orphaned by restart, and a warning reports the count

### Requirement: Server info endpoint
The system SHALL answer `GET /api/server-info` without authentication and without the host check, on the event loop rather than a worker thread, with `base_url`, `mcp_url`, `auth_enabled`, `partial_restore`, `quarantine` and `state`, exposing no secrets.

#### Scenario: Probe while every worker thread is busy
- **WHEN** every worker thread is occupied by long tool calls
- **THEN** `/api/server-info` still answers promptly

### Requirement: Host header allowlist
The system SHALL reject with 421 `{"detail": "invalid host header"}` any request whose `Host` hostname is not a loopback name (`localhost`, `127.0.0.1`, `::1`), an entry of `MYCELIUM_ALLOWED_HOSTS` (comma-separated, port ignored) or the host of `MYCELIUM_PUBLIC_URL`; the check SHALL always apply with authentication off and, with authentication on, only once either variable is set.

#### Scenario: DNS rebinding with auth off
- **WHEN** authentication is off and a request arrives with `Host: invoices.attacker.example`
- **THEN** it is refused with 421

#### Scenario: Auth on with no hosts configured
- **WHEN** authentication is on and neither `MYCELIUM_ALLOWED_HOSTS` nor `MYCELIUM_PUBLIC_URL` is set
- **THEN** requests for any hostname are accepted

#### Scenario: Port in an entry
- **WHEN** `MYCELIUM_ALLOWED_HOSTS` is `kb.example.com:8443` and a request has `Host: kb.example.com`
- **THEN** the request is accepted

### Requirement: Request body limit
The system SHALL refuse with 413 any request body larger than `MYCELIUM_MAX_BODY_BYTES` (default 4 MiB, 4,194,304 bytes), including `/mcp`, except media upload and content routes, which are bounded by the media size limits (see the `media` capability).

#### Scenario: Oversized ingest
- **WHEN** a client posts a 5 MiB body to `/ingest` with the default limit
- **THEN** it receives 413 before the server reads the rest

### Requirement: Security headers
The system SHALL add `X-Frame-Options: DENY`, `Content-Security-Policy: frame-ancestors 'none'` and `X-Content-Type-Options: nosniff` to every HTTP response that does not already set them, error responses included.

#### Scenario: Error response
- **WHEN** a request is refused with 421
- **THEN** the response still carries the three headers

### Requirement: Error responses
The system SHALL answer a request that a tool or setting refuses as invalid with 400 and its message, a state conflict with 409 and its message plus an optional `code`, a missing role with 403, and any other unhandled error with 500 `{"detail": "internal server error"}`.

#### Scenario: Unexpected failure
- **WHEN** a route raises an unexpected exception
- **THEN** the client receives 500 with `{"detail": "internal server error"}` and no internal details

### Requirement: Error log line
The system SHALL log every unhandled HTTP error as one line on standard error beginning with `MYCELIUM_ERROR`, carrying `where=http`, the exception type, its message cut to 500 characters on one line, the path and the method, with the traceback attached, regardless of whether tracing is on; deliberate 4xx responses MUST NOT produce this line, and failing to log MUST NOT change the response.

#### Scenario: Counting errors
- **WHEN** an unexpected exception occurs on `GET /api/knowledge-health`
- **THEN** standard error receives a line starting `MYCELIUM_ERROR where=http exc=` that includes `path=/api/knowledge-health method=GET`

#### Scenario: Bad input
- **WHEN** a tool call fails with a 400 validation error
- **THEN** no `MYCELIUM_ERROR` line is logged

### Requirement: Request timing
The system SHALL time every HTTP request and each tracked background job, splitting its time into time to first byte, waiting for a worker thread, running in one, write-lock wait and hold, embedding, SQLite and model calls, and SHALL label a `POST /mcp` request by its JSON-RPC method and, for a tool call, the tool name.

#### Scenario: MCP tool call label
- **WHEN** a client calls the `ask` tool over `/mcp`
- **THEN** the request is recorded as `MCP tools/call ask`

### Requirement: Slow request log
The system SHALL log one `MYCELIUM_SLOW_REQUEST` line with the route and the time per phase for each request or tracked background job that takes at least `MYCELIUM_SLOW_REQUEST_MS` milliseconds (default 2000), fails, or whose client disconnects before the response ends.

#### Scenario: Slow search
- **WHEN** a search request takes 3 seconds with the default threshold
- **THEN** a line starting `MYCELIUM_SLOW_REQUEST route=` with `total_ms=` and per-phase fields is logged

#### Scenario: Client leaves
- **WHEN** a client disconnects before a response finishes
- **THEN** the request is logged with `disconnected=True` and not counted as failed

### Requirement: Performance summary
The system SHALL serve an admin-only `GET /api/admin/performance`, answered on the event loop, reporting `window_seconds` (900), `slow_request_ms`, worker-thread `limit`, `busy` and `waiting`, and per route over the last 15 minutes the count, errors, disconnects and nearest-rank p50, p95 and maximum of the total and each phase, slowest p95 first; at most 20,000 recent samples are kept.

#### Scenario: Reader request
- **WHEN** a reader requests `/api/admin/performance`
- **THEN** it is refused with 403

#### Scenario: Routes by template
- **WHEN** an admin reads the summary after several `GET /api/drafts/{draft_id}` requests
- **THEN** they are grouped under the route template rather than per draft ID

### Requirement: Profiling traces
The system SHALL keep profiling traces off by default, unless `MYCELIUM_TRACE_ENABLED` is `1`, `on`, `true` or `yes`, and SHALL let an admin read the state with `GET /api/tracing`, turn it on with `POST /api/tracing/enable` (optionally `?minutes=N`, after which it turns itself off) and off with `POST /api/tracing/disable`.

#### Scenario: Debugging window
- **WHEN** an admin calls `POST /api/tracing/enable?minutes=15`
- **THEN** `GET /api/tracing` reports `enabled` true with `expires_in_s` counting down from 900, and tracing is off after 15 minutes

### Requirement: Trace files
The system SHALL, while tracing is on, write a self-contained HTML flamegraph and a `.meta.json` sidecar for each traced operation to `MYCELIUM_TRACE_DIR` (default `<data dir>/traces`), keep the newest `MYCELIUM_TRACE_KEEP` traces (default 200, 0 disables pruning), and serve them to admins through `GET /api/traces` (newest 100, each with a `view_url`) and `GET /api/traces/{id}`.

#### Scenario: Viewing a trace
- **WHEN** an admin opens a trace's `view_url`
- **THEN** the flamegraph renders as HTML

#### Scenario: Path in the trace ID
- **WHEN** an admin requests a trace ID containing `..` or a slash
- **THEN** the request fails with 400 "bad trace id"

### Requirement: Run trace logs
The system SHALL append one JSON line per run to `ask_trace.jsonl`, `ingest_trace.jsonl` and `connect_trace.jsonl` in the data directory, or to the file named by `MYCELIUM_ASK_TRACE_LOG`, `MYCELIUM_INGEST_TRACE_LOG` or `MYCELIUM_DOCGEN_TRACE_LOG`, rotating a file before it exceeds `MYCELIUM_TRACE_LOG_MAX_BYTES` (default 10,000,000; 0 disables rotation) and keeping one older generation; a failure to write MUST NOT affect the run.

#### Scenario: Rotation
- **WHEN** appending a record would take `ingest_trace.jsonl` past the limit
- **THEN** the file is renamed to `ingest_trace.jsonl.1`, replacing any earlier one, and the record starts a new file

### Requirement: Background workers
The system SHALL run the mention recompute worker, the embedding retry worker, the audience labeller, the draft-review sweep and document maintenance as background threads started at startup, where a failing pass is logged and the next pass runs on schedule.

#### Scenario: One bad pass
- **WHEN** a draft-review sweep pass raises an error
- **THEN** the error is logged and the sweep runs again after its interval

### Requirement: Disabling workers
The system SHALL skip starting a background worker when its switch is `1`: `MYCELIUM_DISABLE_MENTION_WORKER`, `MYCELIUM_DISABLE_EMBED_WORKER`, `MYCELIUM_DISABLE_AUDIENCE_WORKER`, `MYCELIUM_DISABLE_REVIEW_SWEEP` or `MYCELIUM_DISABLE_MAINTENANCE_WORKER`, and SHALL skip entity layout recomputation when `MYCELIUM_DISABLE_LAYOUT_BAKE` is `1`.

#### Scenario: Labeller off for tests
- **WHEN** the server starts with `MYCELIUM_DISABLE_AUDIENCE_WORKER=1`
- **THEN** new statements are not labelled in the background

### Requirement: Workers stop with the server
The system SHALL stop its background workers when the HTTP server shuts down.

#### Scenario: Shutdown
- **WHEN** `mycelium-http` receives a shutdown signal
- **THEN** the background workers are asked to stop before the process exits

### Requirement: Quarantine
The system SHALL run in quarantine when `MYCELIUM_QUARANTINE` is `1` or `mycelium-http --quarantine` or `mycelium serve --quarantine` is used, and in quarantine SHALL NOT start the audience labeller, the draft-review sweep or document maintenance, SHALL treat draft review as off, and MUST refuse GitHub delivery, without changing any saved setting.

#### Scenario: Opening a restored copy
- **WHEN** a restored copy whose saved draft-review mode is `review-only` starts with `--quarantine`
- **THEN** submitted drafts are not reviewed, while `GET /api/draft-review/settings` still reports `review-only`
- **AND** publishing a document fails with "Publishing is off: this server runs in quarantine, so nothing is sent to GitHub."

#### Scenario: Leaving quarantine
- **WHEN** the same data directory starts without the flag
- **THEN** the background workers, draft review and delivery run as saved

### Requirement: Quarantine is visible
The system SHALL report `"quarantine": true` from `/api/server-info` and the setup checklist, and log a warning at startup, while quarantine is on; interactive Ask, ingest and documentation runs SHALL still work.

#### Scenario: Banner state
- **WHEN** the web app reads `/api/server-info` from a quarantined server
- **THEN** the response has `"quarantine": true`

### Requirement: Setup checklist
The system SHALL serve an admin-only `GET /api/setup` with the steps `credentials`, `models`, `audiences`, `profile`, `github` (optional), `review` and `budget` (optional), each `done`, `todo` or `dismissed` with a detail and the settings screen it is completed on, plus `complete`, `blocked` and `quarantine`, computed from saved settings and counts without any provider request.

#### Scenario: Dismissing an optional step
- **WHEN** an admin sends `PUT /api/setup/steps/budget` with `{"dismissed": true}` while no budget is set
- **THEN** the `budget` step reports `dismissed`, and `complete` is true once every other step is done or dismissed

#### Scenario: Step done later
- **WHEN** a dismissed step's condition becomes satisfied
- **THEN** the step reports `done`

### Requirement: Blocked background work
The system SHALL list in the setup checklist's `blocked` each background worker that is switched on but whose provider credentials are missing: draft review when its mode is not off, audience labelling when automatic, and document maintenance when a profile auto-revises; in quarantine the list MUST be empty.

#### Scenario: Review without credentials
- **WHEN** draft review is in `review-only` mode and the review provider has no credentials
- **THEN** `blocked` contains `Draft review` with a reason ending "Submitted drafts wait unreviewed."

### Requirement: Packaged assets
The system SHALL ship the ingest and documentation doctrines, the guideline rows and the built browser app inside the installed package, so that an installation outside a source checkout serves them.

#### Scenario: Installed wheel
- **WHEN** the package is installed from its wheel and started outside the repository
- **THEN** the default instructions load and `/ui/` serves the browser app
