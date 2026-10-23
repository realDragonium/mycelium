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
INSERT INTO "history_events" VALUES(1,'2026-10-23T19:22:31.755Z',NULL,'create','entity','ent_00ba705738cc4cee9edbf09b3bf4c183',NULL,'{"id": "ent_00ba705738cc4cee9edbf09b3bf4c183", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T19:22:31.755Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-23T19:22:31.755Z',NULL,'create','name','nam_6d05bbdb0f04407d88bb046cfe8a42b5',NULL,'{"id": "nam_6d05bbdb0f04407d88bb046cfe8a42b5", "text": "Login", "entity_id": "ent_00ba705738cc4cee9edbf09b3bf4c183", "generated_from_name_id": null, "created_at": "2026-10-23T19:22:31.755Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-23T19:22:31.755Z',NULL,'update','entity','ent_00ba705738cc4cee9edbf09b3bf4c183','{"id": "ent_00ba705738cc4cee9edbf09b3bf4c183", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T19:22:31.755Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_00ba705738cc4cee9edbf09b3bf4c183", "description": "Signing in.", "preferred_name_id": "nam_6d05bbdb0f04407d88bb046cfe8a42b5", "created_at": "2026-10-23T19:22:31.755Z", "updated_at": "2026-10-23T19:22:31.755Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-23T19:22:31.768Z',NULL,'create','name','nam_0f0cc19b6081454c9a00a5e006854cf2',NULL,'{"id": "nam_0f0cc19b6081454c9a00a5e006854cf2", "text": "Logins", "entity_id": "ent_00ba705738cc4cee9edbf09b3bf4c183", "generated_from_name_id": "nam_6d05bbdb0f04407d88bb046cfe8a42b5", "created_at": "2026-10-23T19:22:31.768Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-23T19:22:31.771Z',NULL,'create','entity','ent_6cb3c07edd08407295b9aebc6d8178ce',NULL,'{"id": "ent_6cb3c07edd08407295b9aebc6d8178ce", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T19:22:31.770Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-23T19:22:31.771Z',NULL,'create','name','nam_5df3c59da9ee4784a0e8035d45ebfc2c',NULL,'{"id": "nam_5df3c59da9ee4784a0e8035d45ebfc2c", "text": "Session", "entity_id": "ent_6cb3c07edd08407295b9aebc6d8178ce", "generated_from_name_id": null, "created_at": "2026-10-23T19:22:31.771Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-23T19:22:31.771Z',NULL,'update','entity','ent_6cb3c07edd08407295b9aebc6d8178ce','{"id": "ent_6cb3c07edd08407295b9aebc6d8178ce", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T19:22:31.770Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_6cb3c07edd08407295b9aebc6d8178ce", "description": "An authenticated visit.", "preferred_name_id": "nam_5df3c59da9ee4784a0e8035d45ebfc2c", "created_at": "2026-10-23T19:22:31.770Z", "updated_at": "2026-10-23T19:22:31.771Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-23T19:22:31.771Z',NULL,'create','name','nam_e6f10e85ca4f42b9a4d41295d92cd456',NULL,'{"id": "nam_e6f10e85ca4f42b9a4d41295d92cd456", "text": "Sessions", "entity_id": "ent_6cb3c07edd08407295b9aebc6d8178ce", "generated_from_name_id": "nam_5df3c59da9ee4784a0e8035d45ebfc2c", "created_at": "2026-10-23T19:22:31.771Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-23T19:22:31.775Z',NULL,'create','name','nam_ca3489f494d844569459f71093720b58',NULL,'{"id": "nam_ca3489f494d844569459f71093720b58", "text": "Sign-in", "entity_id": "ent_00ba705738cc4cee9edbf09b3bf4c183", "generated_from_name_id": null, "created_at": "2026-10-23T19:22:31.775Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-23T19:22:31.776Z',NULL,'create','name','nam_7a3065b457954951ad2058cc4ee2f355',NULL,'{"id": "nam_7a3065b457954951ad2058cc4ee2f355", "text": "Sign-ins", "entity_id": "ent_00ba705738cc4cee9edbf09b3bf4c183", "generated_from_name_id": "nam_ca3489f494d844569459f71093720b58", "created_at": "2026-10-23T19:22:31.776Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-23T19:22:31.776Z',NULL,'link','entity_link','ent_00ba705738cc4cee9edbf09b3bf4c183|ent_6cb3c07edd08407295b9aebc6d8178ce|contains',NULL,'{"from_entity_id": "ent_00ba705738cc4cee9edbf09b3bf4c183", "to_entity_id": "ent_6cb3c07edd08407295b9aebc6d8178ce", "link_type": "contains", "created_at": "2026-10-23T19:22:31.776Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-23T19:22:31.778Z',NULL,'create','statement','stm_3bc3d4511a6e42e6b207329c996b9df9',NULL,'{"id": "stm_3bc3d4511a6e42e6b207329c996b9df9", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-23T19:22:31.778Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-23T19:22:31.779Z',NULL,'create','statement','stm_4bee664c19794630b37bed25478311cd',NULL,'{"id": "stm_4bee664c19794630b37bed25478311cd", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-23T19:22:31.779Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-23T19:22:31.780Z',NULL,'create','statement','stm_03891c04372d451196074896c8638869',NULL,'{"id": "stm_03891c04372d451196074896c8638869", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-23T19:22:31.780Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-23T19:22:31.785Z',NULL,'create','statement','stm_874090d1aaf043e49af8a773035fb6b6',NULL,'{"id": "stm_874090d1aaf043e49af8a773035fb6b6", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-23T19:22:31.785Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-23T19:22:31.786Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_3bc3d4511a6e42e6b207329c996b9df9", "to_id": "stm_4bee664c19794630b37bed25478311cd", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_03891c04372d451196074896c8638869"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
