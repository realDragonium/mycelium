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
    error         TEXT,
    draft_title   TEXT,
    draft_body    TEXT,
    matched_document_id TEXT,
    provider      TEXT,
    model         TEXT
);
INSERT INTO "documentation_runs" VALUES('drn_9291100262f7','Explain sign-in',NULL,NULL,'2026-10-22T18:38:52.725Z','ada',NULL,'2026-10-22T18:38:52.725Z','document_written','gdc_b88ec5a8c1d8',NULL,NULL,NULL,NULL,NULL,NULL);
CREATE TABLE draft_applications (
    id             TEXT PRIMARY KEY,
    draft_id       TEXT NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
    review_id      TEXT NOT NULL REFERENCES draft_reviews(id),
    status         TEXT NOT NULL CHECK (status IN ('claimed', 'committed', 'failed')),
    claimed_at     TEXT NOT NULL,
    finished_at    TEXT,
    claimed_by     TEXT NOT NULL,
    result_json    TEXT,
    failure        TEXT
);
INSERT INTO "draft_applications" VALUES('app_f87f95ba2c1d','drf_149e3d43361e','rev_04fa98a150e6','committed','2026-10-22T18:38:52.723Z','2026-10-22T18:38:52.723Z','reviewer','{"applied": 1}',NULL);
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
INSERT INTO "draft_ops" VALUES('op_53e643e83354','drf_149e3d43361e',1,'upsert_statement','{"kind": "state", "text": "The account is unlocked.", "links": []}',NULL,'2026-10-22T18:38:52.723Z','local-admin');
CREATE TABLE draft_review_runs (
            id TEXT PRIMARY KEY,
            draft_id TEXT NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
            status TEXT NOT NULL,
            body_json TEXT NOT NULL
        );
INSERT INTO "draft_review_runs" VALUES('drv_0d5fc06751e1','drf_149e3d43361e','completed','{"run_id":"drv_0d5fc06751e1","draft_id":"drf_149e3d43361e","status":"completed","mode":"review-only","draft_revision":1,"provider":null,"model":null,"reviewer_id":null,"settings_revision":null,"model_settings_revision":null,"review_id":null,"stale":false,"knowledge_preconditions":[],"label":"good","rationale":"Fits the graph.","questions":[],"corrections":[],"application":"unapplied","detail":null,"started_at":"2026-10-22T18:38:52.723Z","finished_at":null}');
CREATE TABLE draft_reviews (
    id                 TEXT PRIMARY KEY,
    draft_id           TEXT NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
    outcome            TEXT NOT NULL CHECK (
        outcome IN ('accepted', 'refined', 'rejected', 'needs_context')
    ),
    rationale          TEXT NOT NULL,
    draft_revision     INTEGER NOT NULL,
    preconditions_json TEXT NOT NULL,
    unresolved_json    TEXT NOT NULL,
    reviewed_at        TEXT NOT NULL,
    reviewed_by        TEXT NOT NULL
);
INSERT INTO "draft_reviews" VALUES('rev_04fa98a150e6','drf_149e3d43361e','accepted','Consistent with existing knowledge.',1,'[]','[]','2026-10-22T18:38:52.723Z','reviewer');
CREATE TABLE drafts (
    id           TEXT PRIMARY KEY,
    title        TEXT,
    created_at   TEXT NOT NULL,
    created_by   TEXT,
    session_id   TEXT,
    revision     INTEGER NOT NULL DEFAULT 0,
    source_repository TEXT,
    source_pull_request INTEGER,
    source_merged_commit TEXT,
    source_workflow_run_id INTEGER,
    source_workflow_run_attempt INTEGER,
    submitted_at TEXT,
    decided_at   TEXT,
    decided_by   TEXT,
    decision     TEXT CHECK (decision IN ('approved', 'rejected', 'withdrawn'))
, review_assessment_json TEXT, review_evidence TEXT);
INSERT INTO "drafts" VALUES('drf_149e3d43361e','Lockout','2026-10-22T18:38:52.723Z','local-admin','s1',1,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'{"run_id":"drv_0d5fc06751e1","draft_id":"drf_149e3d43361e","status":"completed","mode":"review-only","draft_revision":1,"provider":null,"model":null,"reviewer_id":null,"settings_revision":null,"model_settings_revision":null,"review_id":null,"stale":false,"knowledge_preconditions":[],"label":"good","rationale":"Fits the graph.","questions":[],"corrections":[],"application":"unapplied","detail":null,"started_at":"2026-10-22T18:38:52.723Z","finished_at":null}',NULL);
CREATE TABLE generated_documents (
    id            TEXT PRIMARY KEY,
    slug          TEXT NOT NULL,
    title         TEXT NOT NULL,
    guideline_set TEXT NOT NULL DEFAULT '',
    document_type TEXT NOT NULL DEFAULT '',
    body          TEXT NOT NULL,
    statement_ids TEXT NOT NULL DEFAULT '[]',
    review        TEXT NOT NULL DEFAULT '{}',
    delivery_destination TEXT,
    delivery_target TEXT,
    delivery_path        TEXT,
    delivery_reference   TEXT,
    delivery_content_revision TEXT,
    revision_source_content_revision TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    last_run_id   TEXT
);
INSERT INTO "generated_documents" VALUES('gdc_b88ec5a8c1d8','sign-in','Sign-in','','','How to sign in.','[]','{}',NULL,NULL,NULL,NULL,NULL,NULL,'2026-10-22T18:38:52.725Z','2026-10-22T18:38:52.725Z','drn_9291100262f7');
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
INSERT INTO "research_runs" VALUES('rrn_f41c5284cdaf','Lockout','docs','2026-10-22T18:38:52.724Z','local-admin',NULL,'2026-10-22T18:38:52.724Z','draft_created','drf_149e3d43361e',NULL,NULL);
CREATE INDEX drafts_session ON drafts (session_id);
CREATE INDEX drafts_creator ON drafts (created_by);
CREATE INDEX draft_ops_draft ON draft_ops (draft_id);
CREATE TRIGGER draft_ops_revision_insert
AFTER INSERT ON draft_ops
BEGIN
    UPDATE drafts SET revision = revision + 1 WHERE id = NEW.draft_id;
END;
CREATE TRIGGER draft_ops_revision_update
AFTER UPDATE OF payload_json ON draft_ops
BEGIN
    UPDATE drafts SET revision = revision + 1 WHERE id = NEW.draft_id;
END;
CREATE TRIGGER draft_ops_revision_delete
AFTER DELETE ON draft_ops
BEGIN
    UPDATE drafts SET revision = revision + 1 WHERE id = OLD.draft_id;
END;
CREATE INDEX draft_reviews_draft ON draft_reviews (draft_id, reviewed_at);
CREATE UNIQUE INDEX draft_application_active
ON draft_applications (draft_id) WHERE status IN ('claimed', 'committed');
CREATE UNIQUE INDEX drafts_source ON drafts (created_by, source_repository, source_pull_request, source_merged_commit, source_workflow_run_id, source_workflow_run_attempt) WHERE source_repository IS NOT NULL;
CREATE UNIQUE INDEX draft_review_run_active
        ON draft_review_runs(draft_id) WHERE status = 'running';
CREATE INDEX research_runs_created ON research_runs (created_at);
CREATE INDEX research_runs_active ON research_runs (started_at) WHERE finished_at IS NULL;
CREATE INDEX documentation_runs_created ON documentation_runs (created_at);
CREATE INDEX documentation_runs_active ON documentation_runs (started_at) WHERE finished_at IS NULL;
CREATE INDEX generated_documents_updated ON generated_documents (updated_at);
CREATE UNIQUE INDEX generated_documents_identity
    ON generated_documents (guideline_set, document_type, slug);
COMMIT;
