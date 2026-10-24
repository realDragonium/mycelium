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
INSERT INTO "history_events" VALUES(1,'2026-10-24T05:51:09.500Z',NULL,'create','entity','ent_b4410d5f20cd4e70ba4ebb461e00103a',NULL,'{"id": "ent_b4410d5f20cd4e70ba4ebb461e00103a", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-24T05:51:09.500Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-24T05:51:09.500Z',NULL,'create','name','nam_bdd2a330a13f430d8e8fb96dc150b28e',NULL,'{"id": "nam_bdd2a330a13f430d8e8fb96dc150b28e", "text": "Login", "entity_id": "ent_b4410d5f20cd4e70ba4ebb461e00103a", "generated_from_name_id": null, "created_at": "2026-10-24T05:51:09.500Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-24T05:51:09.500Z',NULL,'update','entity','ent_b4410d5f20cd4e70ba4ebb461e00103a','{"id": "ent_b4410d5f20cd4e70ba4ebb461e00103a", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-24T05:51:09.500Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_b4410d5f20cd4e70ba4ebb461e00103a", "description": "Signing in.", "preferred_name_id": "nam_bdd2a330a13f430d8e8fb96dc150b28e", "created_at": "2026-10-24T05:51:09.500Z", "updated_at": "2026-10-24T05:51:09.500Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-24T05:51:09.500Z',NULL,'create','name','nam_d955a3bee9b24f98b0c38e2c7eec98b0',NULL,'{"id": "nam_d955a3bee9b24f98b0c38e2c7eec98b0", "text": "Logins", "entity_id": "ent_b4410d5f20cd4e70ba4ebb461e00103a", "generated_from_name_id": "nam_bdd2a330a13f430d8e8fb96dc150b28e", "created_at": "2026-10-24T05:51:09.500Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-24T05:51:09.501Z',NULL,'create','entity','ent_2c32de39501444b1b8d437447ae7ed92',NULL,'{"id": "ent_2c32de39501444b1b8d437447ae7ed92", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-24T05:51:09.501Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-24T05:51:09.501Z',NULL,'create','name','nam_e8ee5ed80cff4560a1af031b92cca2a1',NULL,'{"id": "nam_e8ee5ed80cff4560a1af031b92cca2a1", "text": "Session", "entity_id": "ent_2c32de39501444b1b8d437447ae7ed92", "generated_from_name_id": null, "created_at": "2026-10-24T05:51:09.501Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-24T05:51:09.501Z',NULL,'update','entity','ent_2c32de39501444b1b8d437447ae7ed92','{"id": "ent_2c32de39501444b1b8d437447ae7ed92", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-24T05:51:09.501Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_2c32de39501444b1b8d437447ae7ed92", "description": "An authenticated visit.", "preferred_name_id": "nam_e8ee5ed80cff4560a1af031b92cca2a1", "created_at": "2026-10-24T05:51:09.501Z", "updated_at": "2026-10-24T05:51:09.501Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-24T05:51:09.501Z',NULL,'create','name','nam_95eda057389e402c98fc66620c229e91',NULL,'{"id": "nam_95eda057389e402c98fc66620c229e91", "text": "Sessions", "entity_id": "ent_2c32de39501444b1b8d437447ae7ed92", "generated_from_name_id": "nam_e8ee5ed80cff4560a1af031b92cca2a1", "created_at": "2026-10-24T05:51:09.501Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-24T05:51:09.501Z',NULL,'create','name','nam_9d0819bac5564d8f8c9f523b44c09988',NULL,'{"id": "nam_9d0819bac5564d8f8c9f523b44c09988", "text": "Sign-in", "entity_id": "ent_b4410d5f20cd4e70ba4ebb461e00103a", "generated_from_name_id": null, "created_at": "2026-10-24T05:51:09.501Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-24T05:51:09.501Z',NULL,'create','name','nam_857d3e35396b47b08f6b6f5317e84563',NULL,'{"id": "nam_857d3e35396b47b08f6b6f5317e84563", "text": "Sign-ins", "entity_id": "ent_b4410d5f20cd4e70ba4ebb461e00103a", "generated_from_name_id": "nam_9d0819bac5564d8f8c9f523b44c09988", "created_at": "2026-10-24T05:51:09.501Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-24T05:51:09.502Z',NULL,'link','entity_link','ent_b4410d5f20cd4e70ba4ebb461e00103a|ent_2c32de39501444b1b8d437447ae7ed92|contains',NULL,'{"from_entity_id": "ent_b4410d5f20cd4e70ba4ebb461e00103a", "to_entity_id": "ent_2c32de39501444b1b8d437447ae7ed92", "link_type": "contains", "created_at": "2026-10-24T05:51:09.502Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-24T05:51:09.502Z',NULL,'create','statement','stm_7094dbdd211a48c8bfc8fd84d158c06e',NULL,'{"id": "stm_7094dbdd211a48c8bfc8fd84d158c06e", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-24T05:51:09.502Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-24T05:51:09.503Z',NULL,'create','statement','stm_9bcdc5500532453094200b4eccdd0472',NULL,'{"id": "stm_9bcdc5500532453094200b4eccdd0472", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-24T05:51:09.503Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-24T05:51:09.503Z',NULL,'create','statement','stm_79c6884616b541428b92c54046eb48c7',NULL,'{"id": "stm_79c6884616b541428b92c54046eb48c7", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-24T05:51:09.503Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-24T05:51:09.503Z',NULL,'create','statement','stm_4233567c21484457a10c8265a95e0712',NULL,'{"id": "stm_4233567c21484457a10c8265a95e0712", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-24T05:51:09.503Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-24T05:51:09.504Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_7094dbdd211a48c8bfc8fd84d158c06e", "to_id": "stm_9bcdc5500532453094200b4eccdd0472", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_79c6884616b541428b92c54046eb48c7"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
