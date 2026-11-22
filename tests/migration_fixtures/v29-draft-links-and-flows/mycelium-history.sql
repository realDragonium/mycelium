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
INSERT INTO "history_events" VALUES(1,'2026-11-21T18:51:06.334Z',NULL,'create','entity','ent_330a78fed6de4b8eac7f1336946cb0c5',NULL,'{"id": "ent_330a78fed6de4b8eac7f1336946cb0c5", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-11-21T18:51:06.334Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-11-21T18:51:06.335Z',NULL,'create','name','nam_7ed1481c568e4b4c8170f940ec1a1c35',NULL,'{"id": "nam_7ed1481c568e4b4c8170f940ec1a1c35", "text": "Login", "entity_id": "ent_330a78fed6de4b8eac7f1336946cb0c5", "generated_from_name_id": null, "created_at": "2026-11-21T18:51:06.334Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-11-21T18:51:06.336Z',NULL,'update','entity','ent_330a78fed6de4b8eac7f1336946cb0c5','{"id": "ent_330a78fed6de4b8eac7f1336946cb0c5", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-11-21T18:51:06.334Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_330a78fed6de4b8eac7f1336946cb0c5", "description": "Signing in.", "preferred_name_id": "nam_7ed1481c568e4b4c8170f940ec1a1c35", "created_at": "2026-11-21T18:51:06.334Z", "updated_at": "2026-11-21T18:51:06.335Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-11-21T18:51:06.337Z',NULL,'create','name','nam_c0dc083749274b5abb0376a4fa4cef88',NULL,'{"id": "nam_c0dc083749274b5abb0376a4fa4cef88", "text": "Logins", "entity_id": "ent_330a78fed6de4b8eac7f1336946cb0c5", "generated_from_name_id": "nam_7ed1481c568e4b4c8170f940ec1a1c35", "created_at": "2026-11-21T18:51:06.337Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-11-21T18:51:06.338Z',NULL,'create','entity','ent_2cb718fe0a0c49e39b888697582f3639',NULL,'{"id": "ent_2cb718fe0a0c49e39b888697582f3639", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-11-21T18:51:06.338Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-11-21T18:51:06.339Z',NULL,'create','name','nam_2db32db7d2d4453881b6836f8b61f5a9',NULL,'{"id": "nam_2db32db7d2d4453881b6836f8b61f5a9", "text": "Session", "entity_id": "ent_2cb718fe0a0c49e39b888697582f3639", "generated_from_name_id": null, "created_at": "2026-11-21T18:51:06.339Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-11-21T18:51:06.339Z',NULL,'update','entity','ent_2cb718fe0a0c49e39b888697582f3639','{"id": "ent_2cb718fe0a0c49e39b888697582f3639", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-11-21T18:51:06.338Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_2cb718fe0a0c49e39b888697582f3639", "description": "An authenticated visit.", "preferred_name_id": "nam_2db32db7d2d4453881b6836f8b61f5a9", "created_at": "2026-11-21T18:51:06.338Z", "updated_at": "2026-11-21T18:51:06.339Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-11-21T18:51:06.339Z',NULL,'create','name','nam_72293ca4806b45d7ae7e7fcbc42a6ba6',NULL,'{"id": "nam_72293ca4806b45d7ae7e7fcbc42a6ba6", "text": "Sessions", "entity_id": "ent_2cb718fe0a0c49e39b888697582f3639", "generated_from_name_id": "nam_2db32db7d2d4453881b6836f8b61f5a9", "created_at": "2026-11-21T18:51:06.339Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-11-21T18:51:06.340Z',NULL,'create','name','nam_4073808b63854d53a337627b140cb9c7',NULL,'{"id": "nam_4073808b63854d53a337627b140cb9c7", "text": "Sign-in", "entity_id": "ent_330a78fed6de4b8eac7f1336946cb0c5", "generated_from_name_id": null, "created_at": "2026-11-21T18:51:06.340Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-11-21T18:51:06.340Z',NULL,'create','name','nam_37a7fc97a2b149cd924f1aa85fb31d54',NULL,'{"id": "nam_37a7fc97a2b149cd924f1aa85fb31d54", "text": "Sign-ins", "entity_id": "ent_330a78fed6de4b8eac7f1336946cb0c5", "generated_from_name_id": "nam_4073808b63854d53a337627b140cb9c7", "created_at": "2026-11-21T18:51:06.340Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-11-21T18:51:06.341Z',NULL,'link','entity_link','ent_330a78fed6de4b8eac7f1336946cb0c5|ent_2cb718fe0a0c49e39b888697582f3639|contains',NULL,'{"from_entity_id": "ent_330a78fed6de4b8eac7f1336946cb0c5", "to_entity_id": "ent_2cb718fe0a0c49e39b888697582f3639", "link_type": "contains", "created_at": "2026-11-21T18:51:06.341Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-11-21T18:51:06.342Z',NULL,'create','statement','stm_d2aca38403604bdc9a50af2e428cbbb6',NULL,'{"id": "stm_d2aca38403604bdc9a50af2e428cbbb6", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-11-21T18:51:06.342Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-11-21T18:51:06.344Z',NULL,'create','statement','stm_1a87b7bf4e60436c8de8e429b7645a53',NULL,'{"id": "stm_1a87b7bf4e60436c8de8e429b7645a53", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-11-21T18:51:06.344Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-11-21T18:51:06.345Z',NULL,'create','statement','stm_65584c994b3e4565834e45af02fe15d1',NULL,'{"id": "stm_65584c994b3e4565834e45af02fe15d1", "kind": "state", "text": "The account is locked.", "created_at": "2026-11-21T18:51:06.345Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-11-21T18:51:06.346Z',NULL,'create','statement','stm_fae1821acbea4613b537d3781506cfcd',NULL,'{"id": "stm_fae1821acbea4613b537d3781506cfcd", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-11-21T18:51:06.346Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-11-21T18:51:06.347Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_d2aca38403604bdc9a50af2e428cbbb6", "to_id": "stm_1a87b7bf4e60436c8de8e429b7645a53", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_65584c994b3e4565834e45af02fe15d1"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
