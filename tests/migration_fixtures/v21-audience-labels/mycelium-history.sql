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
INSERT INTO "history_events" VALUES(1,'2026-10-23T09:35:02.506Z',NULL,'create','entity','ent_0d66052b03684f18be55f64085a11e10',NULL,'{"id": "ent_0d66052b03684f18be55f64085a11e10", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T09:35:02.506Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-23T09:35:02.506Z',NULL,'create','name','nam_ddfc2d7478a7499984c16c993c594702',NULL,'{"id": "nam_ddfc2d7478a7499984c16c993c594702", "text": "Login", "entity_id": "ent_0d66052b03684f18be55f64085a11e10", "generated_from_name_id": null, "created_at": "2026-10-23T09:35:02.506Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-23T09:35:02.506Z',NULL,'update','entity','ent_0d66052b03684f18be55f64085a11e10','{"id": "ent_0d66052b03684f18be55f64085a11e10", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T09:35:02.506Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_0d66052b03684f18be55f64085a11e10", "description": "Signing in.", "preferred_name_id": "nam_ddfc2d7478a7499984c16c993c594702", "created_at": "2026-10-23T09:35:02.506Z", "updated_at": "2026-10-23T09:35:02.506Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-23T09:35:02.510Z',NULL,'create','name','nam_e6ddcea976684b2cadaf89bd9094c2d0',NULL,'{"id": "nam_e6ddcea976684b2cadaf89bd9094c2d0", "text": "Logins", "entity_id": "ent_0d66052b03684f18be55f64085a11e10", "generated_from_name_id": "nam_ddfc2d7478a7499984c16c993c594702", "created_at": "2026-10-23T09:35:02.510Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-23T09:35:02.510Z',NULL,'create','entity','ent_1d0271ee97c245fdbcbea3e021cadd32',NULL,'{"id": "ent_1d0271ee97c245fdbcbea3e021cadd32", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T09:35:02.510Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-23T09:35:02.510Z',NULL,'create','name','nam_3555bb21e2764adb916f58f8ad72a1b4',NULL,'{"id": "nam_3555bb21e2764adb916f58f8ad72a1b4", "text": "Session", "entity_id": "ent_1d0271ee97c245fdbcbea3e021cadd32", "generated_from_name_id": null, "created_at": "2026-10-23T09:35:02.510Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-23T09:35:02.510Z',NULL,'update','entity','ent_1d0271ee97c245fdbcbea3e021cadd32','{"id": "ent_1d0271ee97c245fdbcbea3e021cadd32", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T09:35:02.510Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_1d0271ee97c245fdbcbea3e021cadd32", "description": "An authenticated visit.", "preferred_name_id": "nam_3555bb21e2764adb916f58f8ad72a1b4", "created_at": "2026-10-23T09:35:02.510Z", "updated_at": "2026-10-23T09:35:02.510Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-23T09:35:02.510Z',NULL,'create','name','nam_ab944a23aa4241e49eeccbaf37a32340',NULL,'{"id": "nam_ab944a23aa4241e49eeccbaf37a32340", "text": "Sessions", "entity_id": "ent_1d0271ee97c245fdbcbea3e021cadd32", "generated_from_name_id": "nam_3555bb21e2764adb916f58f8ad72a1b4", "created_at": "2026-10-23T09:35:02.510Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-23T09:35:02.511Z',NULL,'create','name','nam_a61c947eb1204ec08b74f960ab0d7675',NULL,'{"id": "nam_a61c947eb1204ec08b74f960ab0d7675", "text": "Sign-in", "entity_id": "ent_0d66052b03684f18be55f64085a11e10", "generated_from_name_id": null, "created_at": "2026-10-23T09:35:02.511Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-23T09:35:02.511Z',NULL,'create','name','nam_d18bf9aaa45445d79d4afd4cc633939c',NULL,'{"id": "nam_d18bf9aaa45445d79d4afd4cc633939c", "text": "Sign-ins", "entity_id": "ent_0d66052b03684f18be55f64085a11e10", "generated_from_name_id": "nam_a61c947eb1204ec08b74f960ab0d7675", "created_at": "2026-10-23T09:35:02.511Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-23T09:35:02.511Z',NULL,'link','entity_link','ent_0d66052b03684f18be55f64085a11e10|ent_1d0271ee97c245fdbcbea3e021cadd32|contains',NULL,'{"from_entity_id": "ent_0d66052b03684f18be55f64085a11e10", "to_entity_id": "ent_1d0271ee97c245fdbcbea3e021cadd32", "link_type": "contains", "created_at": "2026-10-23T09:35:02.511Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-23T09:35:02.511Z',NULL,'create','statement','stm_fe49a3bb1bd3409686d4486fbc0da147',NULL,'{"id": "stm_fe49a3bb1bd3409686d4486fbc0da147", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-23T09:35:02.511Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-23T09:35:02.512Z',NULL,'create','statement','stm_039ae371f9c845e38200373719a92f11',NULL,'{"id": "stm_039ae371f9c845e38200373719a92f11", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-23T09:35:02.512Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-23T09:35:02.513Z',NULL,'create','statement','stm_ee1381ccfa894fa2928d4a859f427319',NULL,'{"id": "stm_ee1381ccfa894fa2928d4a859f427319", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-23T09:35:02.513Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-23T09:35:02.513Z',NULL,'create','statement','stm_24f1c2ed13294ef2b2eaa48be33e053c',NULL,'{"id": "stm_24f1c2ed13294ef2b2eaa48be33e053c", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-23T09:35:02.513Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-23T09:35:02.514Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_fe49a3bb1bd3409686d4486fbc0da147", "to_id": "stm_039ae371f9c845e38200373719a92f11", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_ee1381ccfa894fa2928d4a859f427319"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
