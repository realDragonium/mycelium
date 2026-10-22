PRAGMA user_version = 0;
BEGIN TRANSACTION;
CREATE TABLE draft_ops (
    id           TEXT PRIMARY KEY,
    draft_id     TEXT NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
    seq          INTEGER NOT NULL,
    kind         TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    provenance_json TEXT,
    created_at   TEXT NOT NULL,
    created_by   TEXT,
    UNIQUE (draft_id, seq)
);
INSERT INTO "draft_ops" VALUES('op_feb22c3dea53','drf_d630d29df5d5',1,'upsert_statement','{"kind": "state", "text": "The account is unlocked.", "links": []}',NULL,'2026-10-22T18:23:42.208Z','local-admin');
CREATE TABLE drafts (
    id           TEXT PRIMARY KEY,
    title        TEXT,
    created_at   TEXT NOT NULL,
    created_by   TEXT,
    session_id   TEXT,
    submitted_at TEXT,
    decided_at   TEXT,
    decided_by   TEXT,
    decision     TEXT CHECK (decision IN ('approved', 'rejected', 'withdrawn'))
);
INSERT INTO "drafts" VALUES('drf_d630d29df5d5','Lockout','2026-10-22T18:23:42.208Z','local-admin','s1',NULL,NULL,NULL,NULL);
CREATE TABLE research_runs (
    id          TEXT PRIMARY KEY,
    topic       TEXT NOT NULL,
    source      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    created_by  TEXT,
    started_at  TEXT,
    finished_at TEXT,
    outcome     TEXT CHECK (outcome IN ('draft_created', 'nothing_found', 'failed')),
    draft_id    TEXT,
    error       TEXT,
    trace_ref   TEXT
);
INSERT INTO "research_runs" VALUES('rrn_89a4afdff903','Lockout','docs','2026-10-22T18:23:42.209Z','local-admin',NULL,'2026-10-22T18:23:42.209Z','draft_created','drf_d630d29df5d5',NULL,NULL);
CREATE INDEX drafts_session ON drafts (session_id);
CREATE INDEX drafts_creator ON drafts (created_by);
CREATE INDEX draft_ops_draft ON draft_ops (draft_id);
CREATE INDEX research_runs_created ON research_runs (created_at);
CREATE INDEX research_runs_active ON research_runs (started_at) WHERE finished_at IS NULL;
COMMIT;
