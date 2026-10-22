PRAGMA user_version = 5;
BEGIN TRANSACTION;
CREATE TABLE entities (
    id          TEXT PRIMARY KEY,
    description TEXT,
    created_at  TEXT,
    updated_at  TEXT,
    created_by  TEXT,
    updated_by  TEXT
);
INSERT INTO "entities" VALUES('ent_cc92d4441b2b498b891dcf6c9f414f4e','Signing in.','2026-10-22T18:38:40.254Z',NULL,NULL,NULL);
INSERT INTO "entities" VALUES('ent_62fd20c15423409b9e668a1026821e4d','An authenticated visit.','2026-10-22T18:38:40.265Z',NULL,NULL,NULL);
CREATE TABLE entity_link_type_glossary (
    link_type   TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    created_at  TEXT,
    updated_at  TEXT,
    created_by  TEXT,
    updated_by  TEXT
);
INSERT INTO "entity_link_type_glossary" VALUES('contains','Parent → member. Structural composition between long-lived entities (e.g. parent corp → subsidiary, category → member). Same top-down direction as statement links: parent is the source.','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "entity_link_type_glossary" VALUES('replaces','Source entity supersedes target entity (e.g. one provider replacing another).','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "entity_link_type_glossary" VALUES('sub-type','Source is a specialization of target. Reads ''source is a sub-type of target'' (e.g. Ubeeo is a sub-type of ATS, hard_skill_german_language is a sub-type of Hard Skill). Parent / general category at the target end.','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "entity_link_type_glossary" VALUES('has','Source has the target as a component, attribute, or related object. Generic ownership/composition relation between long-lived entities when neither `contains` (strict structural membership) nor `sub-type` (specialization) fits.','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "entity_link_type_glossary" VALUES('uses','Source depends on or makes use of target. Behavioural dependency between long-lived entities — distinct from structural composition (`contains`) and specialization (`sub-type`).','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
CREATE TABLE entity_links (
    from_entity_id TEXT NOT NULL REFERENCES entities(id),
    to_entity_id   TEXT NOT NULL REFERENCES entities(id),
    link_type      TEXT NOT NULL,
    created_at     TEXT,
    created_by     TEXT,
    PRIMARY KEY (from_entity_id, to_entity_id, link_type)
);
INSERT INTO "entity_links" VALUES('ent_cc92d4441b2b498b891dcf6c9f414f4e','ent_62fd20c15423409b9e668a1026821e4d','contains','2026-10-22T18:38:40.267Z',NULL);
CREATE TABLE entity_statement_links (
    link_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id    TEXT NOT NULL REFERENCES entities(id),
    statement_id TEXT NOT NULL REFERENCES statements(id),
    direction    TEXT NOT NULL CHECK (direction IN ('es', 'se')),
    link_type    TEXT NOT NULL,
    when_hash    TEXT NOT NULL,
    created_at   TEXT,
    created_by   TEXT,
    UNIQUE (entity_id, statement_id, direction, link_type, when_hash)
);
CREATE TABLE knowledge_gaps (
    id           TEXT PRIMARY KEY,
    text         TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    created_by   TEXT,
    resolved_at  TEXT,
    resolved_by  TEXT,
    dismissed_at TEXT,
    dismissed_by TEXT,
    CHECK (resolved_at IS NULL OR dismissed_at IS NULL)
);
INSERT INTO "knowledge_gaps" VALUES('989468ab-b31f-474a-bc95-dc85432f1f26','How long does a locked account stay locked?','2026-10-22T18:38:40.274Z',NULL,NULL,NULL,NULL,NULL);
CREATE TABLE mention_recompute_queue (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    statement_id TEXT REFERENCES statements(id),
    scan_text    TEXT,
    enqueued_at  TEXT NOT NULL,
    claimed_at   TEXT,
    CHECK ((statement_id IS NULL) <> (scan_text IS NULL))
);
INSERT INTO "mention_recompute_queue" VALUES(1,NULL,'Login','2026-10-22T18:38:40.263Z',NULL);
INSERT INTO "mention_recompute_queue" VALUES(2,NULL,'Logins','2026-10-22T18:38:40.263Z',NULL);
INSERT INTO "mention_recompute_queue" VALUES(3,NULL,'Session','2026-10-22T18:38:40.265Z',NULL);
INSERT INTO "mention_recompute_queue" VALUES(4,NULL,'Sessions','2026-10-22T18:38:40.265Z',NULL);
INSERT INTO "mention_recompute_queue" VALUES(5,NULL,'Sign-in','2026-10-22T18:38:40.266Z',NULL);
INSERT INTO "mention_recompute_queue" VALUES(6,NULL,'Sign-ins','2026-10-22T18:38:40.267Z',NULL);
INSERT INTO "mention_recompute_queue" VALUES(7,NULL,'sign-in','2026-08-01T00:00:00Z',NULL);
CREATE TABLE name_vector_ids (
    name_id   TEXT PRIMARY KEY REFERENCES names(id),
    vector_id INTEGER NOT NULL UNIQUE
);
INSERT INTO "name_vector_ids" VALUES('nam_62d1354404a84bbfbb459d8c59a3c3da',0);
INSERT INTO "name_vector_ids" VALUES('nam_f42d1cfacf0244a7ae741767333b4629',1);
INSERT INTO "name_vector_ids" VALUES('nam_b37490da652241d197125704f7f7567a',2);
INSERT INTO "name_vector_ids" VALUES('nam_2bc7a0c451854289b2c3e8619a3609ce',3);
INSERT INTO "name_vector_ids" VALUES('nam_4109ec61b43d4712836e866f968c8025',4);
INSERT INTO "name_vector_ids" VALUES('nam_9aa05be2524446de9ca421fe3683bbfc',5);
CREATE TABLE names (
    id         TEXT PRIMARY KEY,
    text       TEXT NOT NULL UNIQUE,
    entity_id  TEXT NOT NULL REFERENCES entities(id),
    generated_from_name_id TEXT REFERENCES names(id),
    created_at TEXT,
    updated_at TEXT,
    created_by TEXT,
    updated_by TEXT
);
INSERT INTO "names" VALUES('nam_62d1354404a84bbfbb459d8c59a3c3da','Login','ent_cc92d4441b2b498b891dcf6c9f414f4e',NULL,'2026-10-22T18:38:40.254Z',NULL,NULL,NULL);
INSERT INTO "names" VALUES('nam_f42d1cfacf0244a7ae741767333b4629','Logins','ent_cc92d4441b2b498b891dcf6c9f414f4e','nam_62d1354404a84bbfbb459d8c59a3c3da','2026-10-22T18:38:40.263Z',NULL,NULL,NULL);
INSERT INTO "names" VALUES('nam_b37490da652241d197125704f7f7567a','Session','ent_62fd20c15423409b9e668a1026821e4d',NULL,'2026-10-22T18:38:40.265Z',NULL,NULL,NULL);
INSERT INTO "names" VALUES('nam_2bc7a0c451854289b2c3e8619a3609ce','Sessions','ent_62fd20c15423409b9e668a1026821e4d','nam_b37490da652241d197125704f7f7567a','2026-10-22T18:38:40.265Z',NULL,NULL,NULL);
INSERT INTO "names" VALUES('nam_4109ec61b43d4712836e866f968c8025','Sign-in','ent_cc92d4441b2b498b891dcf6c9f414f4e',NULL,'2026-10-22T18:38:40.266Z',NULL,NULL,NULL);
INSERT INTO "names" VALUES('nam_9aa05be2524446de9ca421fe3683bbfc','Sign-ins','ent_cc92d4441b2b498b891dcf6c9f414f4e','nam_4109ec61b43d4712836e866f968c8025','2026-10-22T18:38:40.266Z',NULL,NULL,NULL);
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
INSERT INTO "pending_mentions" VALUES(1,'stm_ab953feeb21d4a3f862526bcb88d9b20','nam_62d1354404a84bbfbb459d8c59a3c3da','2026-10-22T18:38:40.269Z',NULL,NULL,NULL,NULL);
INSERT INTO "pending_mentions" VALUES(2,'stm_ab953feeb21d4a3f862526bcb88d9b20','nam_4109ec61b43d4712836e866f968c8025','2026-08-01','2026-08-01','curator',NULL,NULL);
CREATE TABLE statement_kind_glossary (
    kind        TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    when_to_use TEXT,
    created_at  TEXT,
    updated_at  TEXT,
    created_by  TEXT,
    updated_by  TEXT
);
INSERT INTO "statement_kind_glossary" VALUES('event','Something happening — an atomic occurrence in the product (creation, submission, rejection, dispatch).','Discrete things that fire, succeed, or are rejected. Use action-as-subject phrasing (''an invite is submitted''), with the actor in `mentions` unless the actor''s identity is itself the claim (in which case use `capability`).','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "statement_kind_glossary" VALUES('state','A genuinely persisting, observable condition of a named entity — enum values, configuration flags, or conditions at a decision point.','Enum/status values (''Applied'' on Draft Status), config flags (''Auto result sharing enabled'' on Company), or observable missing-input conditions (''No name on the invite'' on Invite). Often referenced as `when` leaves on conditional edges. Do NOT use for derived/computed conditions or internal-mechanism steps.','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "statement_kind_glossary" VALUES('capability','A modal claim about what is possible — ''X can do Y''. Warranted only when the actor''s identity or permission boundary is itself the claim, or when it anchors a `governed-by` rule tree.','Authoring an event already implies the action is possible. Reach for `capability` when the point of the statement is who is allowed, what is gated, or which rule decomposition this modal anchors. Otherwise prefer `event`.','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "statement_kind_glossary" VALUES('rule','A deterministic, non-contingent claim — formula, default, enumeration, or bound that holds the same way across all instances and moments.','Definitional or computational claims (''statement kind is one of: event, state, capability, rule, property''; ''rank score equals similarity contribution plus recency boost minus staleness penalty''). Apply the contingency test: if the same claim could be otherwise for a specific entity or at a specific time, it is a `state`, not a `rule`.','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "statement_kind_glossary" VALUES('property','A slot on an entity that holds a value — short noun-phrase label, not a sentence. ''Email'', ''Server host'', ''Similarity score''.','When the meaningful question is *what value* rather than *does this hold*. User-supplied configuration values, user-supplied event inputs, or derived/computed values. Anchored to its entity via `mentions`. Reach for this instead of packing inputs into event text.','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "statement_kind_glossary" VALUES('procedure','The named root of a how-to guide. ''How to connect an MCP client to a Mycelium server.'' Composes `action`s, `property` inputs, and optional `check`s into a runnable script.','Authoring prescriptive content: a guide the user (or an agent) executes to accomplish something. Anchors to a `capability` via `teaches`. The body is composed via `contains` / `next` to actions, and `requires` / `accepts` to property inputs.','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "statement_kind_glossary" VALUES('action','A step the user performs that modifies the system. ''Click the Save button.'' Anchors to a descriptive `event` via `performs`.','Single UI interactions inside a procedure or diagnostic flow: clicks, navigations, entries, sends. Each action is its own statement; the procedure `contains` them or chains them via `next`.','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "statement_kind_glossary" VALUES('check','A verification step for a diagnostic agent — observing the system without changing it. ''Verify the user''s authentication provider matches the login method.''','Diagnostic flows where a step inspects rather than mutates. Anchors to a `state` via `verifies`. Branches with `on-success` / `on-failure` or links to a `cause` via `confirms` / `refutes`.','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "statement_kind_glossary" VALUES('cause','A named failure mode worth investigating. ''User is attempting password login on a social-only account.''','Roots of a diagnostic tree. Optionally anchors to a `state` via `violates` when the failure mode is ''a required state isn''t met''. Free-standing when the failure is environmental, historical, referential, or compound.','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
CREATE TABLE statement_link_type_glossary (
    link_type   TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    created_at  TEXT,
    updated_at  TEXT,
    created_by  TEXT,
    updated_by  TEXT
);
INSERT INTO "statement_link_type_glossary" VALUES('contains','Sub-step inside the same process. Target only makes sense as part of the parent (e.g. ''The write pipeline executes'' contains ''The extraction agent runs'').','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('triggers','A *separate* downstream process fires as a consequence. Target stands on its own clock (e.g. ''An invite is created'' triggers ''A notification email is sent'').','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('establishes','Source produces a resulting state. Multiple statements can each `establishes` the same state — the state becomes the convergence point. No intermediate events: if event A causes state S, link A → establishes → S directly; do not create an intermediate event whose only purpose is to establish S.','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('enables','Source unlocks target''s capability without directly invoking it (e.g. ''Embeddings are generated'' enables ''Vector search returns ranked results''). Do NOT use for condition states — a state referenced in a `when` expression on an edge must not also have an `enables` link to the same target.','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('requires','Two uses: (1) target must hold for source to fire, usually paired with a `when` clause when the prerequisite is itself a statement; (2) source consumes the target `property` as a mandatory input in this context.','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('accepts','Source consumes the target `property` as an *optional* input in this context. The same property record is referenced from a `requires` edge elsewhere — optionality is per-edge, not per-property.','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('varies-by','Source''s behavior depends on target as a parameter — shapes *how* source plays out, not *whether* it fires.','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('configures','Source parameterises target before target fires. Use sparingly; `contains` is often cleaner.','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('replaces','Source supersedes target. Almost always with a `when` clause — ''replaces under condition C''.','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('restricts','Source limits target''s operation. Use when the limit is itself a *statement* (a kill-switch, a feature flag).','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('proceeds','Sequential hand-off in the same flow. A proceeds to B means B is the immediate next step after A in a continuous sequence — neither a contained sub-step (`contains`) nor an independently-fired downstream process (`triggers`). Use when A''s completion naturally flows into B without a causal gap.','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('fallback-to','Ordered priority chain. A fallback-to B means B applies only when A does not. Forms a linear chain; first applicable option wins. Distinct from `cases` (enumeration over a named value set) and `composes` (grouping without ordering).','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('governed-by','The rule that determines how a capability works. Typically: capability → governed-by → top-level rule.','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('composes','Sub-formula or sub-rule; together the composed statements specify the parent. Carry `when`-conditions on these edges for conditional applicability. Not the same as `cases`.','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('cases','Enumerated branches over a named, finite value set only (statement kinds, link types, etc.). Each edge points to one branch. Do NOT use for continuous predicates — use a `when`-condition on a `composes` edge instead.','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('valued-by','The source statement''s value is derived by the target rule. Typically: state → valued-by → rule. Do NOT use when the value is configured or input directly.','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('supersedes','Versioning: source replaces target.','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('teaches','Procedure → capability. Anchors a how-to guide to the capability it teaches the user to exercise. Every `procedure` should `teaches` exactly one capability.','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('performs','Action → event. The user step models this product event — the descriptive thing that actually happens when the user performs the step. Anchors the prescriptive action to the descriptive layer.','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('verifies','Check → state. The diagnostic check inspects whether this state currently holds, without changing the system. Anchors the check to the descriptive condition being observed.','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('violates','Cause → state. The failure mode corresponds to a required state not holding. Optional anchor: a cause may also be free-standing (environmental, historical, referential, or compound) and need no `violates` link.','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('obtained-by','Property → action or procedure. How the user finds or produces this value. Empty for values the user types directly or for derived/computed values.','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('next','Linear sequence between prescriptive steps. A `next` B means B follows A. Use for action→action and check→check chains. Distinct from descriptive `proceeds` (which connects events).','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('on-success','Branch after a check or action on its success path. Source''s success outcome leads to target. Pair with `on-failure` for the complementary branch.','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('on-failure','Branch after a check or action on its failure path. Source''s failure outcome leads to target. Pair with `on-success` for the complementary branch.','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('confirms','Check → cause. If this check passes, this cause is the issue. Used in diagnostic trees to link verification steps to the failure modes they identify.','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('refutes','Check → cause. If this check passes, this cause is *not* the issue. Used in diagnostic trees to rule causes out.','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
INSERT INTO "statement_link_type_glossary" VALUES('resolves','Action → cause. This action fixes the situation when the cause applies. Used to attach remediation steps to diagnosed failure modes.','2026-10-22T18:38:40.142Z',NULL,NULL,NULL);
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
INSERT INTO "statement_links" VALUES(1,'stm_ab953feeb21d4a3f862526bcb88d9b20','stm_e158307e84d94c09b953c79280a931b1','triggers','4cb711d68a123497ac5bffc0f33987d4020d0cb158b131b562a123bd43e78dab','2026-10-22T18:38:40.273Z',NULL);
CREATE TABLE statement_mentions (
    statement_id TEXT NOT NULL REFERENCES statements(id),
    name_id     TEXT NOT NULL REFERENCES names(id),
    PRIMARY KEY (statement_id, name_id)
);
INSERT INTO "statement_mentions" VALUES('stm_e158307e84d94c09b953c79280a931b1','nam_b37490da652241d197125704f7f7567a');
INSERT INTO "statement_mentions" VALUES('stm_6db5f90407cb47029d5c046601ad69c1','nam_b37490da652241d197125704f7f7567a');
CREATE TABLE statement_vector_ids (
    statement_id TEXT PRIMARY KEY REFERENCES statements(id),
    vector_id   INTEGER NOT NULL UNIQUE
);
INSERT INTO "statement_vector_ids" VALUES('stm_ab953feeb21d4a3f862526bcb88d9b20',0);
INSERT INTO "statement_vector_ids" VALUES('stm_e158307e84d94c09b953c79280a931b1',1);
INSERT INTO "statement_vector_ids" VALUES('stm_97ea08a09fd1439e8ff206e799f54367',2);
INSERT INTO "statement_vector_ids" VALUES('stm_6db5f90407cb47029d5c046601ad69c1',3);
CREATE TABLE statements (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,
    text       TEXT NOT NULL,
    created_at TEXT,
    updated_at TEXT,
    created_by TEXT,
    updated_by TEXT
);
INSERT INTO "statements" VALUES('stm_ab953feeb21d4a3f862526bcb88d9b20','event','A user submits the Login form.','2026-10-22T18:38:40.268Z',NULL,NULL,NULL);
INSERT INTO "statements" VALUES('stm_e158307e84d94c09b953c79280a931b1','event','The server issues a Session token.','2026-10-22T18:38:40.270Z',NULL,NULL,NULL);
INSERT INTO "statements" VALUES('stm_97ea08a09fd1439e8ff206e799f54367','state','The account is locked.','2026-10-22T18:38:40.271Z',NULL,NULL,NULL);
INSERT INTO "statements" VALUES('stm_6db5f90407cb47029d5c046601ad69c1','rule','A Session token expires after twelve hours.','2026-10-22T18:38:40.272Z',NULL,NULL,NULL);
CREATE TABLE when_nodes (
    node_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    link_id     INTEGER NOT NULL,
    link_kind   TEXT NOT NULL DEFAULT 'statement',
    parent_id   INTEGER REFERENCES when_nodes(node_id) ON DELETE CASCADE,
    op          TEXT,
    statement_id TEXT REFERENCES statements(id) ON DELETE RESTRICT,
    child_index INTEGER NOT NULL,
    CHECK ((op IS NULL) <> (statement_id IS NULL)),
    CHECK (op IS NULL OR op IN ('and', 'or', 'not')),
    CHECK (link_kind IN ('statement', 'entity_statement'))
);
INSERT INTO "when_nodes" VALUES(1,1,'statement',NULL,'not',NULL,0);
INSERT INTO "when_nodes" VALUES(2,1,'statement',1,NULL,'stm_97ea08a09fd1439e8ff206e799f54367',0);
CREATE INDEX statement_mentions_name ON statement_mentions (name_id);
CREATE INDEX when_nodes_link_id     ON when_nodes (link_kind, link_id);
CREATE INDEX when_nodes_statement_id ON when_nodes (statement_id);
CREATE INDEX entity_statement_links_entity
    ON entity_statement_links (entity_id);
CREATE INDEX entity_statement_links_statement
    ON entity_statement_links (statement_id);
CREATE TRIGGER statement_links_delete_cascade_when
AFTER DELETE ON statement_links
BEGIN
    DELETE FROM when_nodes
    WHERE link_id = OLD.link_id AND link_kind = 'statement';
END;
CREATE TRIGGER entity_statement_links_delete_cascade_when
AFTER DELETE ON entity_statement_links
BEGIN
    DELETE FROM when_nodes
    WHERE link_id = OLD.link_id AND link_kind = 'entity_statement';
END;
CREATE INDEX mention_recompute_queue_open
    ON mention_recompute_queue (id) WHERE claimed_at IS NULL;
CREATE INDEX pending_mentions_statement
    ON pending_mentions (statement_id);
CREATE INDEX pending_mentions_name
    ON pending_mentions (name_id);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('mention_recompute_queue',7);
INSERT INTO "sqlite_sequence" VALUES('pending_mentions',2);
INSERT INTO "sqlite_sequence" VALUES('statement_links',1);
INSERT INTO "sqlite_sequence" VALUES('when_nodes',2);
COMMIT;
