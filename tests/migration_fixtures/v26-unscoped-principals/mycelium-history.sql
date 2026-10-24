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
INSERT INTO "history_events" VALUES(1,'2026-10-24T12:17:28.198Z',NULL,'create','entity','ent_7592c6f1894f4631ac812c6215fe1430',NULL,'{"id": "ent_7592c6f1894f4631ac812c6215fe1430", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-24T12:17:28.198Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-24T12:17:28.198Z',NULL,'create','name','nam_6f61c270fb7b44e4a5803d80e6a70069',NULL,'{"id": "nam_6f61c270fb7b44e4a5803d80e6a70069", "text": "Login", "entity_id": "ent_7592c6f1894f4631ac812c6215fe1430", "generated_from_name_id": null, "created_at": "2026-10-24T12:17:28.198Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-24T12:17:28.198Z',NULL,'update','entity','ent_7592c6f1894f4631ac812c6215fe1430','{"id": "ent_7592c6f1894f4631ac812c6215fe1430", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-24T12:17:28.198Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_7592c6f1894f4631ac812c6215fe1430", "description": "Signing in.", "preferred_name_id": "nam_6f61c270fb7b44e4a5803d80e6a70069", "created_at": "2026-10-24T12:17:28.198Z", "updated_at": "2026-10-24T12:17:28.198Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-24T12:17:28.198Z',NULL,'create','name','nam_23bf1c8192aa40cd939ba98df76a6875',NULL,'{"id": "nam_23bf1c8192aa40cd939ba98df76a6875", "text": "Logins", "entity_id": "ent_7592c6f1894f4631ac812c6215fe1430", "generated_from_name_id": "nam_6f61c270fb7b44e4a5803d80e6a70069", "created_at": "2026-10-24T12:17:28.198Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-24T12:17:28.199Z',NULL,'create','entity','ent_b3f69a3193764f7cac128d9226e0add9',NULL,'{"id": "ent_b3f69a3193764f7cac128d9226e0add9", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-24T12:17:28.199Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-24T12:17:28.199Z',NULL,'create','name','nam_49797af65768495196ad4ffa16fea164',NULL,'{"id": "nam_49797af65768495196ad4ffa16fea164", "text": "Session", "entity_id": "ent_b3f69a3193764f7cac128d9226e0add9", "generated_from_name_id": null, "created_at": "2026-10-24T12:17:28.199Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-24T12:17:28.199Z',NULL,'update','entity','ent_b3f69a3193764f7cac128d9226e0add9','{"id": "ent_b3f69a3193764f7cac128d9226e0add9", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-24T12:17:28.199Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_b3f69a3193764f7cac128d9226e0add9", "description": "An authenticated visit.", "preferred_name_id": "nam_49797af65768495196ad4ffa16fea164", "created_at": "2026-10-24T12:17:28.199Z", "updated_at": "2026-10-24T12:17:28.199Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-24T12:17:28.199Z',NULL,'create','name','nam_ad7b11abb9ac4d98a30e242107388353',NULL,'{"id": "nam_ad7b11abb9ac4d98a30e242107388353", "text": "Sessions", "entity_id": "ent_b3f69a3193764f7cac128d9226e0add9", "generated_from_name_id": "nam_49797af65768495196ad4ffa16fea164", "created_at": "2026-10-24T12:17:28.199Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-24T12:17:28.200Z',NULL,'create','name','nam_e4cc0893ee244c08af4c1de96330f8fc',NULL,'{"id": "nam_e4cc0893ee244c08af4c1de96330f8fc", "text": "Sign-in", "entity_id": "ent_7592c6f1894f4631ac812c6215fe1430", "generated_from_name_id": null, "created_at": "2026-10-24T12:17:28.200Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-24T12:17:28.200Z',NULL,'create','name','nam_31bf3c6a6a424a37afef97e62eee94ef',NULL,'{"id": "nam_31bf3c6a6a424a37afef97e62eee94ef", "text": "Sign-ins", "entity_id": "ent_7592c6f1894f4631ac812c6215fe1430", "generated_from_name_id": "nam_e4cc0893ee244c08af4c1de96330f8fc", "created_at": "2026-10-24T12:17:28.200Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-24T12:17:28.200Z',NULL,'link','entity_link','ent_7592c6f1894f4631ac812c6215fe1430|ent_b3f69a3193764f7cac128d9226e0add9|contains',NULL,'{"from_entity_id": "ent_7592c6f1894f4631ac812c6215fe1430", "to_entity_id": "ent_b3f69a3193764f7cac128d9226e0add9", "link_type": "contains", "created_at": "2026-10-24T12:17:28.200Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-24T12:17:28.201Z',NULL,'create','statement','stm_ce7e76d076964c999560d8b33d95a645',NULL,'{"id": "stm_ce7e76d076964c999560d8b33d95a645", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-24T12:17:28.201Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-24T12:17:28.201Z',NULL,'create','statement','stm_46756f35d9c14ccab42f90904d9a0b63',NULL,'{"id": "stm_46756f35d9c14ccab42f90904d9a0b63", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-24T12:17:28.201Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-24T12:17:28.202Z',NULL,'create','statement','stm_63602436288d409491088c673cd93d3f',NULL,'{"id": "stm_63602436288d409491088c673cd93d3f", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-24T12:17:28.202Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-24T12:17:28.202Z',NULL,'create','statement','stm_e9b4da48c0bb4e61b54912ddcbd713d8',NULL,'{"id": "stm_e9b4da48c0bb4e61b54912ddcbd713d8", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-24T12:17:28.202Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-24T12:17:28.203Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_ce7e76d076964c999560d8b33d95a645", "to_id": "stm_46756f35d9c14ccab42f90904d9a0b63", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_63602436288d409491088c673cd93d3f"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
