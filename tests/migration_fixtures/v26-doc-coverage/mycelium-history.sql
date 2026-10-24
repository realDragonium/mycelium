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
INSERT INTO "history_events" VALUES(1,'2026-10-24T15:36:57.050Z',NULL,'create','entity','ent_ea882c2718e545d1b3a17eae2ef5c2b9',NULL,'{"id": "ent_ea882c2718e545d1b3a17eae2ef5c2b9", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-24T15:36:57.050Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-24T15:36:57.050Z',NULL,'create','name','nam_6a7d5c6bf63e4f88a178fe08548fb8f5',NULL,'{"id": "nam_6a7d5c6bf63e4f88a178fe08548fb8f5", "text": "Login", "entity_id": "ent_ea882c2718e545d1b3a17eae2ef5c2b9", "generated_from_name_id": null, "created_at": "2026-10-24T15:36:57.050Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-24T15:36:57.051Z',NULL,'update','entity','ent_ea882c2718e545d1b3a17eae2ef5c2b9','{"id": "ent_ea882c2718e545d1b3a17eae2ef5c2b9", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-24T15:36:57.050Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_ea882c2718e545d1b3a17eae2ef5c2b9", "description": "Signing in.", "preferred_name_id": "nam_6a7d5c6bf63e4f88a178fe08548fb8f5", "created_at": "2026-10-24T15:36:57.050Z", "updated_at": "2026-10-24T15:36:57.050Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-24T15:36:57.051Z',NULL,'create','name','nam_450be5264bcb4424869c57a9b0d07930',NULL,'{"id": "nam_450be5264bcb4424869c57a9b0d07930", "text": "Logins", "entity_id": "ent_ea882c2718e545d1b3a17eae2ef5c2b9", "generated_from_name_id": "nam_6a7d5c6bf63e4f88a178fe08548fb8f5", "created_at": "2026-10-24T15:36:57.051Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-24T15:36:57.051Z',NULL,'create','entity','ent_8f8528aea47945e5803a0ec06d7896d7',NULL,'{"id": "ent_8f8528aea47945e5803a0ec06d7896d7", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-24T15:36:57.051Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-24T15:36:57.052Z',NULL,'create','name','nam_5d779d2255e045ceb4c06aa7d6fbd915',NULL,'{"id": "nam_5d779d2255e045ceb4c06aa7d6fbd915", "text": "Session", "entity_id": "ent_8f8528aea47945e5803a0ec06d7896d7", "generated_from_name_id": null, "created_at": "2026-10-24T15:36:57.051Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-24T15:36:57.052Z',NULL,'update','entity','ent_8f8528aea47945e5803a0ec06d7896d7','{"id": "ent_8f8528aea47945e5803a0ec06d7896d7", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-24T15:36:57.051Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_8f8528aea47945e5803a0ec06d7896d7", "description": "An authenticated visit.", "preferred_name_id": "nam_5d779d2255e045ceb4c06aa7d6fbd915", "created_at": "2026-10-24T15:36:57.051Z", "updated_at": "2026-10-24T15:36:57.052Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-24T15:36:57.052Z',NULL,'create','name','nam_ee3f9b744894424da6df1d2e0432435d',NULL,'{"id": "nam_ee3f9b744894424da6df1d2e0432435d", "text": "Sessions", "entity_id": "ent_8f8528aea47945e5803a0ec06d7896d7", "generated_from_name_id": "nam_5d779d2255e045ceb4c06aa7d6fbd915", "created_at": "2026-10-24T15:36:57.052Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-24T15:36:57.053Z',NULL,'create','name','nam_3a1eafc63b9a42dc80dffff840488878',NULL,'{"id": "nam_3a1eafc63b9a42dc80dffff840488878", "text": "Sign-in", "entity_id": "ent_ea882c2718e545d1b3a17eae2ef5c2b9", "generated_from_name_id": null, "created_at": "2026-10-24T15:36:57.053Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-24T15:36:57.053Z',NULL,'create','name','nam_93d841c991664575b35f4e61a1320f80',NULL,'{"id": "nam_93d841c991664575b35f4e61a1320f80", "text": "Sign-ins", "entity_id": "ent_ea882c2718e545d1b3a17eae2ef5c2b9", "generated_from_name_id": "nam_3a1eafc63b9a42dc80dffff840488878", "created_at": "2026-10-24T15:36:57.053Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-24T15:36:57.053Z',NULL,'link','entity_link','ent_ea882c2718e545d1b3a17eae2ef5c2b9|ent_8f8528aea47945e5803a0ec06d7896d7|contains',NULL,'{"from_entity_id": "ent_ea882c2718e545d1b3a17eae2ef5c2b9", "to_entity_id": "ent_8f8528aea47945e5803a0ec06d7896d7", "link_type": "contains", "created_at": "2026-10-24T15:36:57.053Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-24T15:36:57.053Z',NULL,'create','statement','stm_af54f18e7cf14d0ba315f2f7bc4d5f13',NULL,'{"id": "stm_af54f18e7cf14d0ba315f2f7bc4d5f13", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-24T15:36:57.053Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-24T15:36:57.054Z',NULL,'create','statement','stm_c24d1293af5c414eb1e5b9e2fa9d2d5c',NULL,'{"id": "stm_c24d1293af5c414eb1e5b9e2fa9d2d5c", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-24T15:36:57.054Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-24T15:36:57.055Z',NULL,'create','statement','stm_89e80a3bc3fd4aefaa85eaf9b4247d13',NULL,'{"id": "stm_89e80a3bc3fd4aefaa85eaf9b4247d13", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-24T15:36:57.054Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-24T15:36:57.055Z',NULL,'create','statement','stm_e968363433f142c1a711a1e97828fdd7',NULL,'{"id": "stm_e968363433f142c1a711a1e97828fdd7", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-24T15:36:57.055Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-24T15:36:57.055Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_af54f18e7cf14d0ba315f2f7bc4d5f13", "to_id": "stm_c24d1293af5c414eb1e5b9e2fa9d2d5c", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_89e80a3bc3fd4aefaa85eaf9b4247d13"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
