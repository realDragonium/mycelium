## MODIFIED Requirements

### Requirement: Current principal
`GET /api/me` SHALL return the caller's `id`, `name`, `role` (after token clamping), `type` (`human` or `service`), `synthetic` and `auth_enabled`.

#### Scenario: Reader-scoped token of an admin
- **WHEN** an admin calls `/api/me` with a token minted with scope `reader`
- **THEN** the response has `role: "reader"`

### Requirement: User management
Every `/api/admin/*` endpoint SHALL require the admin role (403 "admin role required" otherwise). `GET /api/admin/users` SHALL list users oldest first. `POST /api/admin/users` SHALL create a user (`name` 1 to 120 characters, `role` default `writer`, `type` default `service`); a `human` user MUST have an email (400 otherwise). `PATCH /api/admin/users/{user_id}` SHALL change `role`, `status` (`active` or `suspended`, else 400) and `name` (404 for an unknown user).

#### Scenario: Create a service account
- **WHEN** an admin posts `{"name": "ci-export-bot", "role": "writer"}` to `/api/admin/users`
- **THEN** a `service` user with the writer role and no email is created

### Requirement: Personal token management
Every principal SHALL manage their own tokens: `GET /api/me/tokens` lists them newest first, revoked ones included; `POST /api/me/tokens` mints one (`name` 1 to 80 characters, `scope` default `writer`, capped at the caller's role); `DELETE /api/me/tokens/{token_id}` revokes one, answering 404 for a token unknown or owned by someone else. Personal tokens SHALL never expire.

#### Scenario: Revoking another user's token
- **WHEN** a writer deletes `/api/me/tokens/{id}` for a token owned by someone else
- **THEN** the response is 404 and the token stays valid

#### Scenario: Local admin mints a token
- **WHEN** auth is off and the local admin mints a token
- **THEN** the token is owned by the `local-admin` user

### Requirement: Token listing fields
Each listed token SHALL show `id`, `name`, `prefix`, `scope`, `created_at`, `last_used_at`, `revoked_at` and `oauth` (whether an OAuth client holds it), and never its secret or hash.

#### Scenario: OAuth connection in the list
- **WHEN** a user has connected a desktop client through OAuth
- **THEN** their token list has one entry for it with `oauth: true`

### Requirement: Admin token management
An admin SHALL list any user's tokens (`GET /api/admin/users/{user_id}/tokens`) and revoke any token idempotently (`DELETE /api/admin/tokens/{token_id}`).

#### Scenario: Revoke twice
- **WHEN** an admin revokes the same token twice
- **THEN** both calls answer `{"ok": true}` and the first revocation time is kept

### Requirement: Authorization request and consent
`GET /authorize` SHALL require `response_type=code`, a `code_challenge`, `code_challenge_method=S256`, a known client and an allowed redirect URI (400 otherwise). Without a signed-in user it SHALL redirect to `/auth/login` with the authorize URL as `next`. Otherwise it SHALL record the request and show a consent page naming the client, the user and role, the redirect host and the access granted, warning on a loopback redirect.

#### Scenario: Not signed in
- **WHEN** an anonymous browser opens a valid `/authorize` URL
- **THEN** it is redirected to `/auth/login?next=<the authorize URL>`

### Requirement: Consent decisions
`POST /authorize/decide` SHALL take only the consent id and the decision; every OAuth parameter SHALL come from the recorded request, and the client and redirect SHALL be re-validated. A consent SHALL be answerable once, only by the user it was shown to, within 600 seconds; otherwise the response is 400 `invalid_request`.

#### Scenario: Submitted OAuth parameters are ignored
- **WHEN** an approval is submitted with extra `client_id` and `redirect_uri` fields naming another client
- **THEN** the code is issued to the client and redirect URI recorded when the consent page was shown

#### Scenario: Second answer
- **WHEN** the same consent is approved twice
- **THEN** the second submission answers 400

### Requirement: Token response
A successful exchange SHALL create a token named `OAuth: <client name>` whose scope is the user's current role, and answer with `access_token`, `token_type: "Bearer"`, `expires_in`, `refresh_token` and `scope`, with `Cache-Control: no-store`.

#### Scenario: Writer connects a client
- **WHEN** a writer completes the flow
- **THEN** the token response has `scope: "writer"` and `expires_in: 3600` by default
