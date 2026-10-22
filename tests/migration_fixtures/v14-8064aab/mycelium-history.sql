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
INSERT INTO "history_events" VALUES(1,'2026-10-22T18:24:09.049Z',NULL,'create','entity','ent_248dc719afe9488ba3de95ca219814dc',NULL,'{"id": "ent_248dc719afe9488ba3de95ca219814dc", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-22T18:24:09.049Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-22T18:24:09.049Z',NULL,'create','name','nam_db918f3848ce44ee8babb27b6d5dcd32',NULL,'{"id": "nam_db918f3848ce44ee8babb27b6d5dcd32", "text": "Login", "entity_id": "ent_248dc719afe9488ba3de95ca219814dc", "generated_from_name_id": null, "created_at": "2026-10-22T18:24:09.049Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-22T18:24:09.049Z',NULL,'update','entity','ent_248dc719afe9488ba3de95ca219814dc','{"id": "ent_248dc719afe9488ba3de95ca219814dc", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-22T18:24:09.049Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_248dc719afe9488ba3de95ca219814dc", "description": "Signing in.", "preferred_name_id": "nam_db918f3848ce44ee8babb27b6d5dcd32", "created_at": "2026-10-22T18:24:09.049Z", "updated_at": "2026-10-22T18:24:09.049Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-22T18:24:09.058Z',NULL,'create','name','nam_5868a8522d8241b4a4aecd6486cfc308',NULL,'{"id": "nam_5868a8522d8241b4a4aecd6486cfc308", "text": "Logins", "entity_id": "ent_248dc719afe9488ba3de95ca219814dc", "generated_from_name_id": "nam_db918f3848ce44ee8babb27b6d5dcd32", "created_at": "2026-10-22T18:24:09.058Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-22T18:24:09.060Z',NULL,'create','entity','ent_c551e80555104fcb89f86e0a9c45a3f4',NULL,'{"id": "ent_c551e80555104fcb89f86e0a9c45a3f4", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-22T18:24:09.060Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-22T18:24:09.061Z',NULL,'create','name','nam_e7c85acceb4e4a358837793a61040645',NULL,'{"id": "nam_e7c85acceb4e4a358837793a61040645", "text": "Session", "entity_id": "ent_c551e80555104fcb89f86e0a9c45a3f4", "generated_from_name_id": null, "created_at": "2026-10-22T18:24:09.061Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-22T18:24:09.061Z',NULL,'update','entity','ent_c551e80555104fcb89f86e0a9c45a3f4','{"id": "ent_c551e80555104fcb89f86e0a9c45a3f4", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-22T18:24:09.060Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_c551e80555104fcb89f86e0a9c45a3f4", "description": "An authenticated visit.", "preferred_name_id": "nam_e7c85acceb4e4a358837793a61040645", "created_at": "2026-10-22T18:24:09.060Z", "updated_at": "2026-10-22T18:24:09.061Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-22T18:24:09.061Z',NULL,'create','name','nam_d30ea869880f41d2b84662e9bf1350ab',NULL,'{"id": "nam_d30ea869880f41d2b84662e9bf1350ab", "text": "Sessions", "entity_id": "ent_c551e80555104fcb89f86e0a9c45a3f4", "generated_from_name_id": "nam_e7c85acceb4e4a358837793a61040645", "created_at": "2026-10-22T18:24:09.061Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-22T18:24:09.062Z',NULL,'create','name','nam_523c9b4137e1400992da110933304bba',NULL,'{"id": "nam_523c9b4137e1400992da110933304bba", "text": "Sign-in", "entity_id": "ent_248dc719afe9488ba3de95ca219814dc", "generated_from_name_id": null, "created_at": "2026-10-22T18:24:09.062Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-22T18:24:09.063Z',NULL,'create','name','nam_b9c2dca8568347faafd48dd4ce755696',NULL,'{"id": "nam_b9c2dca8568347faafd48dd4ce755696", "text": "Sign-ins", "entity_id": "ent_248dc719afe9488ba3de95ca219814dc", "generated_from_name_id": "nam_523c9b4137e1400992da110933304bba", "created_at": "2026-10-22T18:24:09.063Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-22T18:24:09.064Z',NULL,'link','entity_link','ent_248dc719afe9488ba3de95ca219814dc|ent_c551e80555104fcb89f86e0a9c45a3f4|contains',NULL,'{"from_entity_id": "ent_248dc719afe9488ba3de95ca219814dc", "to_entity_id": "ent_c551e80555104fcb89f86e0a9c45a3f4", "link_type": "contains", "created_at": "2026-10-22T18:24:09.064Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-22T18:24:09.065Z',NULL,'create','statement','stm_228e3a0461614d9692612a7e3ba5c0e9',NULL,'{"id": "stm_228e3a0461614d9692612a7e3ba5c0e9", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-22T18:24:09.065Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-22T18:24:09.066Z',NULL,'create','statement','stm_f4cf8731c7b64bb88a85d094958659e9',NULL,'{"id": "stm_f4cf8731c7b64bb88a85d094958659e9", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-22T18:24:09.066Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-22T18:24:09.068Z',NULL,'create','statement','stm_8d429815235446f1b7a9ca8fe915d534',NULL,'{"id": "stm_8d429815235446f1b7a9ca8fe915d534", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-22T18:24:09.068Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-22T18:24:09.070Z',NULL,'create','statement','stm_086986c91b184e389e4bb4677bfeb02a',NULL,'{"id": "stm_086986c91b184e389e4bb4677bfeb02a", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-22T18:24:09.070Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-22T18:24:09.071Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_228e3a0461614d9692612a7e3ba5c0e9", "to_id": "stm_f4cf8731c7b64bb88a85d094958659e9", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_8d429815235446f1b7a9ca8fe915d534"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
