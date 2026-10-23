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
INSERT INTO "history_events" VALUES(1,'2026-10-23T11:13:28.532Z',NULL,'create','entity','ent_f41615f76d934c8ba4c320b4b641cb7e',NULL,'{"id": "ent_f41615f76d934c8ba4c320b4b641cb7e", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T11:13:28.532Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-23T11:13:28.532Z',NULL,'create','name','nam_861f26b5f5b24369846d45e74e60ff4f',NULL,'{"id": "nam_861f26b5f5b24369846d45e74e60ff4f", "text": "Login", "entity_id": "ent_f41615f76d934c8ba4c320b4b641cb7e", "generated_from_name_id": null, "created_at": "2026-10-23T11:13:28.532Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-23T11:13:28.532Z',NULL,'update','entity','ent_f41615f76d934c8ba4c320b4b641cb7e','{"id": "ent_f41615f76d934c8ba4c320b4b641cb7e", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T11:13:28.532Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_f41615f76d934c8ba4c320b4b641cb7e", "description": "Signing in.", "preferred_name_id": "nam_861f26b5f5b24369846d45e74e60ff4f", "created_at": "2026-10-23T11:13:28.532Z", "updated_at": "2026-10-23T11:13:28.532Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-23T11:13:28.536Z',NULL,'create','name','nam_d7fdee5cde014cc0831dae9d91636382',NULL,'{"id": "nam_d7fdee5cde014cc0831dae9d91636382", "text": "Logins", "entity_id": "ent_f41615f76d934c8ba4c320b4b641cb7e", "generated_from_name_id": "nam_861f26b5f5b24369846d45e74e60ff4f", "created_at": "2026-10-23T11:13:28.536Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-23T11:13:28.536Z',NULL,'create','entity','ent_9a0f381395ba49bb8b881d92b7bc4f15',NULL,'{"id": "ent_9a0f381395ba49bb8b881d92b7bc4f15", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T11:13:28.536Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-23T11:13:28.536Z',NULL,'create','name','nam_4de7e0b0a158485e9ecff0947e18231e',NULL,'{"id": "nam_4de7e0b0a158485e9ecff0947e18231e", "text": "Session", "entity_id": "ent_9a0f381395ba49bb8b881d92b7bc4f15", "generated_from_name_id": null, "created_at": "2026-10-23T11:13:28.536Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-23T11:13:28.536Z',NULL,'update','entity','ent_9a0f381395ba49bb8b881d92b7bc4f15','{"id": "ent_9a0f381395ba49bb8b881d92b7bc4f15", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T11:13:28.536Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_9a0f381395ba49bb8b881d92b7bc4f15", "description": "An authenticated visit.", "preferred_name_id": "nam_4de7e0b0a158485e9ecff0947e18231e", "created_at": "2026-10-23T11:13:28.536Z", "updated_at": "2026-10-23T11:13:28.536Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-23T11:13:28.536Z',NULL,'create','name','nam_62bccc9884854f59b364e6dcb836aa73',NULL,'{"id": "nam_62bccc9884854f59b364e6dcb836aa73", "text": "Sessions", "entity_id": "ent_9a0f381395ba49bb8b881d92b7bc4f15", "generated_from_name_id": "nam_4de7e0b0a158485e9ecff0947e18231e", "created_at": "2026-10-23T11:13:28.536Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-23T11:13:28.537Z',NULL,'create','name','nam_5e1141cf084547c6b93e329d18d53f56',NULL,'{"id": "nam_5e1141cf084547c6b93e329d18d53f56", "text": "Sign-in", "entity_id": "ent_f41615f76d934c8ba4c320b4b641cb7e", "generated_from_name_id": null, "created_at": "2026-10-23T11:13:28.537Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-23T11:13:28.537Z',NULL,'create','name','nam_2253ba3fc6504e4eb6c82e5cd27f0be7',NULL,'{"id": "nam_2253ba3fc6504e4eb6c82e5cd27f0be7", "text": "Sign-ins", "entity_id": "ent_f41615f76d934c8ba4c320b4b641cb7e", "generated_from_name_id": "nam_5e1141cf084547c6b93e329d18d53f56", "created_at": "2026-10-23T11:13:28.537Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-23T11:13:28.537Z',NULL,'link','entity_link','ent_f41615f76d934c8ba4c320b4b641cb7e|ent_9a0f381395ba49bb8b881d92b7bc4f15|contains',NULL,'{"from_entity_id": "ent_f41615f76d934c8ba4c320b4b641cb7e", "to_entity_id": "ent_9a0f381395ba49bb8b881d92b7bc4f15", "link_type": "contains", "created_at": "2026-10-23T11:13:28.537Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-23T11:13:28.538Z',NULL,'create','statement','stm_00db016ae62a42b4af5c4d998a474de7',NULL,'{"id": "stm_00db016ae62a42b4af5c4d998a474de7", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-23T11:13:28.537Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-23T11:13:28.538Z',NULL,'create','statement','stm_deee84868a9c492d84447197e416036d',NULL,'{"id": "stm_deee84868a9c492d84447197e416036d", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-23T11:13:28.538Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-23T11:13:28.538Z',NULL,'create','statement','stm_cdef00fd4f8c41849519c59ab1065f1d',NULL,'{"id": "stm_cdef00fd4f8c41849519c59ab1065f1d", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-23T11:13:28.538Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-23T11:13:28.539Z',NULL,'create','statement','stm_95651239dd7c48f99ffcb0e7c0c607fa',NULL,'{"id": "stm_95651239dd7c48f99ffcb0e7c0c607fa", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-23T11:13:28.539Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-23T11:13:28.539Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_00db016ae62a42b4af5c4d998a474de7", "to_id": "stm_deee84868a9c492d84447197e416036d", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_cdef00fd4f8c41849519c59ab1065f1d"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
