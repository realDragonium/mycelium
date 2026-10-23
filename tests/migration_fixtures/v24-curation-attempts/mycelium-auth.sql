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
INSERT INTO "invites" VALUES('693d8a85-fbb1-454d-a026-ae2a3c8a50da','bea@example.com','writer','JCPNmyOZB9Cd1_pVV0vDEqU4uyY63N6X','9797d2a1-8d0a-4ed5-b221-d82b983e989e','2026-10-23T17:20:46.142414+00:00',NULL,NULL,NULL);
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
INSERT INTO "mcp_tokens" VALUES('5481ca4e-010f-4b60-a83b-204434b9b810','9797d2a1-8d0a-4ed5-b221-d82b983e989e','laptop','547919','b05bcb2a7706506ecfff72f495720c73ff6912de5f08106e3d245cc8d4b630e1','writer','2026-10-23T17:20:46.142386+00:00',NULL,NULL,NULL,NULL,NULL);
INSERT INTO "mcp_tokens" VALUES('11f0dc0a-ddbb-45a9-9ef9-567d0958e5bb','9797d2a1-8d0a-4ed5-b221-d82b983e989e','OAuth: Claude','7e212c','ddfef1f2e3181e370c65d6dae60cc948dbf1461b208a7d76a2876ddc70b87b9c','admin','2026-10-23T17:20:46.142457+00:00',NULL,NULL,'client-1','2026-08-01T01:00:00+00:00',NULL);
INSERT INTO "mcp_tokens" VALUES('705081e2-fa81-4999-a425-c07dd562598d','9797d2a1-8d0a-4ed5-b221-d82b983e989e','external','764934','06c48d40c85f0a6fd91a57167e45b0ad2a1e387634d82e2a7c0d0fd96bffbd95','reader','2026-10-23T17:20:46.142503+00:00',NULL,NULL,NULL,NULL,'external-technical');
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
INSERT INTO "oauth_refresh_tokens" VALUES('e70c89db5c853604405bce9ee77e86161aa3daa3bae38cdd6d7cc12d6ee2a87e','11f0dc0a-ddbb-45a9-9ef9-567d0958e5bb','2026-08-01T00:00:00+00:00','2026-08-31T00:00:00+00:00',NULL);
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
INSERT INTO "users" VALUES('9797d2a1-8d0a-4ed5-b221-d82b983e989e','human','ada@example.com','Ada','admin','active',NULL,NULL,'2026-10-23T17:20:46.142344+00:00',NULL,NULL,NULL);
CREATE INDEX mcp_tokens_user   ON mcp_tokens (user_id);
CREATE INDEX mcp_tokens_hash   ON mcp_tokens (hash);
CREATE INDEX mcp_tokens_client ON mcp_tokens (client_id);
CREATE INDEX oauth_refresh_tokens_token ON oauth_refresh_tokens (token_id);
CREATE INDEX oauth_codes_expiry ON oauth_codes (expires_at);
CREATE INDEX oauth_consents_expiry ON oauth_consents (expires_at);
COMMIT;
