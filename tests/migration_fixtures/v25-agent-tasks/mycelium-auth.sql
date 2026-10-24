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
INSERT INTO "invites" VALUES('6c2f41cd-430e-483b-9386-8fc53440a2d1','bea@example.com','writer','jdBp9wG2CmpIsLt-FTewkoixjENnI4N6','c02f6601-6ba4-4dca-8fa1-f8edf691245f','2026-10-24T08:53:26.278046+00:00',NULL,NULL,NULL);
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
INSERT INTO "mcp_tokens" VALUES('1da5057b-95da-4953-978b-cf46aaf0d141','c02f6601-6ba4-4dca-8fa1-f8edf691245f','laptop','de2375','265941499b363e6efaccb236adc0f05df3a74a6b94584bfc7cd44211a15bb788','writer','2026-10-24T08:53:26.277983+00:00',NULL,NULL,NULL,NULL,NULL);
INSERT INTO "mcp_tokens" VALUES('98e2c952-d1a8-483b-80ca-a0ccedfe54b5','c02f6601-6ba4-4dca-8fa1-f8edf691245f','OAuth: Claude','bde21a','082e6ef95251f424c3ec095b5999167c82c3f1e19b7758b6c585d9cb7aad5dcb','admin','2026-10-24T08:53:26.278178+00:00',NULL,NULL,'client-1','2026-08-01T01:00:00+00:00',NULL);
INSERT INTO "mcp_tokens" VALUES('2ef09024-4d9e-4be1-8ff8-511d179e8118','c02f6601-6ba4-4dca-8fa1-f8edf691245f','external','98ec3b','8ecd547f692b395307a0f7688dc5e49cc682a23b0d0e6d7deabad47072100224','reader','2026-10-24T08:53:26.278309+00:00',NULL,NULL,NULL,NULL,'external-technical');
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
INSERT INTO "oauth_refresh_tokens" VALUES('e70c89db5c853604405bce9ee77e86161aa3daa3bae38cdd6d7cc12d6ee2a87e','98e2c952-d1a8-483b-80ca-a0ccedfe54b5','2026-08-01T00:00:00+00:00','2026-08-31T00:00:00+00:00',NULL);
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
INSERT INTO "users" VALUES('c02f6601-6ba4-4dca-8fa1-f8edf691245f','human','ada@example.com','Ada','admin','active',NULL,NULL,'2026-10-24T08:53:26.277880+00:00',NULL,NULL,NULL);
CREATE INDEX mcp_tokens_user   ON mcp_tokens (user_id);
CREATE INDEX mcp_tokens_hash   ON mcp_tokens (hash);
CREATE INDEX mcp_tokens_client ON mcp_tokens (client_id);
CREATE INDEX oauth_refresh_tokens_token ON oauth_refresh_tokens (token_id);
CREATE INDEX oauth_codes_expiry ON oauth_codes (expires_at);
CREATE INDEX oauth_consents_expiry ON oauth_consents (expires_at);
COMMIT;
