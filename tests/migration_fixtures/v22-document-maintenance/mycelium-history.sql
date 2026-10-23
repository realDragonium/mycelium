PRAGMA user_version = 0;
BEGIN TRANSACTION;
CREATE TABLE history_events (
    event_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    at           TEXT NOT NULL,
    actor        TEXT,
    op           TEXT NOT NULL,
    target_kind  TEXT NOT NULL,
    target_id    TEXT NOT NULL,
    before_json  TEXT,
    after_json   TEXT,
    context_json TEXT
);
INSERT INTO "history_events" VALUES(1,'2026-10-23T14:17:14.628Z',NULL,'create','entity','ent_350b23bc0adf422db7037f0ba9975c55',NULL,'{"id": "ent_350b23bc0adf422db7037f0ba9975c55", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T14:17:14.628Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-23T14:17:14.628Z',NULL,'create','name','nam_6af83fb28f524700a20804984abe453e',NULL,'{"id": "nam_6af83fb28f524700a20804984abe453e", "text": "Login", "entity_id": "ent_350b23bc0adf422db7037f0ba9975c55", "generated_from_name_id": null, "created_at": "2026-10-23T14:17:14.628Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-23T14:17:14.628Z',NULL,'update','entity','ent_350b23bc0adf422db7037f0ba9975c55','{"id": "ent_350b23bc0adf422db7037f0ba9975c55", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T14:17:14.628Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_350b23bc0adf422db7037f0ba9975c55", "description": "Signing in.", "preferred_name_id": "nam_6af83fb28f524700a20804984abe453e", "created_at": "2026-10-23T14:17:14.628Z", "updated_at": "2026-10-23T14:17:14.628Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-23T14:17:14.631Z',NULL,'create','name','nam_bd7a52ff018448fabd5018c11ceb24f6',NULL,'{"id": "nam_bd7a52ff018448fabd5018c11ceb24f6", "text": "Logins", "entity_id": "ent_350b23bc0adf422db7037f0ba9975c55", "generated_from_name_id": "nam_6af83fb28f524700a20804984abe453e", "created_at": "2026-10-23T14:17:14.631Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-23T14:17:14.632Z',NULL,'create','entity','ent_2403f518717242eea961f5b798e52ec1',NULL,'{"id": "ent_2403f518717242eea961f5b798e52ec1", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T14:17:14.632Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-23T14:17:14.632Z',NULL,'create','name','nam_ec53c0bde90042f0b51c6cd979fc364f',NULL,'{"id": "nam_ec53c0bde90042f0b51c6cd979fc364f", "text": "Session", "entity_id": "ent_2403f518717242eea961f5b798e52ec1", "generated_from_name_id": null, "created_at": "2026-10-23T14:17:14.632Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-23T14:17:14.632Z',NULL,'update','entity','ent_2403f518717242eea961f5b798e52ec1','{"id": "ent_2403f518717242eea961f5b798e52ec1", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T14:17:14.632Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_2403f518717242eea961f5b798e52ec1", "description": "An authenticated visit.", "preferred_name_id": "nam_ec53c0bde90042f0b51c6cd979fc364f", "created_at": "2026-10-23T14:17:14.632Z", "updated_at": "2026-10-23T14:17:14.632Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-23T14:17:14.632Z',NULL,'create','name','nam_f6cece576f0b48d8b200339f03a304c5',NULL,'{"id": "nam_f6cece576f0b48d8b200339f03a304c5", "text": "Sessions", "entity_id": "ent_2403f518717242eea961f5b798e52ec1", "generated_from_name_id": "nam_ec53c0bde90042f0b51c6cd979fc364f", "created_at": "2026-10-23T14:17:14.632Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-23T14:17:14.633Z',NULL,'create','name','nam_4de5148cd1924b459ee3898948ddc374',NULL,'{"id": "nam_4de5148cd1924b459ee3898948ddc374", "text": "Sign-in", "entity_id": "ent_350b23bc0adf422db7037f0ba9975c55", "generated_from_name_id": null, "created_at": "2026-10-23T14:17:14.632Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-23T14:17:14.633Z',NULL,'create','name','nam_65b17bb24f224f8880659532330f12b5',NULL,'{"id": "nam_65b17bb24f224f8880659532330f12b5", "text": "Sign-ins", "entity_id": "ent_350b23bc0adf422db7037f0ba9975c55", "generated_from_name_id": "nam_4de5148cd1924b459ee3898948ddc374", "created_at": "2026-10-23T14:17:14.633Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-23T14:17:14.633Z',NULL,'link','entity_link','ent_350b23bc0adf422db7037f0ba9975c55|ent_2403f518717242eea961f5b798e52ec1|contains',NULL,'{"from_entity_id": "ent_350b23bc0adf422db7037f0ba9975c55", "to_entity_id": "ent_2403f518717242eea961f5b798e52ec1", "link_type": "contains", "created_at": "2026-10-23T14:17:14.633Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-23T14:17:14.633Z',NULL,'create','statement','stm_86eb274f94d7494eb6c7f8af2eac9ff7',NULL,'{"id": "stm_86eb274f94d7494eb6c7f8af2eac9ff7", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-23T14:17:14.633Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-23T14:17:14.634Z',NULL,'create','statement','stm_0f8f8ed7d85b44bf836b969959e1f0b8',NULL,'{"id": "stm_0f8f8ed7d85b44bf836b969959e1f0b8", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-23T14:17:14.634Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-23T14:17:14.634Z',NULL,'create','statement','stm_9e02d082f1874122973ed88477c2a041',NULL,'{"id": "stm_9e02d082f1874122973ed88477c2a041", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-23T14:17:14.634Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-23T14:17:14.635Z',NULL,'create','statement','stm_f08398938f26422dbb3b32d39608d05d',NULL,'{"id": "stm_f08398938f26422dbb3b32d39608d05d", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-23T14:17:14.635Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-23T14:17:14.635Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_86eb274f94d7494eb6c7f8af2eac9ff7", "to_id": "stm_0f8f8ed7d85b44bf836b969959e1f0b8", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_9e02d082f1874122973ed88477c2a041"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
