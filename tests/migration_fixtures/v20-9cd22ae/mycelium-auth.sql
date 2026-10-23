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
INSERT INTO "invites" VALUES('2d76e45c-6138-474b-afbf-c9850fd5c6e6','bea@example.com','writer','Ei2Zx7Q1bg6AKgHOb-zbkZXRhdjAhQoT','1a1c85a1-e619-45a8-a502-4a3f36bd95a5','2026-10-23T07:08:16.628544+00:00',NULL,NULL,NULL);
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
    expires_at   TEXT
);
INSERT INTO "mcp_tokens" VALUES('c05fc8a3-30bd-428a-bb97-24765f69d0b2','1a1c85a1-e619-45a8-a502-4a3f36bd95a5','laptop','6debc6','5f0d7db1ad3e444670090444b7fdfe25c045aed6cccc32d421325a91fe3e7c91','writer','2026-10-23T07:08:16.628515+00:00',NULL,NULL,NULL,NULL);
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
    used_at               TEXT
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
    UNIQUE (oidc_issuer, oidc_subject),
    UNIQUE (email)
);
INSERT INTO "users" VALUES('1a1c85a1-e619-45a8-a502-4a3f36bd95a5','human','ada@example.com','Ada','admin','active',NULL,NULL,'2026-10-23T07:08:16.628467+00:00',NULL,NULL);
CREATE INDEX mcp_tokens_user   ON mcp_tokens (user_id);
CREATE INDEX mcp_tokens_hash   ON mcp_tokens (hash);
CREATE INDEX mcp_tokens_client ON mcp_tokens (client_id);
CREATE INDEX oauth_codes_expiry ON oauth_codes (expires_at);
CREATE INDEX oauth_consents_expiry ON oauth_consents (expires_at);
COMMIT;
