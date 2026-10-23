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
INSERT INTO "history_events" VALUES(1,'2026-10-23T04:35:53.095Z',NULL,'create','entity','ent_a9d8f183bd344944915313d63b50e732',NULL,'{"id": "ent_a9d8f183bd344944915313d63b50e732", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T04:35:53.095Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-23T04:35:53.095Z',NULL,'create','name','nam_32d95c0b7fcf4831bc0a50fc23aeb245',NULL,'{"id": "nam_32d95c0b7fcf4831bc0a50fc23aeb245", "text": "Login", "entity_id": "ent_a9d8f183bd344944915313d63b50e732", "generated_from_name_id": null, "created_at": "2026-10-23T04:35:53.095Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-23T04:35:53.095Z',NULL,'update','entity','ent_a9d8f183bd344944915313d63b50e732','{"id": "ent_a9d8f183bd344944915313d63b50e732", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T04:35:53.095Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_a9d8f183bd344944915313d63b50e732", "description": "Signing in.", "preferred_name_id": "nam_32d95c0b7fcf4831bc0a50fc23aeb245", "created_at": "2026-10-23T04:35:53.095Z", "updated_at": "2026-10-23T04:35:53.095Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-23T04:35:53.099Z',NULL,'create','name','nam_9ed00fe5798a4a2db269ba6a662f1b33',NULL,'{"id": "nam_9ed00fe5798a4a2db269ba6a662f1b33", "text": "Logins", "entity_id": "ent_a9d8f183bd344944915313d63b50e732", "generated_from_name_id": "nam_32d95c0b7fcf4831bc0a50fc23aeb245", "created_at": "2026-10-23T04:35:53.099Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-23T04:35:53.099Z',NULL,'create','entity','ent_6aeed62fe2e745e5b8e9ece5c27e568a',NULL,'{"id": "ent_6aeed62fe2e745e5b8e9ece5c27e568a", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T04:35:53.099Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-23T04:35:53.100Z',NULL,'create','name','nam_4d76ac1b758048b4a5565d404be20d78',NULL,'{"id": "nam_4d76ac1b758048b4a5565d404be20d78", "text": "Session", "entity_id": "ent_6aeed62fe2e745e5b8e9ece5c27e568a", "generated_from_name_id": null, "created_at": "2026-10-23T04:35:53.100Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-23T04:35:53.100Z',NULL,'update','entity','ent_6aeed62fe2e745e5b8e9ece5c27e568a','{"id": "ent_6aeed62fe2e745e5b8e9ece5c27e568a", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T04:35:53.099Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_6aeed62fe2e745e5b8e9ece5c27e568a", "description": "An authenticated visit.", "preferred_name_id": "nam_4d76ac1b758048b4a5565d404be20d78", "created_at": "2026-10-23T04:35:53.099Z", "updated_at": "2026-10-23T04:35:53.100Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-23T04:35:53.100Z',NULL,'create','name','nam_166648a8e83146408ec43d1f1e8e46c4',NULL,'{"id": "nam_166648a8e83146408ec43d1f1e8e46c4", "text": "Sessions", "entity_id": "ent_6aeed62fe2e745e5b8e9ece5c27e568a", "generated_from_name_id": "nam_4d76ac1b758048b4a5565d404be20d78", "created_at": "2026-10-23T04:35:53.100Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-23T04:35:53.100Z',NULL,'create','name','nam_6b7fb91fa0084ef396e16b89170af18d',NULL,'{"id": "nam_6b7fb91fa0084ef396e16b89170af18d", "text": "Sign-in", "entity_id": "ent_a9d8f183bd344944915313d63b50e732", "generated_from_name_id": null, "created_at": "2026-10-23T04:35:53.100Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-23T04:35:53.100Z',NULL,'create','name','nam_f6825af359134bd39c794f2701b98e06',NULL,'{"id": "nam_f6825af359134bd39c794f2701b98e06", "text": "Sign-ins", "entity_id": "ent_a9d8f183bd344944915313d63b50e732", "generated_from_name_id": "nam_6b7fb91fa0084ef396e16b89170af18d", "created_at": "2026-10-23T04:35:53.100Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-23T04:35:53.101Z',NULL,'link','entity_link','ent_a9d8f183bd344944915313d63b50e732|ent_6aeed62fe2e745e5b8e9ece5c27e568a|contains',NULL,'{"from_entity_id": "ent_a9d8f183bd344944915313d63b50e732", "to_entity_id": "ent_6aeed62fe2e745e5b8e9ece5c27e568a", "link_type": "contains", "created_at": "2026-10-23T04:35:53.100Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-23T04:35:53.101Z',NULL,'create','statement','stm_8ebcf1c9776142358d0dfaed6f73d76c',NULL,'{"id": "stm_8ebcf1c9776142358d0dfaed6f73d76c", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-23T04:35:53.101Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-23T04:35:53.101Z',NULL,'create','statement','stm_2a1a56290e03485cae16d3014e880c49',NULL,'{"id": "stm_2a1a56290e03485cae16d3014e880c49", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-23T04:35:53.101Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-23T04:35:53.102Z',NULL,'create','statement','stm_7035e2c55b714dce918beb78c2d57d0a',NULL,'{"id": "stm_7035e2c55b714dce918beb78c2d57d0a", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-23T04:35:53.102Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-23T04:35:53.102Z',NULL,'create','statement','stm_b671033aa8184073bf1b2efdbce57ba7',NULL,'{"id": "stm_b671033aa8184073bf1b2efdbce57ba7", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-23T04:35:53.102Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-23T04:35:53.103Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_8ebcf1c9776142358d0dfaed6f73d76c", "to_id": "stm_2a1a56290e03485cae16d3014e880c49", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_7035e2c55b714dce918beb78c2d57d0a"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
