## MODIFIED Requirements

### Requirement: Listening before startup finishes
The system SHALL start listening before migrations and index loading finish, run startup in the background, and report its state as `starting`, `migrating`, `indexing`, `ready` or `failed`. `/api/server-info` SHALL answer 200 in every state but `failed`, which answers 503, so a health check does not restart a long migration or index rebuild.

#### Scenario: Health check during a slow start
- **WHEN** a load balancer probes `/api/server-info` while migrations run
- **THEN** it receives 200 with `state` `migrating`, a `detail` naming the step under way and `elapsed_s`

#### Scenario: Ready
- **WHEN** startup has finished
- **THEN** `/api/server-info` answers 200 with `"state": "ready"`

#### Scenario: Failed start
- **WHEN** a load balancer probes `/api/server-info` after startup failed
- **THEN** it receives 503 with `state` `failed` and the reason

### Requirement: Startup gate
The system SHALL, until startup is ready, answer every HTTP request itself before any layer reads a database: `/api/server-info` with the startup state, API calls with 503, a `Retry-After: 5` header and the startup state, and browser navigations with a 503 page that reloads itself every 5 seconds.

#### Scenario: API call while starting
- **WHEN** a client calls `POST /search-statements` while the indexes load
- **THEN** it receives 503 with `Retry-After: 5` and a detail ending "Try again shortly."

#### Scenario: Browser while starting
- **WHEN** a person opens the web app while the server starts
- **THEN** the page says Mycelium is starting and reloads itself

### Requirement: Slow request log
The system SHALL log one `MYCELIUM_SLOW_REQUEST` line with the route and the time per phase for each request or tracked background job that takes at least `MYCELIUM_SLOW_REQUEST_MS` milliseconds (default 2000), fails, or whose client disconnects before the response ends; the answers the startup gate gives while the server is still starting MUST NOT be logged or counted.

#### Scenario: Slow search
- **WHEN** a search request takes 3 seconds with the default threshold
- **THEN** a line starting `MYCELIUM_SLOW_REQUEST route=` with `total_ms=` and per-phase fields is logged

#### Scenario: Client leaves
- **WHEN** a client disconnects before a response finishes
- **THEN** the request is logged with `disconnected=True` and not counted as failed

#### Scenario: Health check while starting
- **WHEN** a health check polls `/api/server-info` before startup has finished
- **THEN** no `MYCELIUM_SLOW_REQUEST` line is logged
