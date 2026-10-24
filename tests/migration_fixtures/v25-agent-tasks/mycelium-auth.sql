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
INSERT INTO "invites" VALUES('f8b8dce9-e0df-45c4-a2ce-128b2b052737','bea@example.com','writer','BW_0-OR6FRNtZOHqTvIWXgdsu00CU7US','47d4acb7-011e-4708-beca-b29a42edb417','2026-10-24T08:34:26.980710+00:00',NULL,NULL,NULL);
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
INSERT INTO "mcp_tokens" VALUES('cc72cae7-033d-489a-aedc-bcae5c21c1c5','47d4acb7-011e-4708-beca-b29a42edb417','laptop','9f44ae','885f0658dbc651e7bcb48cc9ad77aeb362fb25215f5af6e3ad3c746555b87d29','writer','2026-10-24T08:34:26.980681+00:00',NULL,NULL,NULL,NULL,NULL);
INSERT INTO "mcp_tokens" VALUES('2674975d-7d8d-40e0-929a-dcb155ac1887','47d4acb7-011e-4708-beca-b29a42edb417','OAuth: Claude','98b545','78792ecad2733ea55ebf00eac6548ba44edb9ca660a5a1d5d3d98b018dc57203','admin','2026-10-24T08:34:26.980782+00:00',NULL,NULL,'client-1','2026-08-01T01:00:00+00:00',NULL);
INSERT INTO "mcp_tokens" VALUES('b38be172-31b5-4536-9e52-d73bcacacb7b','47d4acb7-011e-4708-beca-b29a42edb417','external','3fafdf','2017a2644a5a34d5faddf2b1e342806c252759340c09ef0d9460e726810f4ba4','reader','2026-10-24T08:34:26.980844+00:00',NULL,NULL,NULL,NULL,'external-technical');
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
INSERT INTO "oauth_refresh_tokens" VALUES('e70c89db5c853604405bce9ee77e86161aa3daa3bae38cdd6d7cc12d6ee2a87e','2674975d-7d8d-40e0-929a-dcb155ac1887','2026-08-01T00:00:00+00:00','2026-08-31T00:00:00+00:00',NULL);
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
INSERT INTO "users" VALUES('47d4acb7-011e-4708-beca-b29a42edb417','human','ada@example.com','Ada','admin','active',NULL,NULL,'2026-10-24T08:34:26.980638+00:00',NULL,NULL,NULL);
CREATE INDEX mcp_tokens_user   ON mcp_tokens (user_id);
CREATE INDEX mcp_tokens_hash   ON mcp_tokens (hash);
CREATE INDEX mcp_tokens_client ON mcp_tokens (client_id);
CREATE INDEX oauth_refresh_tokens_token ON oauth_refresh_tokens (token_id);
CREATE INDEX oauth_codes_expiry ON oauth_codes (expires_at);
CREATE INDEX oauth_consents_expiry ON oauth_consents (expires_at);
COMMIT;
