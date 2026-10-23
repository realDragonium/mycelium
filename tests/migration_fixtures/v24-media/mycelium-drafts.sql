PRAGMA user_version = 0;
BEGIN TRANSACTION;
CREATE TABLE ai_usage (
    id                 INTEGER PRIMARY KEY,
    at                 TEXT NOT NULL,
    action             TEXT NOT NULL,
    provider           TEXT NOT NULL,
    model              TEXT NOT NULL,
    input_tokens       INTEGER NOT NULL,
    cached_tokens      INTEGER NOT NULL,
    cache_write_tokens INTEGER NOT NULL,
    output_tokens      INTEGER NOT NULL,
    cost_usd           REAL,
    duration_ms        INTEGER NOT NULL,
    ok                 INTEGER NOT NULL,
    run_id             TEXT,
    draft_id           TEXT
);
INSERT INTO "ai_usage" VALUES(1,'2026-10-23T19:22:31.792Z','draft_review','claude','claude-sonnet-5-5',1200,0,0,300,0.0054,4100,1,NULL,'drf_4c0825ce1cf7');
CREATE TABLE document_maintenance (
    document_id   TEXT NOT NULL,
    revision      INTEGER NOT NULL,
    guideline_set TEXT NOT NULL,
    changes       TEXT NOT NULL,
    changed_at    TEXT NOT NULL,
    action        TEXT CHECK (action IN ('propose', 'auto-revise')),
    acted_at      TEXT,
    run_id        TEXT,
    error         TEXT,
    delivery      TEXT CHECK (delivery IN ('none', 'publishing', 'published', 'failed')),
    PRIMARY KEY (document_id, revision)
);
INSERT INTO "document_maintenance" VALUES('gdc_c567e6a356c3',1,'kb-authoring','[]','2026-01-01T00:00:00.000Z','auto-revise','2026-01-01T00:30:00.000Z','drn_12cd1b0b2ab0',NULL,'published');
CREATE TABLE documentation_plan_dismissals (
    guideline_set TEXT NOT NULL,
    key           TEXT NOT NULL,
    title         TEXT NOT NULL,
    dismissed_at  TEXT NOT NULL,
    dismissed_by  TEXT,
    PRIMARY KEY (guideline_set, key)
);
INSERT INTO "documentation_plan_dismissals" VALUES('kb-authoring','create:reference:title:sso','SSO','2026-10-23T19:22:31.793Z','ada');
CREATE TABLE documentation_plan_items (
    id                TEXT PRIMARY KEY,
    plan_id           TEXT NOT NULL REFERENCES documentation_plans(id),
    position          INTEGER NOT NULL,
    key               TEXT NOT NULL,
    action            TEXT NOT NULL CHECK (action IN ('create', 'update')),
    title             TEXT NOT NULL,
    document_type     TEXT NOT NULL,
    anchor_entity_id  TEXT,
    document_id       TEXT,
    rationale         TEXT NOT NULL,
    priority          TEXT NOT NULL CHECK (priority IN ('high', 'medium', 'low')),
    statement_ids     TEXT NOT NULL,
    state             TEXT NOT NULL DEFAULT 'proposed'
                      CHECK (state IN ('proposed', 'approved', 'dismissed')),
    decided_at        TEXT,
    decided_by        TEXT,
    run_id            TEXT
);
INSERT INTO "documentation_plan_items" VALUES('dpi_6c70311a564d4da4','dpl_f38e67a3d9fd40c3',0,'create:how-to:title:reset-a-password','create','Reset a password','how-to',NULL,NULL,'Users forget passwords.','high','["stm_sign_in"]','approved','2026-10-23T19:22:31.793Z','ada','drn_12cd1b0b2ab0');
CREATE TABLE documentation_plans (
    id            TEXT PRIMARY KEY,
    guideline_set TEXT NOT NULL,
    audience_id   TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    created_by    TEXT,
    finished_at   TEXT,
    outcome       TEXT CHECK (outcome IN ('planned', 'failed')),
    error         TEXT,
    activity      TEXT,
    provider      TEXT,
    model         TEXT,
    summary       TEXT
, kind TEXT NOT NULL DEFAULT 'model' CHECK (kind IN ('model', 'maintenance')));
INSERT INTO "documentation_plans" VALUES('dpl_f38e67a3d9fd40c3','kb-authoring','external-technical','2026-10-23T19:22:31.793Z','ada','2026-10-23T19:22:31.793Z','planned',NULL,NULL,'claude','claude-sonnet-4-6','{"cost_usd": 0.01}','model');
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
, reasoning_effort TEXT, target_document_id TEXT, target_revision INTEGER, result_revision INTEGER, profile_revisions TEXT NOT NULL DEFAULT '{}', profile_snapshot TEXT NOT NULL DEFAULT '{}', review_notes TEXT, anchor_entity_id TEXT, revision_base TEXT CHECK (revision_base IN ('internal', 'destination')), summary TEXT);
INSERT INTO "documentation_runs" VALUES('drn_12cd1b0b2ab0','Explain sign-in',NULL,NULL,'2026-10-23T19:22:31.792Z','ada',NULL,'2026-10-23T19:22:31.793Z','document_written','gdc_c567e6a356c3',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,1,'{}','{}',NULL,NULL,NULL,NULL);
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
INSERT INTO "draft_applications" VALUES('app_80267e4c215e','drf_4c0825ce1cf7','rev_a7c74e9eb5f8','committed','2026-10-23T19:22:31.791Z','2026-10-23T19:22:31.791Z','reviewer','{"applied": 1}',NULL);
CREATE TABLE draft_ops (
    id           TEXT PRIMARY KEY,
    draft_id     TEXT NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
    seq          INTEGER NOT NULL,
    kind         TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    provenance_json TEXT,
    evidence_json TEXT,
    created_at   TEXT NOT NULL,
    created_by   TEXT,
    UNIQUE (draft_id, seq)
);
INSERT INTO "draft_ops" VALUES('op_b1273c8be063','drf_4c0825ce1cf7',1,'upsert_statement','{"kind": "state", "text": "The account is unlocked.", "links": []}',NULL,NULL,'2026-10-23T19:22:31.789Z','local-admin');
CREATE TABLE draft_review_runs (
            id TEXT PRIMARY KEY,
            draft_id TEXT NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
            status TEXT NOT NULL,
            body_json TEXT NOT NULL
        );
INSERT INTO "draft_review_runs" VALUES('drv_abb5b6090540','drf_4c0825ce1cf7','completed','{"run_id":"drv_abb5b6090540","draft_id":"drf_4c0825ce1cf7","status":"completed","mode":"review-only","draft_revision":1,"provider":null,"model":null,"prompt":null,"reasoning_effort":null,"reviewer_id":null,"settings_revision":null,"model_settings_revision":null,"review_id":null,"stale":false,"knowledge_preconditions":[],"label":"good","rationale":"Fits the graph.","questions":[],"corrections":[],"contradictions":[],"attempt":1,"retries":0,"previous_failure":null,"answers":[],"application":"unapplied","detail":null,"started_at":"2026-10-23T19:22:31.791Z","finished_at":null}');
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
INSERT INTO "draft_reviews" VALUES('rev_a7c74e9eb5f8','drf_4c0825ce1cf7','accepted','Consistent with existing knowledge.',1,'[]','[]','2026-10-23T19:22:31.791Z','reviewer');
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
INSERT INTO "drafts" VALUES('drf_4c0825ce1cf7','Lockout','2026-10-23T19:22:31.789Z','local-admin','s1',1,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'{"run_id":"drv_abb5b6090540","draft_id":"drf_4c0825ce1cf7","status":"completed","mode":"review-only","draft_revision":1,"provider":null,"model":null,"prompt":null,"reasoning_effort":null,"reviewer_id":null,"settings_revision":null,"model_settings_revision":null,"review_id":null,"stale":false,"knowledge_preconditions":[],"label":"good","rationale":"Fits the graph.","questions":[],"corrections":[],"contradictions":[],"attempt":1,"retries":0,"previous_failure":null,"answers":[],"application":"unapplied","detail":null,"started_at":"2026-10-23T19:22:31.791Z","finished_at":null}',NULL);
CREATE TABLE generated_document_deliveries (
    document_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    destination TEXT NOT NULL,
    binding TEXT,
    target TEXT NOT NULL,
    path TEXT NOT NULL,
    reference TEXT NOT NULL,
    content_revision TEXT NOT NULL,
    created_at TEXT,
    PRIMARY KEY (document_id, revision)
);
INSERT INTO "generated_document_deliveries" VALUES('gdc_c567e6a356c3',1,'docs','approved','{"host": "github.com", "owner": "example", "repo": "docs", "base_branch": "main"}','docs/sign-in.md','https://github.com/example/docs/pull/1','sha','2026-10-23T19:22:31.793Z');
CREATE TABLE generated_document_revisions (
    document_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    parent_revision INTEGER,
    slug TEXT NOT NULL,
    title TEXT NOT NULL,
    guideline_set TEXT NOT NULL,
    document_type TEXT NOT NULL,
    body TEXT NOT NULL,
    statement_ids TEXT NOT NULL,
    review TEXT NOT NULL,
    created_at TEXT NOT NULL,
    run_id TEXT, cited_statements TEXT,
    PRIMARY KEY (document_id, revision)
);
INSERT INTO "generated_document_revisions" VALUES('gdc_c567e6a356c3',1,NULL,'sign-in','Sign-in','','','How to sign in.','[]','{}','2026-10-23T19:22:31.792Z','drn_12cd1b0b2ab0','{"stm_sign_in": "A user signs in."}');
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
, current_revision INTEGER NOT NULL DEFAULT 1, published_revision INTEGER, delivery_binding TEXT, anchor_entity_id TEXT, pull_request_number INTEGER, pull_request_state TEXT CHECK (pull_request_state IN ('open', 'merged', 'closed')), pull_request_refreshed_at TEXT);
INSERT INTO "generated_documents" VALUES('gdc_c567e6a356c3','sign-in','Sign-in','','','How to sign in.','[]','{}','docs','{"host": "github.com", "owner": "example", "repo": "docs", "base_branch": "main"}','docs/sign-in.md','https://github.com/example/docs/pull/1','sha',NULL,'2026-10-23T19:22:31.792Z','2026-10-23T19:22:31.792Z','drn_12cd1b0b2ab0',1,1,'approved',NULL,1,'open','2026-10-23T19:22:31.793Z');
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
CREATE INDEX ai_usage_at ON ai_usage(at);
CREATE INDEX documentation_runs_created ON documentation_runs (created_at);
CREATE INDEX documentation_runs_active ON documentation_runs (started_at) WHERE finished_at IS NULL;
CREATE INDEX generated_documents_updated ON generated_documents (updated_at);
CREATE UNIQUE INDEX generated_documents_identity
    ON generated_documents (guideline_set, document_type, slug);
CREATE UNIQUE INDEX generated_documents_anchor ON generated_documents (guideline_set, document_type, anchor_entity_id) WHERE anchor_entity_id IS NOT NULL;
CREATE INDEX documentation_plans_profile
    ON documentation_plans (guideline_set, created_at);
CREATE INDEX documentation_plan_items_plan
    ON documentation_plan_items (plan_id, position);
CREATE INDEX document_maintenance_acted
    ON document_maintenance (guideline_set, acted_at);
COMMIT;
