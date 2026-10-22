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
INSERT INTO "history_events" VALUES(1,'2026-10-22T19:10:53.574Z',NULL,'create','entity','ent_0d3ed46a0ac84572a32425adf681be76',NULL,'{"id": "ent_0d3ed46a0ac84572a32425adf681be76", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-22T19:10:53.574Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-22T19:10:53.574Z',NULL,'create','name','nam_c8920d17405441f4bb8b53bb06f90340',NULL,'{"id": "nam_c8920d17405441f4bb8b53bb06f90340", "text": "Login", "entity_id": "ent_0d3ed46a0ac84572a32425adf681be76", "generated_from_name_id": null, "created_at": "2026-10-22T19:10:53.574Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-22T19:10:53.574Z',NULL,'update','entity','ent_0d3ed46a0ac84572a32425adf681be76','{"id": "ent_0d3ed46a0ac84572a32425adf681be76", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-22T19:10:53.574Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_0d3ed46a0ac84572a32425adf681be76", "description": "Signing in.", "preferred_name_id": "nam_c8920d17405441f4bb8b53bb06f90340", "created_at": "2026-10-22T19:10:53.574Z", "updated_at": "2026-10-22T19:10:53.574Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-22T19:10:53.583Z',NULL,'create','name','nam_fe3b90b57b8e40689d20f86cfe1e210c',NULL,'{"id": "nam_fe3b90b57b8e40689d20f86cfe1e210c", "text": "Logins", "entity_id": "ent_0d3ed46a0ac84572a32425adf681be76", "generated_from_name_id": "nam_c8920d17405441f4bb8b53bb06f90340", "created_at": "2026-10-22T19:10:53.583Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-22T19:10:53.584Z',NULL,'create','entity','ent_cfdd692f24ea4979a5d1e8b07a0a4b0b',NULL,'{"id": "ent_cfdd692f24ea4979a5d1e8b07a0a4b0b", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-22T19:10:53.584Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-22T19:10:53.585Z',NULL,'create','name','nam_9175ff9788b241398d1feb56ee8d802e',NULL,'{"id": "nam_9175ff9788b241398d1feb56ee8d802e", "text": "Session", "entity_id": "ent_cfdd692f24ea4979a5d1e8b07a0a4b0b", "generated_from_name_id": null, "created_at": "2026-10-22T19:10:53.584Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-22T19:10:53.585Z',NULL,'update','entity','ent_cfdd692f24ea4979a5d1e8b07a0a4b0b','{"id": "ent_cfdd692f24ea4979a5d1e8b07a0a4b0b", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-22T19:10:53.584Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_cfdd692f24ea4979a5d1e8b07a0a4b0b", "description": "An authenticated visit.", "preferred_name_id": "nam_9175ff9788b241398d1feb56ee8d802e", "created_at": "2026-10-22T19:10:53.584Z", "updated_at": "2026-10-22T19:10:53.585Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-22T19:10:53.585Z',NULL,'create','name','nam_71729abe63cf4bb6b3bd5f20e89c08f7',NULL,'{"id": "nam_71729abe63cf4bb6b3bd5f20e89c08f7", "text": "Sessions", "entity_id": "ent_cfdd692f24ea4979a5d1e8b07a0a4b0b", "generated_from_name_id": "nam_9175ff9788b241398d1feb56ee8d802e", "created_at": "2026-10-22T19:10:53.585Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-22T19:10:53.586Z',NULL,'create','name','nam_3fbb78d85d274f328fe10bfb00e20e7e',NULL,'{"id": "nam_3fbb78d85d274f328fe10bfb00e20e7e", "text": "Sign-in", "entity_id": "ent_0d3ed46a0ac84572a32425adf681be76", "generated_from_name_id": null, "created_at": "2026-10-22T19:10:53.586Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-22T19:10:53.586Z',NULL,'create','name','nam_b74775f53d70453b9b3c038089901323',NULL,'{"id": "nam_b74775f53d70453b9b3c038089901323", "text": "Sign-ins", "entity_id": "ent_0d3ed46a0ac84572a32425adf681be76", "generated_from_name_id": "nam_3fbb78d85d274f328fe10bfb00e20e7e", "created_at": "2026-10-22T19:10:53.586Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-22T19:10:53.587Z',NULL,'link','entity_link','ent_0d3ed46a0ac84572a32425adf681be76|ent_cfdd692f24ea4979a5d1e8b07a0a4b0b|contains',NULL,'{"from_entity_id": "ent_0d3ed46a0ac84572a32425adf681be76", "to_entity_id": "ent_cfdd692f24ea4979a5d1e8b07a0a4b0b", "link_type": "contains", "created_at": "2026-10-22T19:10:53.587Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-22T19:10:53.588Z',NULL,'create','statement','stm_cb95c66b0eff4dbf9783ad1e843e6b15',NULL,'{"id": "stm_cb95c66b0eff4dbf9783ad1e843e6b15", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-22T19:10:53.588Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-22T19:10:53.589Z',NULL,'create','statement','stm_61758f8e880c44aaa76f41297cd00b5c',NULL,'{"id": "stm_61758f8e880c44aaa76f41297cd00b5c", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-22T19:10:53.589Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-22T19:10:53.591Z',NULL,'create','statement','stm_37cd108a27bb4bf387f96cec0fd4371c',NULL,'{"id": "stm_37cd108a27bb4bf387f96cec0fd4371c", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-22T19:10:53.591Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-22T19:10:53.592Z',NULL,'create','statement','stm_d4459feadec2491cb3a386eb489b7b5a',NULL,'{"id": "stm_d4459feadec2491cb3a386eb489b7b5a", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-22T19:10:53.592Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-22T19:10:53.593Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_cb95c66b0eff4dbf9783ad1e843e6b15", "to_id": "stm_61758f8e880c44aaa76f41297cd00b5c", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_37cd108a27bb4bf387f96cec0fd4371c"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
