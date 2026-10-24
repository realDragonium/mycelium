PRAGMA user_version = 0;
BEGIN TRANSACTION;
CREATE TABLE invites (
    id          TEXT PRIMARY KEY,
    email       TEXT NOT NULL,
    role        TEXT NOT NULL,  -- free-form; see auth.Role
    token       TEXT NOT NULL UNIQUE,
    invited_by  TEXT REFERENCES users(id),
    created_at  TEXT NOT NULL,
    expires_at  TEXT,
    accepted_at TEXT,
    accepted_by TEXT REFERENCES users(id)
);
INSERT INTO "invites" VALUES('b53961f4-9eba-4449-a3d3-24381752c713','bea@example.com','writer','qMluprET3w9us5MaOQ8xHqM9Pwwo8_uN','8a94433e-2b5d-43c8-95c8-d2b39e5a2a58','2026-10-24T10:17:25.893212+00:00',NULL,NULL,NULL);
CREATE TABLE mcp_tokens (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    prefix       TEXT NOT NULL UNIQUE,
    hash         TEXT NOT NULL,
    scope        TEXT NOT NULL,  -- free-form; narrowed against the owner's role in code
    created_at   TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at   TEXT,
    client_id    TEXT REFERENCES oauth_clients(client_id) ON DELETE SET NULL,
    expires_at   TEXT,
    audience_id  TEXT
);
INSERT INTO "mcp_tokens" VALUES('4499b569-5ce3-4cea-b98b-2dc204717202','8a94433e-2b5d-43c8-95c8-d2b39e5a2a58','laptop','32d850','de35bc738ae48407360fb27d64ccbec0960f8812b62d1dc149bcab225e8f6c5b','writer','2026-10-24T10:17:25.893185+00:00',NULL,NULL,NULL,NULL,NULL);
INSERT INTO "mcp_tokens" VALUES('d410bdd6-0508-4f8f-b6cc-b93c1ba9f748','8a94433e-2b5d-43c8-95c8-d2b39e5a2a58','OAuth: Claude','25e390','dcea23fda8c60c47973c160b67f2580b3b2335b91ad5c7b9c6d90217a87030af','admin','2026-10-24T10:17:25.893263+00:00',NULL,NULL,'client-1','2026-08-01T01:00:00+00:00',NULL);
INSERT INTO "mcp_tokens" VALUES('9d5ddfd3-0c8e-4bc1-94c0-8812c97c8024','8a94433e-2b5d-43c8-95c8-d2b39e5a2a58','external','96d83e','0e1071bd4fd8ef314419177fcbaf4135e6898b3b449bbacd0febeccf4529c7b9','reader','2026-10-24T10:17:25.893321+00:00',NULL,NULL,NULL,NULL,'external-technical');
CREATE TABLE oauth_clients (
    client_id     TEXT PRIMARY KEY,
    client_name   TEXT,
    redirect_uris TEXT NOT NULL,   -- JSON array of allowed redirect URIs
    created_at    TEXT NOT NULL,
    last_used_at  TEXT
);
INSERT INTO "oauth_clients" VALUES('client-1','Claude','["http://localhost/cb"]','2026-08-01T00:00:00Z',NULL);
CREATE TABLE oauth_codes (
    code                  TEXT PRIMARY KEY,
    client_id             TEXT NOT NULL REFERENCES oauth_clients(client_id) ON DELETE CASCADE,
    user_id               TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    redirect_uri          TEXT NOT NULL,
    code_challenge        TEXT NOT NULL,
    code_challenge_method TEXT NOT NULL CHECK (code_challenge_method IN ('S256', 'plain')),
    scope                 TEXT,
    resource              TEXT,
    created_at            TEXT NOT NULL,
    expires_at            TEXT NOT NULL,
    used_at               TEXT,
    audience_id           TEXT
);
CREATE TABLE oauth_consents (
    id                    TEXT PRIMARY KEY,
    user_id               TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    client_id             TEXT NOT NULL,
    redirect_uri          TEXT NOT NULL,
    code_challenge        TEXT NOT NULL,
    code_challenge_method TEXT NOT NULL,
    scope                 TEXT,
    resource              TEXT,
    state                 TEXT,
    created_at            TEXT NOT NULL,
    expires_at            TEXT NOT NULL,
    used_at               TEXT
);
CREATE TABLE oauth_refresh_tokens (
    hash       TEXT PRIMARY KEY,
    token_id   TEXT NOT NULL REFERENCES mcp_tokens(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at    TEXT
);
INSERT INTO "oauth_refresh_tokens" VALUES('e70c89db5c853604405bce9ee77e86161aa3daa3bae38cdd6d7cc12d6ee2a87e','d410bdd6-0508-4f8f-b6cc-b93c1ba9f748','2026-08-01T00:00:00+00:00','2026-08-31T00:00:00+00:00',NULL);
CREATE TABLE users (
    id            TEXT PRIMARY KEY,
    type          TEXT NOT NULL CHECK (type IN ('human', 'service')),
    email         TEXT,
    name          TEXT NOT NULL,
    role          TEXT NOT NULL,  -- free-form; valid roles live in code (auth.Role), not the DB
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended')),
    oidc_issuer   TEXT,
    oidc_subject  TEXT,
    created_at    TEXT NOT NULL,
    created_by    TEXT,
    last_login_at TEXT,
    audience_id   TEXT,  -- set: reads only what this audience may see; see principal_audience
    UNIQUE (oidc_issuer, oidc_subject),
    UNIQUE (email)
);
INSERT INTO "users" VALUES('8a94433e-2b5d-43c8-95c8-d2b39e5a2a58','human','ada@example.com','Ada','admin','active',NULL,NULL,'2026-10-24T10:17:25.893142+00:00',NULL,NULL,NULL);
CREATE INDEX mcp_tokens_user   ON mcp_tokens (user_id);
CREATE INDEX mcp_tokens_hash   ON mcp_tokens (hash);
CREATE INDEX mcp_tokens_client ON mcp_tokens (client_id);
CREATE INDEX oauth_refresh_tokens_token ON oauth_refresh_tokens (token_id);
CREATE INDEX oauth_codes_expiry ON oauth_codes (expires_at);
CREATE INDEX oauth_consents_expiry ON oauth_consents (expires_at);
COMMIT;
