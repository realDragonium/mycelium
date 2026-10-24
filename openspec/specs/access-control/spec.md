# access-control Specification

## Purpose
Access control decides who is calling and what they may do: authentication on or off, human logins through OIDC with invites and email-domain policy, service accounts, roles, personal and OAuth-issued bearer tokens, and the role filtering applied to HTTP routes and MCP tools.

## Requirements

### Requirement: Authentication toggle
The system SHALL read `MYCELIUM_AUTH`; only the value `on` (case-insensitive) enables authentication, and the default is off. With authentication off, every request SHALL run as the synthetic principal `local-admin` with the admin role, and no credential is required.

#### Scenario: Auth off
- **WHEN** `MYCELIUM_AUTH` is unset and a client calls `GET /api/me` without credentials
- **THEN** the response has `id: "local-admin"`, `role: "admin"`, `synthetic: true` and `auth_enabled: false`

### Requirement: Session secret required with auth on
With authentication on, the server SHALL refuse to start unless `MYCELIUM_SESSION_SECRET` is set. With authentication off and no secret, it SHALL use an ephemeral per-process key.

#### Scenario: Missing secret
- **WHEN** the server starts with `MYCELIUM_AUTH=on` and no `MYCELIUM_SESSION_SECRET`
- **THEN** startup fails naming `MYCELIUM_SESSION_SECRET`

### Requirement: Unauthenticated requests with auth on
With authentication on, a request without a resolvable session or bearer token to a non-exempt path SHALL be rejected: a browser navigation (accepts `text/html`, no `Authorization` header) SHALL be redirected with 302 to `/auth/logout?next=<original path and query>`, and any other request SHALL get 401 `{"detail": "authentication required"}`. A 401 for `/mcp` SHALL carry `WWW-Authenticate: Bearer realm="mycelium", scope="mcp", resource_metadata="<base>/.well-known/oauth-protected-resource"`.

#### Scenario: MCP client without a token
- **WHEN** an MCP client posts to `/mcp` without credentials while auth is on
- **THEN** the response is 401 with the `WWW-Authenticate` challenge naming the protected-resource metadata

#### Scenario: Browser without a session
- **WHEN** a browser navigates to `/ui/settings` without a session while auth is on
- **THEN** it is redirected to `/auth/logout?next=/ui/settings`

### Requirement: Paths open without signing in
With authentication on, the system SHALL serve without credentials `/`, `/connect`, `/api/server-info`, the OAuth discovery, registration, token and authorize endpoints, `/auth/*`, `/static/*`, `/ui/assets/*`, `/ui/fonts/*`, `/favicon*`, the API docs (`/docs`, `/openapi.json`, `/redoc`) and media upload links (`/api/media/uploads/*`). A path containing `..` SHALL NOT be exempt through a prefix. An exempt path SHALL NOT receive the synthetic admin when auth is on.

#### Scenario: Built assets are public, the app page is not
- **WHEN** an anonymous client requests a file under `/ui/assets/` and then `/ui/` while auth is on
- **THEN** the asset is served and the app page is refused

### Requirement: Principal attribution
Every request SHALL carry one principal, and substrate writes made during the request SHALL record that principal's id as their author (`created_by`, `updated_by`).

#### Scenario: Token write attribution
- **WHEN** a service account's token creates a statement
- **THEN** the statement's `created_by` is the service account's user id

### Requirement: Roles
The system SHALL recognise the roles `asker`, `reader`, `drafter`, `writer` and `admin`, ranked in that order. A tool's required role SHALL follow its name unless the tool declares one: names starting `delete_` or `merge_` require admin, names starting `list_`, `get_`, `search_`, `grep_`, `discover_` or `find_` require reader, and every other tool requires writer. `ask` SHALL require only asker and `report_knowledge_gap` only reader.

#### Scenario: Reader calls a write tool
- **WHEN** a reader calls `upsert_statement`
- **THEN** the call is refused with 403 naming the writer role

#### Scenario: Writer calls an admin tool
- **WHEN** a writer calls `delete_statement`
- **THEN** the call is refused with 403

### Requirement: Drafter role redirects writes
A drafter SHALL pass the role gate of every writer and admin tool, with its write, delete and merge calls queued onto a draft instead of changing the substrate (see the `drafts-and-review` capability). Tools that declare a real role requirement (draft approval and curation, documentation runs, label decisions) SHALL NOT admit a drafter.

#### Scenario: Drafter deletes a statement
- **WHEN** a drafter calls `delete_statement`
- **THEN** the deletion is queued on the drafter's open draft and the statement still exists

#### Scenario: Drafter requests documentation
- **WHEN** a drafter calls `request_documentation`
- **THEN** the call is refused with 403 requiring a real writer role

### Requirement: Asker role
An asker SHALL be able to call `ask` and nothing else that reads the substrate. With an asker principal, every `/api/*` route except `/api/me`, `/api/me/*` and exempt paths SHALL answer 403 "the asker role can only call ask", including routes added later.

#### Scenario: Asker reads the graph
- **WHEN** an asker requests `GET /api/data`
- **THEN** the response is 403

#### Scenario: Asker manages its tokens
- **WHEN** an asker requests `GET /api/me/tokens`
- **THEN** its tokens are listed

### Requirement: One rule for both transports
The HTTP tool routes and MCP tool calls SHALL apply the same role gate for each tool, and `tools/list` SHALL show a caller only the tools that gate lets it call. Without a principal (local stdio) the full list SHALL be shown.

#### Scenario: Listed tools per role
- **WHEN** callers of each role send `tools/list` to `/mcp`
- **THEN** an asker sees only `ask`, a reader 19 tools, a drafter 39 (not `list_drafts`, `request_documentation` or `revise_document`), a writer 39 (not `delete_statement`, `merge_statements` or `merge_entities`) and an admin all 42 advertised tools

#### Scenario: Both MCP protocol revisions
- **WHEN** a reader lists tools once with a 2026-07-28 request and once through a 2025-era session
- **THEN** both lists are filtered identically

### Requirement: Cross-origin writes refused
The system SHALL refuse with 403 "cross-origin request refused" any request with a method other than GET, HEAD or OPTIONS that carries no bearer token and that a browser sent on behalf of another origin: `Sec-Fetch-Site` other than `same-origin` or `none` (so `same-site` counts as foreign), or, without that header, an `Origin` whose host differs from `Host`. This SHALL apply to session-authenticated requests and to every request while auth is off.

#### Scenario: Sibling site posts with the session cookie
- **WHEN** a page on a sibling subdomain posts to `/upsert-statement` with the user's session cookie and `Sec-Fetch-Site: same-site`
- **THEN** the response is 403

#### Scenario: Bearer client
- **WHEN** an agent posts with `Authorization: Bearer myc_…` and no browser headers
- **THEN** the request is not refused for its origin

### Requirement: No framing
Every response SHALL carry `X-Frame-Options: DENY`, `Content-Security-Policy: frame-ancestors 'none'` (unless the route set its own policy) and `X-Content-Type-Options: nosniff`.

#### Scenario: Consent page in a frame
- **WHEN** a page embeds `/authorize` in an iframe
- **THEN** the response forbids framing

### Requirement: Browser session cookie
The browser session SHALL be a signed cookie `myc_session` with `SameSite=Lax`, marked `Secure` when `MYCELIUM_PUBLIC_URL` starts with `https://`, or, without it, when `MYCELIUM_OIDC_REDIRECT_URI` does. Each request SHALL re-read the session user from the auth store, so role, status, scope and domain changes apply on the next request.

#### Scenario: Suspended mid-session
- **WHEN** an admin suspends a signed-in user
- **THEN** the user's next request is treated as unauthenticated

### Requirement: OIDC login routes
With authentication on and `MYCELIUM_OIDC_ISSUER`, `MYCELIUM_OIDC_CLIENT_ID` and `MYCELIUM_OIDC_CLIENT_SECRET` set, `GET /auth/login` SHALL redirect to the issuer with scopes `openid email profile`, the redirect URI `MYCELIUM_OIDC_REDIRECT_URI` (or `/auth/callback`) and any `prompt`. Login and callback SHALL answer 404 with authentication off and 503 without OIDC settings. A `next` target that is not a same-site path SHALL become `/ui/`.

#### Scenario: Open redirect attempt
- **WHEN** a user signs in through `/auth/login?next=https://evil.example`
- **THEN** after login they land on `/ui/`

### Requirement: OIDC callback
`GET /auth/callback` SHALL exchange the code, answer 400 when the exchange fails or the response has no subject, resolve the identity to a user, store the user in the session and redirect to the saved `next`. When no user may be resolved it SHALL answer 403 "this account is not authorized — request an invite from an admin", and when the domain policy refuses it 403 "this service only admits verified email addresses in its allowed domains — sign in with your work account".

#### Scenario: Uninvited login
- **WHEN** someone with a verified email that matches no account, invite, bootstrap admin or JIT domain signs in
- **THEN** no user is created and the callback answers 403

### Requirement: Identity resolution order
The callback SHALL resolve an identity in this order: a user with the same issuer and subject; a user with the same email (case-insensitive) whose issuer is unset or the same, binding the subject to it; the bootstrap admin; a pending invite; a JIT domain. Every step after the first MUST require a verified email; only an `email_verified` claim that is present and not `true` counts as unverified. An email match bound to a different issuer SHALL be refused.

#### Scenario: Unverified email
- **WHEN** a password signup with `email_verified: false` uses an invited address
- **THEN** the invite is not consumed and the callback answers 403

#### Scenario: Issuer without the claim
- **WHEN** the issuer sends no `email_verified` claim
- **THEN** the email counts as verified

### Requirement: Bootstrap admin
A first login whose verified email equals `MYCELIUM_BOOTSTRAP_ADMIN_EMAIL` (case-insensitive) SHALL create an admin user, but only while no user with the admin role exists. The bootstrap SHALL take priority over an invite for the same email, which is then marked accepted.

#### Scenario: Admin already exists
- **WHEN** the bootstrap email signs in for the first time after another admin was created
- **THEN** no admin is created from the bootstrap

### Requirement: Invites
An admin SHALL create invites with `POST /api/admin/invites` (`email` 3 to 254 characters, stored trimmed and lowercased; `role` default `writer`), list pending ones with `GET /api/admin/invites`, each with a `link` to `/auth/invite/{token}` (which redirects to `/auth/login?next=/connect`), and delete one with `DELETE /api/admin/invites/{invite_id}`. A login whose verified email matches a pending invite SHALL get the invited role and consume the oldest match.

#### Scenario: Invite consumed by matching email
- **WHEN** an admin invites `ann@example.com` as reader and Ann signs in with that verified email
- **THEN** Ann's user has the reader role and the invite no longer appears as pending

#### Scenario: Different email
- **WHEN** the invitee signs in with another address
- **THEN** the invite stays pending and the login is refused

### Requirement: Just-in-time provisioning
When a login's verified email domain is listed in `MYCELIUM_JIT_DOMAINS` (comma-separated, case-insensitive, a leading `@` tolerated) and no bootstrap or invite matches, the system SHALL create the user with `MYCELIUM_JIT_DEFAULT_ROLE` (default `reader`). An unknown role name SHALL disable JIT provisioning rather than guess.

#### Scenario: Unknown default role
- **WHEN** `MYCELIUM_JIT_DEFAULT_ROLE=superuser` and a login comes from a JIT domain
- **THEN** no user is created and the login is refused with 403

### Requirement: Email domain policy
When `MYCELIUM_ALLOWED_EMAIL_DOMAINS` is set (comma-separated, exact case-insensitive match, no subdomains) and authentication is on, the system SHALL admit a human only with an email in an allowed domain: every OIDC login needs a verified email in one, and every session, token, consent, code exchange and refresh SHALL be judged by the user's stored email. A human without an email SHALL be blocked; service accounts SHALL be exempt. With authentication off the setting has no effect.

#### Scenario: Subdomain
- **WHEN** the allowed domains are `example.com` and `ann@sub.example.com` signs in
- **THEN** the callback answers 403 with the domain policy message

#### Scenario: Narrowing the list
- **WHEN** an operator removes a domain and restarts
- **THEN** existing sessions and tokens of users in that domain stop working on their next request, without their rows being changed

### Requirement: Domain policy at invite and startup
Creating an invite for an address outside the allowed domains SHALL be refused with 400. The server SHALL refuse to start when `MYCELIUM_JIT_DOMAINS` lists a domain missing from a set `MYCELIUM_ALLOWED_EMAIL_DOMAINS`. `GET /api/admin/users` SHALL flag each user the policy shuts out with `blocked_by_domain_policy: true`.

#### Scenario: Stray JIT domain
- **WHEN** `MYCELIUM_ALLOWED_EMAIL_DOMAINS=example.com` and `MYCELIUM_JIT_DOMAINS=example.org`
- **THEN** startup fails naming `example.org`

### Requirement: Logout
`GET` or `POST /auth/logout` SHALL clear the session and, with authentication on and OIDC configured, redirect to the issuer's `/v2/logout` with `returnTo` set to this server's `/auth/login?next=<next>`; otherwise it SHALL redirect to `/auth/login?next=<next>` directly.

#### Scenario: Logout with OIDC
- **WHEN** a signed-in user opens `/auth/logout`
- **THEN** their session is cleared and they are sent to the issuer's logout, which returns them to `/auth/login`

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

### Requirement: Last admin guard
The system SHALL refuse with 400 "cannot demote the last admin" a role change that would leave no active user with the admin role.

#### Scenario: Sole admin demotes themself
- **WHEN** the only active admin sets their own role to writer
- **THEN** the request is refused with 400 and the role is unchanged

### Requirement: Suspension
A suspended user SHALL be refused on every later request: their session no longer resolves and every token they own stops working at once. Their row and tokens SHALL remain so they can be re-activated.

#### Scenario: Re-activation
- **WHEN** an admin suspends and later re-activates a user
- **THEN** the user's unrevoked tokens work again

### Requirement: Service accounts are token-only
A service account SHALL have no OIDC identity and authenticate only with bearer tokens an admin mints for it through `POST /api/admin/users/{user_id}/tokens`.

#### Scenario: Minting for a service account
- **WHEN** an admin mints a token named `ci-export-bot` for a service account
- **THEN** the raw token is returned once and the service account can call tools with it

### Requirement: Bearer token format and storage
A personal or OAuth access token SHALL have the form `myc_<6 hex prefix>_<secret>` and be accepted only as `Authorization: Bearer <token>`; a bearer value not starting with `myc_` SHALL be ignored. The server SHALL store only the prefix and a SHA-256 hash and return the raw token exactly once, at creation.

#### Scenario: Token shown once
- **WHEN** a user mints a token and then lists their tokens
- **THEN** the list shows the token's prefix but never its secret

### Requirement: Token resolution
A bearer token SHALL authenticate only when it exists, is not revoked, has not expired, and its owner is active and not blocked by the domain policy. When both a valid bearer token and a session are present, the token SHALL decide the principal. A token's last use SHALL be recorded at most once a minute.

#### Scenario: Revoked token
- **WHEN** a client calls `/mcp` with a revoked token while auth is on
- **THEN** the response is 401

### Requirement: Token scope is clamped to the owner's role
A token's effective role SHALL be the lower of its scope and its owner's current role, re-evaluated on every request, so demoting a user narrows every token they hold at once. Minting SHALL cap the requested scope at the minting principal's role (own tokens) or the target user's role (admin minting).

#### Scenario: Demotion narrows an old token
- **WHEN** a user who minted an admin-scoped token is demoted to writer
- **THEN** the token acts as writer on its next request

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

### Requirement: OAuth endpoints require auth on
With authentication off, the OAuth discovery, registration, authorize, decide and token endpoints SHALL answer 404.

#### Scenario: Discovery with auth off
- **WHEN** a client fetches `/.well-known/oauth-authorization-server` while auth is off
- **THEN** the response is 404

### Requirement: Protected resource metadata
With authentication on, `/.well-known/oauth-protected-resource` SHALL return `resource` and `authorization_servers` equal to the issuer, `bearer_methods_supported: ["header"]`, `resource_documentation` `<issuer>/connect` and `scopes_supported: ["mcp"]`.

#### Scenario: Client follows the challenge
- **WHEN** an MCP client fetches the metadata named in a 401 challenge
- **THEN** it learns that this server is its own authorization server

### Requirement: Authorization server metadata
`/.well-known/oauth-authorization-server` SHALL return the issuer, the `/authorize`, `/token` and `/register` endpoints, `scopes_supported: ["mcp"]`, `response_types_supported: ["code"]`, `grant_types_supported: ["authorization_code", "refresh_token"]`, `code_challenge_methods_supported: ["S256"]`, `token_endpoint_auth_methods_supported: ["none"]`, `authorization_response_iss_parameter_supported: true` and `client_id_metadata_document_supported: true`.

#### Scenario: PKCE method advertised
- **WHEN** a client reads the authorization server metadata
- **THEN** `S256` is the only code challenge method listed

### Requirement: Stable OAuth issuer
The OAuth issuer and resource identifier SHALL be `MYCELIUM_PUBLIC_URL` without a trailing slash when set, otherwise the request's base URL.

#### Scenario: Pinned issuer
- **WHEN** `MYCELIUM_PUBLIC_URL=https://kb.example.com` and discovery is fetched through another hostname
- **THEN** the metadata names `https://kb.example.com` as issuer

### Requirement: Dynamic client registration
`POST /register` SHALL register a public client without authentication and answer 201 with a `client_id` starting `mcp_`, the `client_name` (default "Unnamed MCP client"), `redirect_uris`, both grant types, `response_types: ["code"]` and `token_endpoint_auth_method: "none"`. It SHALL answer 400 for a non-object body, bad or over 20 redirect URIs or one over 2000 characters, a name over 200 characters, or types lacking `authorization_code` or `code`, and 413 over 64 KiB.

#### Scenario: Unsupported grant
- **WHEN** a client registers with `grant_types: ["client_credentials"]`
- **THEN** the response is 400 `invalid_client_metadata`

### Requirement: Client ID metadata documents
A `client_id` that is an `https` URL with a path SHALL be resolved by fetching it as a Client ID Metadata Document, without registration. The document MUST be a JSON object answered with HTTP 200 whose `client_id` equals the URL, with a non-empty `client_name` and a non-empty `redirect_uris` list of strings without userinfo. Any failure SHALL make the client unknown (`invalid_client`).

#### Scenario: Document hosted elsewhere
- **WHEN** a document fetched from `https://app.example.com/oauth/client.json` claims a different `client_id`
- **THEN** `/authorize` answers 400 `invalid_client`

### Requirement: Metadata document fetch limits
A metadata document fetch SHALL use port 443 only, refuse userinfo, require every address the host resolves to to be public and connect to the vetted address, follow no redirects, ignore proxy settings, time out after 5 seconds per operation and 10 seconds overall, and read at most 64 KiB.

#### Scenario: Private address
- **WHEN** the client id host resolves to `10.0.0.5`
- **THEN** no document is fetched and the client is unknown

### Requirement: Metadata document caching
Fetched documents SHALL be cached per process: `no-store`, `no-cache` or a non-positive `max-age` SHALL prevent caching, a positive `max-age` SHALL be clamped to 60 to 3600 seconds, and a document without `Cache-Control` SHALL be reused for 300 seconds. At most 256 documents SHALL be cached.

#### Scenario: Revoked redirect
- **WHEN** a client republishes its document with `Cache-Control: no-store`
- **THEN** the next authorization fetches it again

### Requirement: Redirect URI matching
An authorization request's `redirect_uri` SHALL match one of the client's redirect URIs exactly, except that an `http` loopback URI (`localhost`, `127.0.0.1` or `[::1]`) MAY differ only in its port.

#### Scenario: Loopback port
- **WHEN** a client registered `http://127.0.0.1/callback` and authorizes with `http://127.0.0.1:53111/callback`
- **THEN** the redirect is accepted

#### Scenario: Hosted callback
- **WHEN** a client registered `https://app.example.com/cb` and authorizes with `https://app.example.com/cb2`
- **THEN** `/authorize` answers 400

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

### Requirement: Authorization responses
A denial SHALL redirect to the client with `error=access_denied`, a recorded `resource` that does not name this server with `error=invalid_target`, and an approval with a single-use `code` valid for 60 seconds. Every authorization response SHALL carry `state` and `iss` (the issuer).

#### Scenario: Denial
- **WHEN** the user clicks Deny
- **THEN** the browser is redirected to the client's redirect URI with `error=access_denied`, the `state` and `iss`

### Requirement: Resource indicators
A `resource` parameter SHALL name this server: the issuer or its `/mcp` endpoint, with scheme and host compared case-insensitively and one trailing slash ignored; a fragment, query, userinfo or repeated slash SHALL not match. At `/token`, a `resource` that does not name this server, or differs from the one the code was authorized for, SHALL fail with `invalid_target`.

#### Scenario: Token for another server
- **WHEN** a client exchanges a valid code with `resource=https://other.example.com/mcp`
- **THEN** the response is 400 `invalid_target`

### Requirement: Authorization code exchange
`POST /token` with `grant_type=authorization_code` SHALL require `code`, `redirect_uri`, `client_id` and `code_verifier`, and SHALL fail with 400 `invalid_grant` for an unknown, used or expired code, a mismatched client or redirect, a failed S256 PKCE check, or an inactive or domain-blocked user; a code that passed the other checks SHALL be spent even then. Any other grant type SHALL fail with `unsupported_grant_type`.

#### Scenario: Code reuse
- **WHEN** a client exchanges the same code twice
- **THEN** the second exchange fails with `invalid_grant` "code already used"

### Requirement: Token response
A successful exchange SHALL create a token named `OAuth: <client name>` whose scope is the user's current role, and answer with `access_token`, `token_type: "Bearer"`, `expires_in`, `refresh_token` and `scope`, with `Cache-Control: no-store`.

#### Scenario: Writer connects a client
- **WHEN** a writer completes the flow
- **THEN** the token response has `scope: "writer"` and `expires_in: 3600` by default

### Requirement: OAuth token lifetime and refresh
An OAuth access token SHALL expire after `MYCELIUM_OAUTH_ACCESS_TOKEN_TTL_SECONDS` (default 3600) and a refresh token (`mycr_…`, stored hashed) after 30 days. `grant_type=refresh_token` with the matching `client_id` SHALL give the grant a new access token (same prefix and scope) and a new refresh token, spending the old one.

#### Scenario: Expired access token
- **WHEN** a client's access token has expired and it posts its refresh token
- **THEN** it receives a new access token and a new refresh token, and the old refresh token is spent

### Requirement: Refresh token misuse
Presenting a spent refresh token SHALL revoke the whole grant. An unknown, expired or client-mismatched refresh token, a revoked grant, or an inactive or domain-blocked user SHALL fail with `invalid_grant`.

#### Scenario: Replay
- **WHEN** a refresh token is used, and then presented again
- **THEN** the second request fails with `invalid_grant` and the grant's access token stops working

### Requirement: OAuth grants are tokens
Each OAuth grant SHALL be one token row owned by the consenting user, listed among their tokens with `oauth: true`, clamped like any token, and revocable like any token; revoking it SHALL end the connection, including its refresh. OAuth tokens issued before access tokens expired SHALL receive an expiry 30 days after the first startup that introduced expiry.

#### Scenario: Revoke an OAuth connection
- **WHEN** a user revokes their `OAuth: Desktop client` token
- **THEN** the client's access token and refresh token no longer work
