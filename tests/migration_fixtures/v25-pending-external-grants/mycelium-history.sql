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
INSERT INTO "history_events" VALUES(1,'2026-10-23T19:31:49.137Z',NULL,'create','entity','ent_d08ea5c825c34f2aa04156842b9942e2',NULL,'{"id": "ent_d08ea5c825c34f2aa04156842b9942e2", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T19:31:49.136Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-23T19:31:49.137Z',NULL,'create','name','nam_e7960b04ba2f458baa7d003846e048c7',NULL,'{"id": "nam_e7960b04ba2f458baa7d003846e048c7", "text": "Login", "entity_id": "ent_d08ea5c825c34f2aa04156842b9942e2", "generated_from_name_id": null, "created_at": "2026-10-23T19:31:49.137Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-23T19:31:49.137Z',NULL,'update','entity','ent_d08ea5c825c34f2aa04156842b9942e2','{"id": "ent_d08ea5c825c34f2aa04156842b9942e2", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T19:31:49.136Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_d08ea5c825c34f2aa04156842b9942e2", "description": "Signing in.", "preferred_name_id": "nam_e7960b04ba2f458baa7d003846e048c7", "created_at": "2026-10-23T19:31:49.136Z", "updated_at": "2026-10-23T19:31:49.137Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-23T19:31:49.141Z',NULL,'create','name','nam_2c8da130e5d54e3988bd9b90be6b5de6',NULL,'{"id": "nam_2c8da130e5d54e3988bd9b90be6b5de6", "text": "Logins", "entity_id": "ent_d08ea5c825c34f2aa04156842b9942e2", "generated_from_name_id": "nam_e7960b04ba2f458baa7d003846e048c7", "created_at": "2026-10-23T19:31:49.141Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-23T19:31:49.142Z',NULL,'create','entity','ent_89334ef92d6f4386aa8cad91b244746a',NULL,'{"id": "ent_89334ef92d6f4386aa8cad91b244746a", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T19:31:49.141Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-23T19:31:49.142Z',NULL,'create','name','nam_44567e986dab48c4a9962f011ba3bd88',NULL,'{"id": "nam_44567e986dab48c4a9962f011ba3bd88", "text": "Session", "entity_id": "ent_89334ef92d6f4386aa8cad91b244746a", "generated_from_name_id": null, "created_at": "2026-10-23T19:31:49.142Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-23T19:31:49.142Z',NULL,'update','entity','ent_89334ef92d6f4386aa8cad91b244746a','{"id": "ent_89334ef92d6f4386aa8cad91b244746a", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T19:31:49.141Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_89334ef92d6f4386aa8cad91b244746a", "description": "An authenticated visit.", "preferred_name_id": "nam_44567e986dab48c4a9962f011ba3bd88", "created_at": "2026-10-23T19:31:49.141Z", "updated_at": "2026-10-23T19:31:49.142Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-23T19:31:49.142Z',NULL,'create','name','nam_37df0b02c9ee419abf747d3774928add',NULL,'{"id": "nam_37df0b02c9ee419abf747d3774928add", "text": "Sessions", "entity_id": "ent_89334ef92d6f4386aa8cad91b244746a", "generated_from_name_id": "nam_44567e986dab48c4a9962f011ba3bd88", "created_at": "2026-10-23T19:31:49.142Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-23T19:31:49.142Z',NULL,'create','name','nam_5b423b96eebd4c8ab3b42ac1a2cd36bf',NULL,'{"id": "nam_5b423b96eebd4c8ab3b42ac1a2cd36bf", "text": "Sign-in", "entity_id": "ent_d08ea5c825c34f2aa04156842b9942e2", "generated_from_name_id": null, "created_at": "2026-10-23T19:31:49.142Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-23T19:31:49.142Z',NULL,'create','name','nam_044c17e6f5e34bb2a76f67618043706f',NULL,'{"id": "nam_044c17e6f5e34bb2a76f67618043706f", "text": "Sign-ins", "entity_id": "ent_d08ea5c825c34f2aa04156842b9942e2", "generated_from_name_id": "nam_5b423b96eebd4c8ab3b42ac1a2cd36bf", "created_at": "2026-10-23T19:31:49.142Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-23T19:31:49.143Z',NULL,'link','entity_link','ent_d08ea5c825c34f2aa04156842b9942e2|ent_89334ef92d6f4386aa8cad91b244746a|contains',NULL,'{"from_entity_id": "ent_d08ea5c825c34f2aa04156842b9942e2", "to_entity_id": "ent_89334ef92d6f4386aa8cad91b244746a", "link_type": "contains", "created_at": "2026-10-23T19:31:49.143Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-23T19:31:49.143Z',NULL,'create','statement','stm_5029dfbb1b4b48f9a67bfc3fa4e34780',NULL,'{"id": "stm_5029dfbb1b4b48f9a67bfc3fa4e34780", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-23T19:31:49.143Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-23T19:31:49.143Z',NULL,'create','statement','stm_13e3cf37e94743d6a4c4c0569fc46250',NULL,'{"id": "stm_13e3cf37e94743d6a4c4c0569fc46250", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-23T19:31:49.143Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-23T19:31:49.144Z',NULL,'create','statement','stm_22325e3d87e84b04afbc4a6f0ef5cca5',NULL,'{"id": "stm_22325e3d87e84b04afbc4a6f0ef5cca5", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-23T19:31:49.144Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-23T19:31:49.144Z',NULL,'create','statement','stm_724c8b9209bf4b0987ba3bd1fd8465f9',NULL,'{"id": "stm_724c8b9209bf4b0987ba3bd1fd8465f9", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-23T19:31:49.144Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-23T19:31:49.145Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_5029dfbb1b4b48f9a67bfc3fa4e34780", "to_id": "stm_13e3cf37e94743d6a4c4c0569fc46250", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_22325e3d87e84b04afbc4a6f0ef5cca5"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
