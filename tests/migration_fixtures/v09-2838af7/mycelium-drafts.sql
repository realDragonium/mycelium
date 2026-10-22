PRAGMA user_version = 0;
BEGIN TRANSACTION;
CREATE TABLE documentation_runs (
    id            TEXT PRIMARY KEY,
    prompt        TEXT NOT NULL,
    guideline_set TEXT,
    document_type TEXT,
    created_at    TEXT NOT NULL,
    created_by    TEXT,
    started_at    TEXT,
    finished_at   TEXT,
    outcome       TEXT CHECK (outcome IN ('document_written', 'nothing_written', 'failed')),
    document_id   TEXT,
    error         TEXT
);
INSERT INTO "documentation_runs" VALUES('drn_c51e3b67da4d','Explain sign-in',NULL,NULL,'2026-10-22T18:23:46.376Z','ada',NULL,'2026-10-22T18:23:46.377Z','document_written','gdc_43bc971b0463',NULL);
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
INSERT INTO "draft_ops" VALUES('op_e06687402e35','drf_dcd6e6c03912',1,'upsert_statement','{"kind": "state", "text": "The account is unlocked.", "links": []}',NULL,'2026-10-22T18:23:46.375Z','local-admin');
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
INSERT INTO "drafts" VALUES('drf_dcd6e6c03912','Lockout','2026-10-22T18:23:46.375Z','local-admin','s1',NULL,NULL,NULL,NULL);
CREATE TABLE generated_documents (
    id            TEXT PRIMARY KEY,
    slug          TEXT NOT NULL,
    title         TEXT NOT NULL,
    guideline_set TEXT NOT NULL DEFAULT '',
    document_type TEXT NOT NULL DEFAULT '',
    body          TEXT NOT NULL,
    statement_ids TEXT NOT NULL DEFAULT '[]',
    review        TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    last_run_id   TEXT
);
INSERT INTO "generated_documents" VALUES('gdc_43bc971b0463','sign-in','Sign-in','','','How to sign in.','[]','{}','2026-10-22T18:23:46.376Z','2026-10-22T18:23:46.376Z','drn_c51e3b67da4d');
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
INSERT INTO "research_runs" VALUES('rrn_d3cd6b5311bb','Lockout','docs','2026-10-22T18:23:46.375Z','local-admin',NULL,'2026-10-22T18:23:46.376Z','draft_created','drf_dcd6e6c03912',NULL,NULL);
CREATE INDEX drafts_session ON drafts (session_id);
CREATE INDEX drafts_creator ON drafts (created_by);
CREATE INDEX draft_ops_draft ON draft_ops (draft_id);
CREATE INDEX research_runs_created ON research_runs (created_at);
CREATE INDEX research_runs_active ON research_runs (started_at) WHERE finished_at IS NULL;
CREATE INDEX documentation_runs_created ON documentation_runs (created_at);
CREATE INDEX documentation_runs_active ON documentation_runs (started_at) WHERE finished_at IS NULL;
CREATE INDEX generated_documents_updated ON generated_documents (updated_at);
CREATE UNIQUE INDEX generated_documents_identity
    ON generated_documents (guideline_set, document_type, slug);
COMMIT;
