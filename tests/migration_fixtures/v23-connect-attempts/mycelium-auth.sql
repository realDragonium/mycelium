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
INSERT INTO "invites" VALUES('c426d65a-7c81-4d94-ad9b-a3b10bb49434','bea@example.com','writer','2tsi4qGyLFHBCBWbqsqtM9A8LpMB3-YS','f62ce633-8498-4b2b-9538-6ec35c6bf91f','2026-10-23T16:53:02.440904+00:00',NULL,NULL,NULL);
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
INSERT INTO "mcp_tokens" VALUES('2ffedf88-6d87-4ee2-84d1-f4d05aa83aa1','f62ce633-8498-4b2b-9538-6ec35c6bf91f','laptop','c5bc57','52232b957c30a456821f565f43443b4bace64f6fc33937cfa4ac2bde7310ed76','writer','2026-10-23T16:53:02.440877+00:00',NULL,NULL,NULL,NULL,NULL);
INSERT INTO "mcp_tokens" VALUES('f6a9315f-338d-432d-98d5-099a53a90cef','f62ce633-8498-4b2b-9538-6ec35c6bf91f','OAuth: Claude','4c7fb6','d237661761d76c0fb531ede53a10fc40f7d39f31a246f4df8ea30180411c4202','admin','2026-10-23T16:53:02.440949+00:00',NULL,NULL,'client-1','2026-08-01T01:00:00+00:00',NULL);
INSERT INTO "mcp_tokens" VALUES('b65f8168-2d2c-4067-a9b3-c34fca615d19','f62ce633-8498-4b2b-9538-6ec35c6bf91f','external','daef92','21923eeef5b8354e21a553f5ab88abc617286011217d0775e887cd12fb1f11fe','reader','2026-10-23T16:53:02.440992+00:00',NULL,NULL,NULL,NULL,'external-technical');
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
INSERT INTO "oauth_refresh_tokens" VALUES('e70c89db5c853604405bce9ee77e86161aa3daa3bae38cdd6d7cc12d6ee2a87e','f6a9315f-338d-432d-98d5-099a53a90cef','2026-08-01T00:00:00+00:00','2026-08-31T00:00:00+00:00',NULL);
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
INSERT INTO "users" VALUES('f62ce633-8498-4b2b-9538-6ec35c6bf91f','human','ada@example.com','Ada','admin','active',NULL,NULL,'2026-10-23T16:53:02.440835+00:00',NULL,NULL,NULL);
CREATE INDEX mcp_tokens_user   ON mcp_tokens (user_id);
CREATE INDEX mcp_tokens_hash   ON mcp_tokens (hash);
CREATE INDEX mcp_tokens_client ON mcp_tokens (client_id);
CREATE INDEX oauth_refresh_tokens_token ON oauth_refresh_tokens (token_id);
CREATE INDEX oauth_codes_expiry ON oauth_codes (expires_at);
CREATE INDEX oauth_consents_expiry ON oauth_consents (expires_at);
COMMIT;
