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
INSERT INTO "history_events" VALUES(1,'2026-10-22T18:38:55.212Z',NULL,'create','entity','ent_e42ffece53b84aab8c0968ea059130e1',NULL,'{"id": "ent_e42ffece53b84aab8c0968ea059130e1", "description": "Signing in.", "created_at": "2026-10-22T18:38:55.212Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-22T18:38:55.212Z',NULL,'create','name','nam_10c1bdeca11544b7bd7e24f1ec3f38cd',NULL,'{"id": "nam_10c1bdeca11544b7bd7e24f1ec3f38cd", "text": "Login", "entity_id": "ent_e42ffece53b84aab8c0968ea059130e1", "generated_from_name_id": null, "created_at": "2026-10-22T18:38:55.212Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-22T18:38:55.221Z',NULL,'create','name','nam_d4874db541d4495dbe9670c4e1216d24',NULL,'{"id": "nam_d4874db541d4495dbe9670c4e1216d24", "text": "Logins", "entity_id": "ent_e42ffece53b84aab8c0968ea059130e1", "generated_from_name_id": "nam_10c1bdeca11544b7bd7e24f1ec3f38cd", "created_at": "2026-10-22T18:38:55.221Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-22T18:38:55.223Z',NULL,'create','entity','ent_3d09cd4b5863427eaadc175383dc3781',NULL,'{"id": "ent_3d09cd4b5863427eaadc175383dc3781", "description": "An authenticated visit.", "created_at": "2026-10-22T18:38:55.223Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-22T18:38:55.223Z',NULL,'create','name','nam_2f25c100a558459eb0a99ce8d9488981',NULL,'{"id": "nam_2f25c100a558459eb0a99ce8d9488981", "text": "Session", "entity_id": "ent_3d09cd4b5863427eaadc175383dc3781", "generated_from_name_id": null, "created_at": "2026-10-22T18:38:55.223Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-22T18:38:55.223Z',NULL,'create','name','nam_e28d7dd47ef74d6386035d95fc1d5aeb',NULL,'{"id": "nam_e28d7dd47ef74d6386035d95fc1d5aeb", "text": "Sessions", "entity_id": "ent_3d09cd4b5863427eaadc175383dc3781", "generated_from_name_id": "nam_2f25c100a558459eb0a99ce8d9488981", "created_at": "2026-10-22T18:38:55.223Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-22T18:38:55.224Z',NULL,'create','name','nam_5055f6a4a90e45bb8072a7a6d1821ea6',NULL,'{"id": "nam_5055f6a4a90e45bb8072a7a6d1821ea6", "text": "Sign-in", "entity_id": "ent_e42ffece53b84aab8c0968ea059130e1", "generated_from_name_id": null, "created_at": "2026-10-22T18:38:55.224Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-22T18:38:55.225Z',NULL,'create','name','nam_1434b6d4554f4f7ab6a35208fa22f962',NULL,'{"id": "nam_1434b6d4554f4f7ab6a35208fa22f962", "text": "Sign-ins", "entity_id": "ent_e42ffece53b84aab8c0968ea059130e1", "generated_from_name_id": "nam_5055f6a4a90e45bb8072a7a6d1821ea6", "created_at": "2026-10-22T18:38:55.225Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-22T18:38:55.226Z',NULL,'link','entity_link','ent_e42ffece53b84aab8c0968ea059130e1|ent_3d09cd4b5863427eaadc175383dc3781|contains',NULL,'{"from_entity_id": "ent_e42ffece53b84aab8c0968ea059130e1", "to_entity_id": "ent_3d09cd4b5863427eaadc175383dc3781", "link_type": "contains", "created_at": "2026-10-22T18:38:55.226Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-22T18:38:55.227Z',NULL,'create','statement','stm_fa75374b47084e299f201b70d9c0f982',NULL,'{"id": "stm_fa75374b47084e299f201b70d9c0f982", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-22T18:38:55.227Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-22T18:38:55.229Z',NULL,'create','statement','stm_a414667ca0554e8098fca9d8d89a9dab',NULL,'{"id": "stm_a414667ca0554e8098fca9d8d89a9dab", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-22T18:38:55.228Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-22T18:38:55.230Z',NULL,'create','statement','stm_90e476f00cdb4d0d88ce2e20fb2b6dea',NULL,'{"id": "stm_90e476f00cdb4d0d88ce2e20fb2b6dea", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-22T18:38:55.230Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-22T18:38:55.231Z',NULL,'create','statement','stm_d49dffbcc0be4257a3d396e44a1a6296',NULL,'{"id": "stm_d49dffbcc0be4257a3d396e44a1a6296", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-22T18:38:55.231Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-22T18:38:55.233Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_fa75374b47084e299f201b70d9c0f982", "to_id": "stm_a414667ca0554e8098fca9d8d89a9dab", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_90e476f00cdb4d0d88ce2e20fb2b6dea"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',14);
COMMIT;
