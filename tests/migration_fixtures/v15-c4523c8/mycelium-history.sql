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
INSERT INTO "history_events" VALUES(1,'2026-10-22T20:25:25.003Z',NULL,'create','entity','ent_b3de63e7438f4990a97c9ce5cc8d2746',NULL,'{"id": "ent_b3de63e7438f4990a97c9ce5cc8d2746", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-22T20:25:25.003Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-22T20:25:25.003Z',NULL,'create','name','nam_d34bc0e0146a44caaf68d0e6faf2aebe',NULL,'{"id": "nam_d34bc0e0146a44caaf68d0e6faf2aebe", "text": "Login", "entity_id": "ent_b3de63e7438f4990a97c9ce5cc8d2746", "generated_from_name_id": null, "created_at": "2026-10-22T20:25:25.003Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-22T20:25:25.003Z',NULL,'update','entity','ent_b3de63e7438f4990a97c9ce5cc8d2746','{"id": "ent_b3de63e7438f4990a97c9ce5cc8d2746", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-22T20:25:25.003Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_b3de63e7438f4990a97c9ce5cc8d2746", "description": "Signing in.", "preferred_name_id": "nam_d34bc0e0146a44caaf68d0e6faf2aebe", "created_at": "2026-10-22T20:25:25.003Z", "updated_at": "2026-10-22T20:25:25.003Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-22T20:25:25.012Z',NULL,'create','name','nam_daffb0406c30483ba3cdf43183ba4df4',NULL,'{"id": "nam_daffb0406c30483ba3cdf43183ba4df4", "text": "Logins", "entity_id": "ent_b3de63e7438f4990a97c9ce5cc8d2746", "generated_from_name_id": "nam_d34bc0e0146a44caaf68d0e6faf2aebe", "created_at": "2026-10-22T20:25:25.012Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-22T20:25:25.014Z',NULL,'create','entity','ent_167d9c81a16b4925a5ddb8005d404004',NULL,'{"id": "ent_167d9c81a16b4925a5ddb8005d404004", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-22T20:25:25.014Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-22T20:25:25.014Z',NULL,'create','name','nam_ac27eef167e14987825de4787fcd29ea',NULL,'{"id": "nam_ac27eef167e14987825de4787fcd29ea", "text": "Session", "entity_id": "ent_167d9c81a16b4925a5ddb8005d404004", "generated_from_name_id": null, "created_at": "2026-10-22T20:25:25.014Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-22T20:25:25.014Z',NULL,'update','entity','ent_167d9c81a16b4925a5ddb8005d404004','{"id": "ent_167d9c81a16b4925a5ddb8005d404004", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-22T20:25:25.014Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_167d9c81a16b4925a5ddb8005d404004", "description": "An authenticated visit.", "preferred_name_id": "nam_ac27eef167e14987825de4787fcd29ea", "created_at": "2026-10-22T20:25:25.014Z", "updated_at": "2026-10-22T20:25:25.014Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-22T20:25:25.014Z',NULL,'create','name','nam_258120ac0c4f4b538dcac3f285e9c670',NULL,'{"id": "nam_258120ac0c4f4b538dcac3f285e9c670", "text": "Sessions", "entity_id": "ent_167d9c81a16b4925a5ddb8005d404004", "generated_from_name_id": "nam_ac27eef167e14987825de4787fcd29ea", "created_at": "2026-10-22T20:25:25.014Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-22T20:25:25.016Z',NULL,'create','name','nam_09c1bc96bcee4dfba2a60f64ad2910c2',NULL,'{"id": "nam_09c1bc96bcee4dfba2a60f64ad2910c2", "text": "Sign-in", "entity_id": "ent_b3de63e7438f4990a97c9ce5cc8d2746", "generated_from_name_id": null, "created_at": "2026-10-22T20:25:25.015Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-22T20:25:25.016Z',NULL,'create','name','nam_d660168221b3493aaab64f74ee794d07',NULL,'{"id": "nam_d660168221b3493aaab64f74ee794d07", "text": "Sign-ins", "entity_id": "ent_b3de63e7438f4990a97c9ce5cc8d2746", "generated_from_name_id": "nam_09c1bc96bcee4dfba2a60f64ad2910c2", "created_at": "2026-10-22T20:25:25.016Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-22T20:25:25.017Z',NULL,'link','entity_link','ent_b3de63e7438f4990a97c9ce5cc8d2746|ent_167d9c81a16b4925a5ddb8005d404004|contains',NULL,'{"from_entity_id": "ent_b3de63e7438f4990a97c9ce5cc8d2746", "to_entity_id": "ent_167d9c81a16b4925a5ddb8005d404004", "link_type": "contains", "created_at": "2026-10-22T20:25:25.017Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-22T20:25:25.018Z',NULL,'create','statement','stm_75309ed080b94d9181d8bec20792e974',NULL,'{"id": "stm_75309ed080b94d9181d8bec20792e974", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-22T20:25:25.018Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-22T20:25:25.020Z',NULL,'create','statement','stm_541440a851d44bf5a3928b7b9b013c9c',NULL,'{"id": "stm_541440a851d44bf5a3928b7b9b013c9c", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-22T20:25:25.020Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-22T20:25:25.021Z',NULL,'create','statement','stm_4c6565726d3c4f3ba3821e8c5cf54927',NULL,'{"id": "stm_4c6565726d3c4f3ba3821e8c5cf54927", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-22T20:25:25.021Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-22T20:25:25.022Z',NULL,'create','statement','stm_32b38a734c4842169283886576163b46',NULL,'{"id": "stm_32b38a734c4842169283886576163b46", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-22T20:25:25.022Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-22T20:25:25.024Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_75309ed080b94d9181d8bec20792e974", "to_id": "stm_541440a851d44bf5a3928b7b9b013c9c", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_4c6565726d3c4f3ba3821e8c5cf54927"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
