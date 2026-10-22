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
INSERT INTO "history_events" VALUES(1,'2026-10-22T18:38:40.254Z',NULL,'create','entity','ent_cc92d4441b2b498b891dcf6c9f414f4e',NULL,'{"id": "ent_cc92d4441b2b498b891dcf6c9f414f4e", "description": "Signing in.", "created_at": "2026-10-22T18:38:40.254Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-22T18:38:40.254Z',NULL,'create','name','nam_62d1354404a84bbfbb459d8c59a3c3da',NULL,'{"id": "nam_62d1354404a84bbfbb459d8c59a3c3da", "text": "Login", "entity_id": "ent_cc92d4441b2b498b891dcf6c9f414f4e", "generated_from_name_id": null, "created_at": "2026-10-22T18:38:40.254Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-22T18:38:40.263Z',NULL,'create','name','nam_f42d1cfacf0244a7ae741767333b4629',NULL,'{"id": "nam_f42d1cfacf0244a7ae741767333b4629", "text": "Logins", "entity_id": "ent_cc92d4441b2b498b891dcf6c9f414f4e", "generated_from_name_id": "nam_62d1354404a84bbfbb459d8c59a3c3da", "created_at": "2026-10-22T18:38:40.263Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-22T18:38:40.265Z',NULL,'create','entity','ent_62fd20c15423409b9e668a1026821e4d',NULL,'{"id": "ent_62fd20c15423409b9e668a1026821e4d", "description": "An authenticated visit.", "created_at": "2026-10-22T18:38:40.265Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-22T18:38:40.265Z',NULL,'create','name','nam_b37490da652241d197125704f7f7567a',NULL,'{"id": "nam_b37490da652241d197125704f7f7567a", "text": "Session", "entity_id": "ent_62fd20c15423409b9e668a1026821e4d", "generated_from_name_id": null, "created_at": "2026-10-22T18:38:40.265Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-22T18:38:40.265Z',NULL,'create','name','nam_2bc7a0c451854289b2c3e8619a3609ce',NULL,'{"id": "nam_2bc7a0c451854289b2c3e8619a3609ce", "text": "Sessions", "entity_id": "ent_62fd20c15423409b9e668a1026821e4d", "generated_from_name_id": "nam_b37490da652241d197125704f7f7567a", "created_at": "2026-10-22T18:38:40.265Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-22T18:38:40.266Z',NULL,'create','name','nam_4109ec61b43d4712836e866f968c8025',NULL,'{"id": "nam_4109ec61b43d4712836e866f968c8025", "text": "Sign-in", "entity_id": "ent_cc92d4441b2b498b891dcf6c9f414f4e", "generated_from_name_id": null, "created_at": "2026-10-22T18:38:40.266Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-22T18:38:40.266Z',NULL,'create','name','nam_9aa05be2524446de9ca421fe3683bbfc',NULL,'{"id": "nam_9aa05be2524446de9ca421fe3683bbfc", "text": "Sign-ins", "entity_id": "ent_cc92d4441b2b498b891dcf6c9f414f4e", "generated_from_name_id": "nam_4109ec61b43d4712836e866f968c8025", "created_at": "2026-10-22T18:38:40.266Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-22T18:38:40.267Z',NULL,'link','entity_link','ent_cc92d4441b2b498b891dcf6c9f414f4e|ent_62fd20c15423409b9e668a1026821e4d|contains',NULL,'{"from_entity_id": "ent_cc92d4441b2b498b891dcf6c9f414f4e", "to_entity_id": "ent_62fd20c15423409b9e668a1026821e4d", "link_type": "contains", "created_at": "2026-10-22T18:38:40.267Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-22T18:38:40.268Z',NULL,'create','statement','stm_ab953feeb21d4a3f862526bcb88d9b20',NULL,'{"id": "stm_ab953feeb21d4a3f862526bcb88d9b20", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-22T18:38:40.268Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-22T18:38:40.270Z',NULL,'create','statement','stm_e158307e84d94c09b953c79280a931b1',NULL,'{"id": "stm_e158307e84d94c09b953c79280a931b1", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-22T18:38:40.270Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-22T18:38:40.271Z',NULL,'create','statement','stm_97ea08a09fd1439e8ff206e799f54367',NULL,'{"id": "stm_97ea08a09fd1439e8ff206e799f54367", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-22T18:38:40.271Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-22T18:38:40.272Z',NULL,'create','statement','stm_6db5f90407cb47029d5c046601ad69c1',NULL,'{"id": "stm_6db5f90407cb47029d5c046601ad69c1", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-22T18:38:40.272Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-22T18:38:40.273Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_ab953feeb21d4a3f862526bcb88d9b20", "to_id": "stm_e158307e84d94c09b953c79280a931b1", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_97ea08a09fd1439e8ff206e799f54367"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',14);
COMMIT;
