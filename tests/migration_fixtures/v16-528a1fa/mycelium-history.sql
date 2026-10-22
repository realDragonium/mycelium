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
INSERT INTO "history_events" VALUES(1,'2026-10-22T20:39:12.946Z',NULL,'create','entity','ent_75345e627c2b4a11aaec420e6d5f1c5b',NULL,'{"id": "ent_75345e627c2b4a11aaec420e6d5f1c5b", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-22T20:39:12.946Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-22T20:39:12.946Z',NULL,'create','name','nam_3b39ac3432a147679ff5d20324f520bd',NULL,'{"id": "nam_3b39ac3432a147679ff5d20324f520bd", "text": "Login", "entity_id": "ent_75345e627c2b4a11aaec420e6d5f1c5b", "generated_from_name_id": null, "created_at": "2026-10-22T20:39:12.946Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-22T20:39:12.946Z',NULL,'update','entity','ent_75345e627c2b4a11aaec420e6d5f1c5b','{"id": "ent_75345e627c2b4a11aaec420e6d5f1c5b", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-22T20:39:12.946Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_75345e627c2b4a11aaec420e6d5f1c5b", "description": "Signing in.", "preferred_name_id": "nam_3b39ac3432a147679ff5d20324f520bd", "created_at": "2026-10-22T20:39:12.946Z", "updated_at": "2026-10-22T20:39:12.946Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-22T20:39:12.955Z',NULL,'create','name','nam_c66b312c7e664991882ddf4f4d118bc1',NULL,'{"id": "nam_c66b312c7e664991882ddf4f4d118bc1", "text": "Logins", "entity_id": "ent_75345e627c2b4a11aaec420e6d5f1c5b", "generated_from_name_id": "nam_3b39ac3432a147679ff5d20324f520bd", "created_at": "2026-10-22T20:39:12.955Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-22T20:39:12.956Z',NULL,'create','entity','ent_42ad3287e879465cae0aa5b37ed9cbe6',NULL,'{"id": "ent_42ad3287e879465cae0aa5b37ed9cbe6", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-22T20:39:12.956Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-22T20:39:12.956Z',NULL,'create','name','nam_088fa873a83644f5bf9980bd0e6e8150',NULL,'{"id": "nam_088fa873a83644f5bf9980bd0e6e8150", "text": "Session", "entity_id": "ent_42ad3287e879465cae0aa5b37ed9cbe6", "generated_from_name_id": null, "created_at": "2026-10-22T20:39:12.956Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-22T20:39:12.957Z',NULL,'update','entity','ent_42ad3287e879465cae0aa5b37ed9cbe6','{"id": "ent_42ad3287e879465cae0aa5b37ed9cbe6", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-22T20:39:12.956Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_42ad3287e879465cae0aa5b37ed9cbe6", "description": "An authenticated visit.", "preferred_name_id": "nam_088fa873a83644f5bf9980bd0e6e8150", "created_at": "2026-10-22T20:39:12.956Z", "updated_at": "2026-10-22T20:39:12.957Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-22T20:39:12.957Z',NULL,'create','name','nam_e5e9c08580ea4af1bc8d2eda6e9c02d3',NULL,'{"id": "nam_e5e9c08580ea4af1bc8d2eda6e9c02d3", "text": "Sessions", "entity_id": "ent_42ad3287e879465cae0aa5b37ed9cbe6", "generated_from_name_id": "nam_088fa873a83644f5bf9980bd0e6e8150", "created_at": "2026-10-22T20:39:12.957Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-22T20:39:12.958Z',NULL,'create','name','nam_2e5caaa0e07a4c7eb31866d64350eb2f',NULL,'{"id": "nam_2e5caaa0e07a4c7eb31866d64350eb2f", "text": "Sign-in", "entity_id": "ent_75345e627c2b4a11aaec420e6d5f1c5b", "generated_from_name_id": null, "created_at": "2026-10-22T20:39:12.958Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-22T20:39:12.958Z',NULL,'create','name','nam_979957ee0514499bb8370a1146148e66',NULL,'{"id": "nam_979957ee0514499bb8370a1146148e66", "text": "Sign-ins", "entity_id": "ent_75345e627c2b4a11aaec420e6d5f1c5b", "generated_from_name_id": "nam_2e5caaa0e07a4c7eb31866d64350eb2f", "created_at": "2026-10-22T20:39:12.958Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-22T20:39:12.959Z',NULL,'link','entity_link','ent_75345e627c2b4a11aaec420e6d5f1c5b|ent_42ad3287e879465cae0aa5b37ed9cbe6|contains',NULL,'{"from_entity_id": "ent_75345e627c2b4a11aaec420e6d5f1c5b", "to_entity_id": "ent_42ad3287e879465cae0aa5b37ed9cbe6", "link_type": "contains", "created_at": "2026-10-22T20:39:12.959Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-22T20:39:12.960Z',NULL,'create','statement','stm_a8cef95380f747438e4bad93b387f108',NULL,'{"id": "stm_a8cef95380f747438e4bad93b387f108", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-22T20:39:12.960Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-22T20:39:12.962Z',NULL,'create','statement','stm_b1c2c098b5ed43cfb990318ded2ddad8',NULL,'{"id": "stm_b1c2c098b5ed43cfb990318ded2ddad8", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-22T20:39:12.962Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-22T20:39:12.963Z',NULL,'create','statement','stm_139b7ed9c4e943af83ec70fd271ceee4',NULL,'{"id": "stm_139b7ed9c4e943af83ec70fd271ceee4", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-22T20:39:12.963Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-22T20:39:12.964Z',NULL,'create','statement','stm_171fa57916a2407698843bd88703c322',NULL,'{"id": "stm_171fa57916a2407698843bd88703c322", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-22T20:39:12.964Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-22T20:39:12.966Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_a8cef95380f747438e4bad93b387f108", "to_id": "stm_b1c2c098b5ed43cfb990318ded2ddad8", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_139b7ed9c4e943af83ec70fd271ceee4"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
