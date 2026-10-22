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
INSERT INTO "history_events" VALUES(1,'2026-10-22T18:38:48.226Z',NULL,'create','entity','ent_5370b0d1b27343a6b0c5d4dd80bf7864',NULL,'{"id": "ent_5370b0d1b27343a6b0c5d4dd80bf7864", "description": "Signing in.", "created_at": "2026-10-22T18:38:48.226Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-22T18:38:48.226Z',NULL,'create','name','nam_dfa25ade261642ddb94678a36ed42cb4',NULL,'{"id": "nam_dfa25ade261642ddb94678a36ed42cb4", "text": "Login", "entity_id": "ent_5370b0d1b27343a6b0c5d4dd80bf7864", "generated_from_name_id": null, "created_at": "2026-10-22T18:38:48.226Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-22T18:38:48.235Z',NULL,'create','name','nam_53c85fbb860843e1b2adeb07b9ed2d3a',NULL,'{"id": "nam_53c85fbb860843e1b2adeb07b9ed2d3a", "text": "Logins", "entity_id": "ent_5370b0d1b27343a6b0c5d4dd80bf7864", "generated_from_name_id": "nam_dfa25ade261642ddb94678a36ed42cb4", "created_at": "2026-10-22T18:38:48.235Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-22T18:38:48.236Z',NULL,'create','entity','ent_192a32ac73564c6389bcd52867210e77',NULL,'{"id": "ent_192a32ac73564c6389bcd52867210e77", "description": "An authenticated visit.", "created_at": "2026-10-22T18:38:48.236Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-22T18:38:48.236Z',NULL,'create','name','nam_e3e2bde084df4b32a893e63efb868fc7',NULL,'{"id": "nam_e3e2bde084df4b32a893e63efb868fc7", "text": "Session", "entity_id": "ent_192a32ac73564c6389bcd52867210e77", "generated_from_name_id": null, "created_at": "2026-10-22T18:38:48.236Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-22T18:38:48.237Z',NULL,'create','name','nam_63c9db4a76604763a23a6964c6fa8eb7',NULL,'{"id": "nam_63c9db4a76604763a23a6964c6fa8eb7", "text": "Sessions", "entity_id": "ent_192a32ac73564c6389bcd52867210e77", "generated_from_name_id": "nam_e3e2bde084df4b32a893e63efb868fc7", "created_at": "2026-10-22T18:38:48.237Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-22T18:38:48.238Z',NULL,'create','name','nam_c314f6205f4c44fda4ec23a0b671af10',NULL,'{"id": "nam_c314f6205f4c44fda4ec23a0b671af10", "text": "Sign-in", "entity_id": "ent_5370b0d1b27343a6b0c5d4dd80bf7864", "generated_from_name_id": null, "created_at": "2026-10-22T18:38:48.238Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-22T18:38:48.238Z',NULL,'create','name','nam_81715337082a448c8d67dd589349eee7',NULL,'{"id": "nam_81715337082a448c8d67dd589349eee7", "text": "Sign-ins", "entity_id": "ent_5370b0d1b27343a6b0c5d4dd80bf7864", "generated_from_name_id": "nam_c314f6205f4c44fda4ec23a0b671af10", "created_at": "2026-10-22T18:38:48.238Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-22T18:38:48.239Z',NULL,'link','entity_link','ent_5370b0d1b27343a6b0c5d4dd80bf7864|ent_192a32ac73564c6389bcd52867210e77|contains',NULL,'{"from_entity_id": "ent_5370b0d1b27343a6b0c5d4dd80bf7864", "to_entity_id": "ent_192a32ac73564c6389bcd52867210e77", "link_type": "contains", "created_at": "2026-10-22T18:38:48.239Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-22T18:38:48.240Z',NULL,'create','statement','stm_385df4b4d030403cbd2c7026daa1d378',NULL,'{"id": "stm_385df4b4d030403cbd2c7026daa1d378", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-22T18:38:48.240Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-22T18:38:48.242Z',NULL,'create','statement','stm_3022193f3cab437c8494ddbb1f299c20',NULL,'{"id": "stm_3022193f3cab437c8494ddbb1f299c20", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-22T18:38:48.242Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-22T18:38:48.243Z',NULL,'create','statement','stm_5e904b01d9cf4ffea4f5396320063496',NULL,'{"id": "stm_5e904b01d9cf4ffea4f5396320063496", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-22T18:38:48.243Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-22T18:38:48.244Z',NULL,'create','statement','stm_aa2e33d2d93b4c7f8ccc26df81acfc4e',NULL,'{"id": "stm_aa2e33d2d93b4c7f8ccc26df81acfc4e", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-22T18:38:48.244Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-22T18:38:48.245Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_385df4b4d030403cbd2c7026daa1d378", "to_id": "stm_3022193f3cab437c8494ddbb1f299c20", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_5e904b01d9cf4ffea4f5396320063496"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',14);
COMMIT;
