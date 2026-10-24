PRAGMA user_version = 26;
BEGIN TRANSACTION;
CREATE TABLE audience_label_queue (
    statement_id    TEXT PRIMARY KEY REFERENCES statements(id) ON DELETE CASCADE,
    enqueued_at     TEXT NOT NULL,
    attempts        INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    last_error      TEXT,
    previous        TEXT,
    backfill        INTEGER NOT NULL DEFAULT 0
);
INSERT INTO "audience_label_queue" VALUES('stm_af54f18e7cf14d0ba315f2f7bc4d5f13','2026-10-24T15:36:57.054Z',0,NULL,NULL,NULL,0);
INSERT INTO "audience_label_queue" VALUES('stm_c24d1293af5c414eb1e5b9e2fa9d2d5c','2026-10-24T15:36:57.054Z',0,NULL,NULL,NULL,0);
INSERT INTO "audience_label_queue" VALUES('stm_89e80a3bc3fd4aefaa85eaf9b4247d13','2026-10-24T15:36:57.055Z',0,NULL,NULL,'{"text": "The account is disabled.", "audiences": ["external-non-technical"], "reason": "Users see this.", "confirmed": {"external-non-technical": {"decision": "confirmed", "by": "curator", "at": "2026-08-02T00:00:00Z"}}, "confirmed_text": "The account is disabled."}',0);
INSERT INTO "audience_label_queue" VALUES('stm_e968363433f142c1a711a1e97828fdd7','2026-10-24T15:36:57.055Z',0,NULL,NULL,NULL,0);
CREATE TABLE curation_attempts (
    item_id      TEXT PRIMARY KEY,
    text         TEXT NOT NULL,
    neighbours   TEXT NOT NULL,
    attempted_at TEXT NOT NULL,
    attempted_by TEXT,
    outcome      TEXT NOT NULL
        CHECK (outcome IN ('looked', 'proposed', 'no_link', 'skipped')),
    reason       TEXT,
    draft_id     TEXT
);
INSERT INTO "curation_attempts" VALUES('stm_af54f18e7cf14d0ba315f2f7bc4d5f13','A user submits the Login form.','["stm_e968363433f142c1a711a1e97828fdd7"]','2026-08-01T00:00:00Z','scenario-agent','no_link','Nothing in the code relates it.',NULL);
CREATE TABLE curation_claims (
    item_id    TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,
    neighbours TEXT NOT NULL,
    claimed_by TEXT NOT NULL,
    claimed_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE entities (
    id          TEXT PRIMARY KEY,
    description TEXT,
    preferred_name_id TEXT REFERENCES names(id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED,
    created_at  TEXT,
    updated_at  TEXT,
    created_by  TEXT,
    updated_by  TEXT
);
INSERT INTO "entities" VALUES('ent_ea882c2718e545d1b3a17eae2ef5c2b9','Signing in.','nam_6a7d5c6bf63e4f88a178fe08548fb8f5','2026-10-24T15:36:57.050Z','2026-10-24T15:36:57.050Z',NULL,NULL);
INSERT INTO "entities" VALUES('ent_8f8528aea47945e5803a0ec06d7896d7','An authenticated visit.','nam_5d779d2255e045ceb4c06aa7d6fbd915','2026-10-24T15:36:57.051Z','2026-10-24T15:36:57.052Z',NULL,NULL);
CREATE TABLE entity_duplicate_dismissals (
    a_entity_id  TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    b_entity_id  TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    dismissed_at TEXT NOT NULL,
    dismissed_by TEXT,
    PRIMARY KEY (a_entity_id, b_entity_id),
    CHECK (a_entity_id < b_entity_id)
);
INSERT INTO "entity_duplicate_dismissals" VALUES('ent_8f8528aea47945e5803a0ec06d7896d7','ent_ea882c2718e545d1b3a17eae2ef5c2b9','2026-08-01',NULL);
CREATE TABLE entity_link_type_glossary (
    link_type   TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    created_at  TEXT,
    updated_at  TEXT,
    created_by  TEXT,
    updated_by  TEXT
);
INSERT INTO "entity_link_type_glossary" VALUES('contains','Parent → member. Structural composition between long-lived entities (e.g. parent corp → subsidiary, category → member). Same top-down direction as statement links: parent is the source.','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "entity_link_type_glossary" VALUES('replaces','Source entity supersedes target entity (e.g. one provider replacing another).','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "entity_link_type_glossary" VALUES('sub-type','Source is a specialization of target. Reads ''source is a sub-type of target'' (e.g. SAML SSO is a sub-type of Authentication method, Admin is a sub-type of User role). Parent / general category at the target end.','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "entity_link_type_glossary" VALUES('has','Source has the target as a component, attribute, or related object. Generic ownership/composition relation between long-lived entities when neither `contains` (strict structural membership) nor `sub-type` (specialization) fits.','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "entity_link_type_glossary" VALUES('uses','Source depends on or makes use of target. Behavioural dependency between long-lived entities — distinct from structural composition (`contains`) and specialization (`sub-type`).','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
CREATE TABLE entity_links (
    from_entity_id TEXT NOT NULL REFERENCES entities(id),
    to_entity_id   TEXT NOT NULL REFERENCES entities(id),
    link_type      TEXT NOT NULL,
    created_at     TEXT,
    created_by     TEXT,
    PRIMARY KEY (from_entity_id, to_entity_id, link_type)
);
INSERT INTO "entity_links" VALUES('ent_ea882c2718e545d1b3a17eae2ef5c2b9','ent_8f8528aea47945e5803a0ec06d7896d7','contains','2026-10-24T15:36:57.053Z',NULL);
CREATE TABLE knowledge_gaps (
    id           TEXT PRIMARY KEY,
    text         TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    created_by   TEXT,
    resolved_at  TEXT,
    resolved_by  TEXT,
    dismissed_at TEXT,
    dismissed_by TEXT,
    draft_id     TEXT,
    statement_id TEXT,
    document_id  TEXT,
    CHECK (resolved_at IS NULL OR dismissed_at IS NULL)
);
INSERT INTO "knowledge_gaps" VALUES('1478459e-eeab-4d29-a9db-515a4fcdb52e','How long does a locked account stay locked?','2026-10-24T15:36:57.056Z',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);
INSERT INTO "knowledge_gaps" VALUES('b2cbfded-52e4-4576-a7d5-384221c55f84','Draft drf_fixture contradicted the session expiry rule.','2026-10-24T15:36:57.056Z',NULL,NULL,NULL,NULL,NULL,'drf_fixture','stm_e968363433f142c1a711a1e97828fdd7',NULL);
CREATE TABLE link_type_aliases (
    link_type   TEXT NOT NULL,
    alias       TEXT NOT NULL,
    provenance  TEXT NOT NULL DEFAULT 'seed',
    score       REAL,
    -- 'forward' reads the edge off the alias left to right ("A contains B");
    -- 'reverse' aliases name the relation from the far side ("A is part of B").
    direction   TEXT NOT NULL DEFAULT 'forward',
    created_at  TEXT,
    created_by  TEXT,
    PRIMARY KEY (link_type, alias)
);
INSERT INTO "link_type_aliases" VALUES('contains','contains','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('contains','includes','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('contains','comprises','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('contains','consists of','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('contains','is made up of','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('contains','is part of','seed',NULL,'reverse','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('contains','belongs to','seed',NULL,'reverse','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('contains','is owned by','seed',NULL,'reverse','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('triggers','triggers','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('triggers','fires','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('triggers','kicks off','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('triggers','causes','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('triggers','results in','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('triggers','leads to','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('establishes','establishes','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('establishes','marks','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('establishes','sets','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('establishes','becomes','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('establishes','transitions to','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('enables','enables','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('enables','unlocks','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('enables','allows','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('enables','permits','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('enables','makes available','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('enables','is enabled by','seed',NULL,'reverse','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('enables','is unlocked by','seed',NULL,'reverse','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('requires','requires','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('requires','needs','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('requires','must have','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('requires','is required for','seed',NULL,'reverse','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('accepts','accepts','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('accepts','optionally','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('accepts','may include','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('accepts','may provide','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('varies-by','varies by','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('varies-by','varies with','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('varies-by','varies per','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('varies-by','differs by','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('varies-by','depends on','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('configures','configures','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('configures','configured','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('configures','set','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('configures','adjusted','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('configures','customised','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('configures','customized','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('configures','toggled','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('replaces','replaces','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('replaces','overrides','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('replaces','takes precedence over','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('replaces','instead of','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('replaces','in place of','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('restricts','restricts','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('restricts','limit','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('restricts','limits','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('restricts','disabled','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('restricts','locked','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('restricts','frozen','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('restricts','suspended','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('restricts','read-only','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('restricts','is limited by','seed',NULL,'reverse','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('restricts','is bounded by','seed',NULL,'reverse','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('restricts','is locked by','seed',NULL,'reverse','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('restricts','is capped by','seed',NULL,'reverse','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('restricts','is disabled by','seed',NULL,'reverse','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('restricts','is frozen by','seed',NULL,'reverse','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('restricts','is suspended by','seed',NULL,'reverse','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('proceeds','proceeds to','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('proceeds','then','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('proceeds','and then','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('proceeds','afterwards','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('proceeds','hands off to','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('proceeds','is followed by','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('proceeds','redirected','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('proceeds','routed','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('proceeds','forwarded','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('proceeds','returned','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('fallback-to','falls back to','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('fallback-to','fallback to','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('fallback-to','otherwise','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('fallback-to','defaults to','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('governed-by','is governed by','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('governed-by','according to','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('governed-by','subject to','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('governed-by','as defined by','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('composes','composes','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('composes','equal','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('composes','equals','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('composes','plus','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('composes','minus','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('composes','multiplied by','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('composes','divided by','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('composes','times','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('composes','sum of','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('composes','product of','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('composes','difference of','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('composes','difference between','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('cases','is one of','seed',NULL,'reverse','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('cases','either','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('cases','any of','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('valued-by','is derived from','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('valued-by','is computed from','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('valued-by','is determined by','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('supersedes','supersedes','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('supersedes','deprecates','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('teaches','teaches','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('teaches','how to','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('performs','performs','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('performs','carries out','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('verifies','verifies','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('verifies','checks','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('verifies','inspects','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('violates','violates','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('violates','is missing','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('violates','is not set','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('obtained-by','obtained by','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('obtained-by','found by','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('next','next','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('next','followed by','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('on-success','on success','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('on-success','if successful','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('on-failure','on failure','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('on-failure','if it fails','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('confirms','confirms','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('confirms','indicates','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('confirms','means','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('refutes','refutes','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('refutes','rules out','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('resolves','resolves','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('resolves','fixes','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('resolves','to fix','seed',NULL,'forward','2026-10-24T15:36:56.919Z',NULL);
INSERT INTO "link_type_aliases" VALUES('triggers','sets off','curator',NULL,'forward','2026-10-24T15:36:57.056Z',NULL);
CREATE TABLE mention_recompute_queue (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    statement_id TEXT REFERENCES statements(id),
    scan_text    TEXT,
    enqueued_at  TEXT NOT NULL,
    claimed_at   TEXT,
    CHECK ((statement_id IS NULL) <> (scan_text IS NULL))
);
INSERT INTO "mention_recompute_queue" VALUES(1,NULL,'Login','2026-10-24T15:36:57.051Z',NULL);
INSERT INTO "mention_recompute_queue" VALUES(2,NULL,'Logins','2026-10-24T15:36:57.051Z',NULL);
INSERT INTO "mention_recompute_queue" VALUES(3,NULL,'Session','2026-10-24T15:36:57.052Z',NULL);
INSERT INTO "mention_recompute_queue" VALUES(4,NULL,'Sessions','2026-10-24T15:36:57.052Z',NULL);
INSERT INTO "mention_recompute_queue" VALUES(5,NULL,'Sign-in','2026-10-24T15:36:57.053Z',NULL);
INSERT INTO "mention_recompute_queue" VALUES(6,NULL,'Sign-ins','2026-10-24T15:36:57.053Z',NULL);
INSERT INTO "mention_recompute_queue" VALUES(7,NULL,'sign-in','2026-08-01T00:00:00Z',NULL);
CREATE TABLE name_vector_ids (
    name_id   TEXT PRIMARY KEY REFERENCES names(id),
    vector_id INTEGER NOT NULL UNIQUE
);
INSERT INTO "name_vector_ids" VALUES('nam_6a7d5c6bf63e4f88a178fe08548fb8f5',0);
INSERT INTO "name_vector_ids" VALUES('nam_450be5264bcb4424869c57a9b0d07930',1);
INSERT INTO "name_vector_ids" VALUES('nam_5d779d2255e045ceb4c06aa7d6fbd915',2);
INSERT INTO "name_vector_ids" VALUES('nam_ee3f9b744894424da6df1d2e0432435d',3);
INSERT INTO "name_vector_ids" VALUES('nam_3a1eafc63b9a42dc80dffff840488878',4);
INSERT INTO "name_vector_ids" VALUES('nam_93d841c991664575b35f4e61a1320f80',5);
CREATE TABLE names (
    id         TEXT PRIMARY KEY,
    text       TEXT NOT NULL COLLATE NOCASE UNIQUE,
    entity_id  TEXT NOT NULL REFERENCES entities(id),
    generated_from_name_id TEXT REFERENCES names(id),
    created_at TEXT,
    updated_at TEXT,
    created_by TEXT,
    updated_by TEXT
);
INSERT INTO "names" VALUES('nam_6a7d5c6bf63e4f88a178fe08548fb8f5','Login','ent_ea882c2718e545d1b3a17eae2ef5c2b9',NULL,'2026-10-24T15:36:57.050Z',NULL,NULL,NULL);
INSERT INTO "names" VALUES('nam_450be5264bcb4424869c57a9b0d07930','Logins','ent_ea882c2718e545d1b3a17eae2ef5c2b9','nam_6a7d5c6bf63e4f88a178fe08548fb8f5','2026-10-24T15:36:57.051Z',NULL,NULL,NULL);
INSERT INTO "names" VALUES('nam_5d779d2255e045ceb4c06aa7d6fbd915','Session','ent_8f8528aea47945e5803a0ec06d7896d7',NULL,'2026-10-24T15:36:57.051Z',NULL,NULL,NULL);
INSERT INTO "names" VALUES('nam_ee3f9b744894424da6df1d2e0432435d','Sessions','ent_8f8528aea47945e5803a0ec06d7896d7','nam_5d779d2255e045ceb4c06aa7d6fbd915','2026-10-24T15:36:57.052Z',NULL,NULL,NULL);
INSERT INTO "names" VALUES('nam_3a1eafc63b9a42dc80dffff840488878','Sign-in','ent_ea882c2718e545d1b3a17eae2ef5c2b9',NULL,'2026-10-24T15:36:57.053Z',NULL,NULL,NULL);
INSERT INTO "names" VALUES('nam_93d841c991664575b35f4e61a1320f80','Sign-ins','ent_ea882c2718e545d1b3a17eae2ef5c2b9','nam_3a1eafc63b9a42dc80dffff840488878','2026-10-24T15:36:57.053Z',NULL,NULL,NULL);
CREATE TABLE pending_mentions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    statement_id TEXT NOT NULL REFERENCES statements(id),
    name_id      TEXT NOT NULL REFERENCES names(id),
    created_at   TEXT NOT NULL,
    approved_at  TEXT,
    approved_by  TEXT,
    rejected_at  TEXT,
    rejected_by  TEXT,
    UNIQUE (statement_id, name_id),
    CHECK (approved_at IS NULL OR rejected_at IS NULL)
);
INSERT INTO "pending_mentions" VALUES(1,'stm_af54f18e7cf14d0ba315f2f7bc4d5f13','nam_3a1eafc63b9a42dc80dffff840488878','2026-08-01','2026-08-01','curator',NULL,NULL);
CREATE TABLE reviewed_draft_applications (
    application_id TEXT PRIMARY KEY,
    draft_id       TEXT NOT NULL,
    review_id      TEXT NOT NULL,
    committed_at   TEXT NOT NULL,
    result_json    TEXT NOT NULL
);
INSERT INTO "reviewed_draft_applications" VALUES('app_scenario','drf_scenario','rev_scenario','2026-08-01T00:00:00Z','{}');
CREATE TABLE statement_audience_labels (
    statement_id    TEXT PRIMARY KEY REFERENCES statements(id) ON DELETE CASCADE,
    audiences       TEXT NOT NULL,
    source          TEXT NOT NULL CHECK (source IN ('ai', 'curator')),
    reason          TEXT NOT NULL,
    model           TEXT,
    cost_usd        REAL,
    labelled_at     TEXT NOT NULL,
    labelled_by     TEXT,
    text_changed_at TEXT,
    pending         TEXT,
    decisions       TEXT,
    narrowed        TEXT,
    kept_on_edit    TEXT
);
INSERT INTO "statement_audience_labels" VALUES('stm_e968363433f142c1a711a1e97828fdd7','["external-technical"]','curator','Integrators configure this.',NULL,NULL,'2026-08-01T00:00:00Z','curator','2026-08-02T00:00:00Z',NULL,NULL,NULL,NULL);
INSERT INTO "statement_audience_labels" VALUES('stm_af54f18e7cf14d0ba315f2f7bc4d5f13','["internal-technical", "external-technical"]','ai','Users see this.','scenario-model',0.0001,'2026-08-01T00:00:00Z',NULL,NULL,'["external-non-technical"]','{"external-technical": {"at": "2026-08-02T00:00:00Z", "by": "curator", "decision": "confirmed"}}','{"previous": ["external-non-technical"], "lost": ["external-non-technical"], "reason": "The new text names an internal service."}','{"audiences": ["external-technical"], "old_text": "A user submits the sign-in form.", "at": "2026-08-03T00:00:00Z"}');
CREATE TABLE statement_kind_glossary (
    kind        TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    when_to_use TEXT,
    created_at  TEXT,
    updated_at  TEXT,
    created_by  TEXT,
    updated_by  TEXT
);
INSERT INTO "statement_kind_glossary" VALUES('event','Something happening — an atomic occurrence in the product (creation, submission, rejection, dispatch).','Discrete things that fire, succeed, or are rejected. Use action-as-subject phrasing (''an invite is submitted''), with the actor in `mentions` unless the actor''s identity is itself the claim (in which case use `capability`).','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "statement_kind_glossary" VALUES('state','A genuinely persisting, observable condition of a named entity — enum values, configuration flags, or conditions at a decision point.','Enum/status values (''Applied'' on Draft Status), config flags (''Auto result sharing enabled'' on Company), or observable missing-input conditions (''No name on the invite'' on Invite). Often referenced as `when` leaves on conditional edges. Do NOT use for derived/computed conditions or internal-mechanism steps.','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "statement_kind_glossary" VALUES('capability','A modal claim about what is possible — ''X can do Y''. Warranted only when the actor''s identity or permission boundary is itself the claim, or when it anchors a `governed-by` rule tree.','Authoring an event already implies the action is possible. Reach for `capability` when the point of the statement is who is allowed, what is gated, or which rule decomposition this modal anchors. Otherwise prefer `event`.','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "statement_kind_glossary" VALUES('rule','An obligation or permission — what must, must not, or may happen — or a definition, formula, default, or bound that holds the same way across all instances and moments.','Obligations and permissions (''a draft must be approved by a curator''; ''an admin may revoke any token''), and definitional or computational claims (''statement kind is one of: event, state, capability, rule, property''). Modals such as must, may and is required to belong here, not in an `event` or `state`; the statement a rule governs links to it with `governed-by`. Apply the contingency test: if the same claim could be otherwise for a specific entity or at a specific time, it is a `state`, not a `rule`.','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "statement_kind_glossary" VALUES('property','A slot on an entity that holds a value — short noun-phrase label, not a sentence. ''Email'', ''Server host'', ''Similarity score''.','When the meaningful question is *what value* rather than *does this hold*. User-supplied configuration values, user-supplied event inputs, or derived/computed values. Anchored to its entity via `mentions`. Reach for this instead of packing inputs into event text.','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "statement_kind_glossary" VALUES('procedure','The named root of a how-to guide. ''How to connect an MCP client to a Mycelium server.'' Composes `action`s, `property` inputs, and optional `check`s into a runnable script.','Authoring prescriptive content: a guide the user (or an agent) executes to accomplish something. Anchors to a `capability` via `teaches`. The body is composed via `contains` / `next` to actions, and `requires` / `accepts` to property inputs.','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "statement_kind_glossary" VALUES('action','A step the user performs that modifies the system. ''Click the Save button.'' Anchors to a descriptive `event` via `performs`.','Single UI interactions inside a procedure or diagnostic flow: clicks, navigations, entries, sends. Each action is its own statement; the procedure `contains` them or chains them via `next`.','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "statement_kind_glossary" VALUES('check','A verification step for a diagnostic agent — observing the system without changing it. ''Verify the user''s authentication provider matches the login method.''','Diagnostic flows where a step inspects rather than mutates. Anchors to a `state` via `verifies`. Branches with `on-success` / `on-failure` or links to a `cause` via `confirms` / `refutes`.','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "statement_kind_glossary" VALUES('cause','A named failure mode worth investigating. ''User is attempting password login on a social-only account.''','Roots of a diagnostic tree. Optionally anchors to a `state` via `violates` when the failure mode is ''a required state isn''t met''. Free-standing when the failure is environmental, historical, referential, or compound.','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
CREATE TABLE statement_link_type_glossary (
    link_type   TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    created_at  TEXT,
    updated_at  TEXT,
    created_by  TEXT,
    updated_by  TEXT
);
INSERT INTO "statement_link_type_glossary" VALUES('contains','Sub-step inside the same process. Target only makes sense as part of the parent (e.g. ''The write pipeline executes'' contains ''The extraction agent runs'').','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('triggers','A *separate* downstream process fires as a consequence. Target stands on its own clock (e.g. ''An invite is created'' triggers ''A notification email is sent'').','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('establishes','Source produces a resulting state. Multiple statements can each `establishes` the same state — the state becomes the convergence point. No intermediate events: if event A causes state S, link A → establishes → S directly; do not create an intermediate event whose only purpose is to establish S.','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('enables','Source unlocks target''s capability without directly invoking it (e.g. ''Embeddings are generated'' enables ''Vector search returns ranked results''). Do NOT use for condition states — a state referenced in a `when` expression on an edge must not also have an `enables` link to the same target.','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('requires','Two uses: (1) target must hold for source to fire, usually paired with a `when` clause when the prerequisite is itself a statement; (2) source consumes the target `property` as a mandatory input in this context.','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('accepts','Source consumes the target `property` as an *optional* input in this context. The same property record is referenced from a `requires` edge elsewhere — optionality is per-edge, not per-property.','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('varies-by','Source''s behavior depends on target as a parameter — shapes *how* source plays out, not *whether* it fires.','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('configures','Source parameterises target before target fires. Use sparingly; `contains` is often cleaner.','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('replaces','Source supersedes target. Almost always with a `when` clause — ''replaces under condition C''.','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('restricts','Source limits target''s operation. Use when the limit is itself a *statement* (a kill-switch, a feature flag).','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('proceeds','Sequential hand-off in the same flow. A proceeds to B means B is the immediate next step after A in a continuous sequence — neither a contained sub-step (`contains`) nor an independently-fired downstream process (`triggers`). Use when A''s completion naturally flows into B without a causal gap.','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('fallback-to','Ordered priority chain. A fallback-to B means B applies only when A does not. Forms a linear chain; first applicable option wins. Distinct from `cases` (enumeration over a named value set) and `composes` (grouping without ordering).','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('governed-by','The rule that determines how a capability works. Typically: capability → governed-by → top-level rule.','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('composes','Sub-formula or sub-rule; together the composed statements specify the parent. Carry `when`-conditions on these edges for conditional applicability. Not the same as `cases`.','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('cases','Enumerated branches over a named, finite value set only (statement kinds, link types, etc.). Each edge points to one branch. Do NOT use for continuous predicates — use a `when`-condition on a `composes` edge instead.','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('valued-by','The source statement''s value is derived by the target rule. Typically: state → valued-by → rule. Do NOT use when the value is configured or input directly.','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('supersedes','Versioning: source replaces target.','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('teaches','Procedure → capability. Anchors a how-to guide to the capability it teaches the user to exercise. Every `procedure` should `teaches` exactly one capability.','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('performs','Action → event. The user step models this product event — the descriptive thing that actually happens when the user performs the step. Anchors the prescriptive action to the descriptive layer.','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('verifies','Check → state. The diagnostic check inspects whether this state currently holds, without changing the system. Anchors the check to the descriptive condition being observed.','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('violates','Cause → state. The failure mode corresponds to a required state not holding. Optional anchor: a cause may also be free-standing (environmental, historical, referential, or compound) and need no `violates` link.','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('obtained-by','Property → action or procedure. How the user finds or produces this value. Empty for values the user types directly or for derived/computed values.','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('next','Linear sequence between prescriptive steps. A `next` B means B follows A. Use for action→action and check→check chains. Distinct from descriptive `proceeds` (which connects events).','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('on-success','Branch after a check or action on its success path. Source''s success outcome leads to target. Pair with `on-failure` for the complementary branch.','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('on-failure','Branch after a check or action on its failure path. Source''s failure outcome leads to target. Pair with `on-success` for the complementary branch.','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('confirms','Check → cause. If this check passes, this cause is the issue. Used in diagnostic trees to link verification steps to the failure modes they identify.','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('refutes','Check → cause. If this check passes, this cause is *not* the issue. Used in diagnostic trees to rule causes out.','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('resolves','Action → cause. This action fixes the situation when the cause applies. Used to attach remediation steps to diagnosed failure modes.','2026-10-24T15:36:56.917Z',NULL,NULL,NULL);
CREATE TABLE statement_links (
    link_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    from_statement_id TEXT NOT NULL REFERENCES statements(id),
    to_statement_id   TEXT NOT NULL REFERENCES statements(id),
    link_type         TEXT NOT NULL,
    when_hash         TEXT NOT NULL,
    created_at        TEXT,
    created_by        TEXT,
    UNIQUE (from_statement_id, to_statement_id, link_type, when_hash)
);
INSERT INTO "statement_links" VALUES(1,'stm_af54f18e7cf14d0ba315f2f7bc4d5f13','stm_c24d1293af5c414eb1e5b9e2fa9d2d5c','triggers','7cfc814a970aa3cb854c3906b37aa1cef6443aeb90e8e91615563317385c8ed3','2026-10-24T15:36:57.055Z',NULL);
CREATE TABLE statement_mentions (
    statement_id TEXT NOT NULL REFERENCES statements(id),
    name_id     TEXT NOT NULL REFERENCES names(id),
    PRIMARY KEY (statement_id, name_id)
);
INSERT INTO "statement_mentions" VALUES('stm_c24d1293af5c414eb1e5b9e2fa9d2d5c','nam_5d779d2255e045ceb4c06aa7d6fbd915');
INSERT INTO "statement_mentions" VALUES('stm_e968363433f142c1a711a1e97828fdd7','nam_5d779d2255e045ceb4c06aa7d6fbd915');
CREATE TABLE statement_vector_ids (
    statement_id TEXT PRIMARY KEY REFERENCES statements(id),
    vector_id   INTEGER NOT NULL UNIQUE
);
INSERT INTO "statement_vector_ids" VALUES('stm_af54f18e7cf14d0ba315f2f7bc4d5f13',0);
INSERT INTO "statement_vector_ids" VALUES('stm_c24d1293af5c414eb1e5b9e2fa9d2d5c',1);
INSERT INTO "statement_vector_ids" VALUES('stm_89e80a3bc3fd4aefaa85eaf9b4247d13',2);
INSERT INTO "statement_vector_ids" VALUES('stm_e968363433f142c1a711a1e97828fdd7',3);
CREATE TABLE statements (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,
    text       TEXT NOT NULL,
    created_at TEXT,
    updated_at TEXT,
    created_by TEXT,
    updated_by TEXT
);
INSERT INTO "statements" VALUES('stm_af54f18e7cf14d0ba315f2f7bc4d5f13','event','A user submits the Login form.','2026-10-24T15:36:57.053Z',NULL,NULL,NULL);
INSERT INTO "statements" VALUES('stm_c24d1293af5c414eb1e5b9e2fa9d2d5c','event','The server issues a Session token.','2026-10-24T15:36:57.054Z',NULL,NULL,NULL);
INSERT INTO "statements" VALUES('stm_89e80a3bc3fd4aefaa85eaf9b4247d13','state','The account is locked.','2026-10-24T15:36:57.054Z',NULL,NULL,NULL);
INSERT INTO "statements" VALUES('stm_e968363433f142c1a711a1e97828fdd7','rule','A Session token expires after twelve hours.','2026-10-24T15:36:57.055Z',NULL,NULL,NULL);
CREATE TABLE when_nodes (
    node_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    link_id     INTEGER NOT NULL REFERENCES statement_links(link_id) ON DELETE CASCADE,
    parent_id   INTEGER REFERENCES when_nodes(node_id) ON DELETE CASCADE,
    op          TEXT,
    statement_id TEXT REFERENCES statements(id) ON DELETE RESTRICT,
    child_index INTEGER NOT NULL,
    CHECK ((op IS NULL) <> (statement_id IS NULL)),
    CHECK (op IS NULL OR op IN ('and', 'or', 'not'))
);
INSERT INTO "when_nodes" VALUES(1,1,NULL,'not',NULL,0);
INSERT INTO "when_nodes" VALUES(2,1,1,NULL,'stm_89e80a3bc3fd4aefaa85eaf9b4247d13',0);
CREATE INDEX statement_mentions_name ON statement_mentions (name_id);
CREATE INDEX names_entity ON names (entity_id);
CREATE INDEX statement_links_from_id
    ON statement_links (from_statement_id, link_id);
CREATE INDEX statement_links_to_id
    ON statement_links (to_statement_id, link_id);
CREATE INDEX when_nodes_link_id     ON when_nodes (link_id);
CREATE INDEX when_nodes_statement_id ON when_nodes (statement_id);
CREATE INDEX when_nodes_statement_link
    ON when_nodes (statement_id, link_id);
CREATE INDEX mention_recompute_queue_open
    ON mention_recompute_queue (id) WHERE claimed_at IS NULL;
CREATE INDEX pending_mentions_statement
    ON pending_mentions (statement_id);
CREATE INDEX pending_mentions_name
    ON pending_mentions (name_id);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('mention_recompute_queue',7);
INSERT INTO "sqlite_sequence" VALUES('statement_links',1);
INSERT INTO "sqlite_sequence" VALUES('when_nodes',2);
INSERT INTO "sqlite_sequence" VALUES('pending_mentions',1);
COMMIT;
