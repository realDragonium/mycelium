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
INSERT INTO "history_events" VALUES(1,'2026-10-22T18:23:48.464Z',NULL,'create','entity','ent_ec6faea5524141b688366b9f94801047',NULL,'{"id": "ent_ec6faea5524141b688366b9f94801047", "description": "Signing in.", "created_at": "2026-10-22T18:23:48.464Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-22T18:23:48.464Z',NULL,'create','name','nam_b05145e083bc422dbe6ebfd49541f341',NULL,'{"id": "nam_b05145e083bc422dbe6ebfd49541f341", "text": "Login", "entity_id": "ent_ec6faea5524141b688366b9f94801047", "generated_from_name_id": null, "created_at": "2026-10-22T18:23:48.464Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-22T18:23:48.473Z',NULL,'create','name','nam_e60afbded39444da90a928cd765c8157',NULL,'{"id": "nam_e60afbded39444da90a928cd765c8157", "text": "Logins", "entity_id": "ent_ec6faea5524141b688366b9f94801047", "generated_from_name_id": "nam_b05145e083bc422dbe6ebfd49541f341", "created_at": "2026-10-22T18:23:48.473Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-22T18:23:48.475Z',NULL,'create','entity','ent_16cd282d2284474a862a86776d3fbaf0',NULL,'{"id": "ent_16cd282d2284474a862a86776d3fbaf0", "description": "An authenticated visit.", "created_at": "2026-10-22T18:23:48.474Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-22T18:23:48.475Z',NULL,'create','name','nam_d147f231153249cfabb7833d99dea1d4',NULL,'{"id": "nam_d147f231153249cfabb7833d99dea1d4", "text": "Session", "entity_id": "ent_16cd282d2284474a862a86776d3fbaf0", "generated_from_name_id": null, "created_at": "2026-10-22T18:23:48.475Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-22T18:23:48.475Z',NULL,'create','name','nam_148bdbd326f04276a3e082f71f112203',NULL,'{"id": "nam_148bdbd326f04276a3e082f71f112203", "text": "Sessions", "entity_id": "ent_16cd282d2284474a862a86776d3fbaf0", "generated_from_name_id": "nam_d147f231153249cfabb7833d99dea1d4", "created_at": "2026-10-22T18:23:48.475Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-22T18:23:48.476Z',NULL,'create','name','nam_4c4fd917dacb4964aeb553c6cd49e852',NULL,'{"id": "nam_4c4fd917dacb4964aeb553c6cd49e852", "text": "Sign-in", "entity_id": "ent_ec6faea5524141b688366b9f94801047", "generated_from_name_id": null, "created_at": "2026-10-22T18:23:48.476Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-22T18:23:48.477Z',NULL,'create','name','nam_8de8b6f2dad04d2db27fd9ce49e06f3e',NULL,'{"id": "nam_8de8b6f2dad04d2db27fd9ce49e06f3e", "text": "Sign-ins", "entity_id": "ent_ec6faea5524141b688366b9f94801047", "generated_from_name_id": "nam_4c4fd917dacb4964aeb553c6cd49e852", "created_at": "2026-10-22T18:23:48.477Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-22T18:23:48.478Z',NULL,'link','entity_link','ent_ec6faea5524141b688366b9f94801047|ent_16cd282d2284474a862a86776d3fbaf0|contains',NULL,'{"from_entity_id": "ent_ec6faea5524141b688366b9f94801047", "to_entity_id": "ent_16cd282d2284474a862a86776d3fbaf0", "link_type": "contains", "created_at": "2026-10-22T18:23:48.477Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-22T18:23:48.479Z',NULL,'create','statement','stm_d8ed74208a5449478fc63d017226539b',NULL,'{"id": "stm_d8ed74208a5449478fc63d017226539b", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-22T18:23:48.479Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-22T18:23:48.480Z',NULL,'create','statement','stm_aab351ee53dc4818b6ba872dae635fd9',NULL,'{"id": "stm_aab351ee53dc4818b6ba872dae635fd9", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-22T18:23:48.480Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-22T18:23:48.481Z',NULL,'create','statement','stm_fd3decf37bf14f948d484f0809423af4',NULL,'{"id": "stm_fd3decf37bf14f948d484f0809423af4", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-22T18:23:48.481Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-22T18:23:48.483Z',NULL,'create','statement','stm_e8e0ccd79e4e4da09ba9455e011a2321',NULL,'{"id": "stm_e8e0ccd79e4e4da09ba9455e011a2321", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-22T18:23:48.483Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-22T18:23:48.485Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_d8ed74208a5449478fc63d017226539b", "to_id": "stm_aab351ee53dc4818b6ba872dae635fd9", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_fd3decf37bf14f948d484f0809423af4"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',14);
COMMIT;
