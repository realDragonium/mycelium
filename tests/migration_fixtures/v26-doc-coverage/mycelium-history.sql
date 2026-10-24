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
INSERT INTO "history_events" VALUES(1,'2026-10-24T16:00:07.315Z',NULL,'create','entity','ent_ef12a30da5304eae820bd181db75d4e3',NULL,'{"id": "ent_ef12a30da5304eae820bd181db75d4e3", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-24T16:00:07.315Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-24T16:00:07.316Z',NULL,'create','name','nam_18674ca094f0460588093f15bac98592',NULL,'{"id": "nam_18674ca094f0460588093f15bac98592", "text": "Login", "entity_id": "ent_ef12a30da5304eae820bd181db75d4e3", "generated_from_name_id": null, "created_at": "2026-10-24T16:00:07.315Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-24T16:00:07.316Z',NULL,'update','entity','ent_ef12a30da5304eae820bd181db75d4e3','{"id": "ent_ef12a30da5304eae820bd181db75d4e3", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-24T16:00:07.315Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_ef12a30da5304eae820bd181db75d4e3", "description": "Signing in.", "preferred_name_id": "nam_18674ca094f0460588093f15bac98592", "created_at": "2026-10-24T16:00:07.315Z", "updated_at": "2026-10-24T16:00:07.316Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-24T16:00:07.316Z',NULL,'create','name','nam_c8c981bcf07b4c018d958e98929ae442',NULL,'{"id": "nam_c8c981bcf07b4c018d958e98929ae442", "text": "Logins", "entity_id": "ent_ef12a30da5304eae820bd181db75d4e3", "generated_from_name_id": "nam_18674ca094f0460588093f15bac98592", "created_at": "2026-10-24T16:00:07.316Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-24T16:00:07.316Z',NULL,'create','entity','ent_5bd7844b18c64e2fa87918f54ba9e956',NULL,'{"id": "ent_5bd7844b18c64e2fa87918f54ba9e956", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-24T16:00:07.316Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-24T16:00:07.316Z',NULL,'create','name','nam_9579bb710a6349ae8f885102d12481fe',NULL,'{"id": "nam_9579bb710a6349ae8f885102d12481fe", "text": "Session", "entity_id": "ent_5bd7844b18c64e2fa87918f54ba9e956", "generated_from_name_id": null, "created_at": "2026-10-24T16:00:07.316Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-24T16:00:07.316Z',NULL,'update','entity','ent_5bd7844b18c64e2fa87918f54ba9e956','{"id": "ent_5bd7844b18c64e2fa87918f54ba9e956", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-24T16:00:07.316Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_5bd7844b18c64e2fa87918f54ba9e956", "description": "An authenticated visit.", "preferred_name_id": "nam_9579bb710a6349ae8f885102d12481fe", "created_at": "2026-10-24T16:00:07.316Z", "updated_at": "2026-10-24T16:00:07.316Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-24T16:00:07.317Z',NULL,'create','name','nam_e0fd687e5cb94ab5bfbd802d741e9295',NULL,'{"id": "nam_e0fd687e5cb94ab5bfbd802d741e9295", "text": "Sessions", "entity_id": "ent_5bd7844b18c64e2fa87918f54ba9e956", "generated_from_name_id": "nam_9579bb710a6349ae8f885102d12481fe", "created_at": "2026-10-24T16:00:07.317Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-24T16:00:07.317Z',NULL,'create','name','nam_809dbc8158e94a15804b536d36114a6d',NULL,'{"id": "nam_809dbc8158e94a15804b536d36114a6d", "text": "Sign-in", "entity_id": "ent_ef12a30da5304eae820bd181db75d4e3", "generated_from_name_id": null, "created_at": "2026-10-24T16:00:07.317Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-24T16:00:07.317Z',NULL,'create','name','nam_0d25123b394d4fb69a72cce1c34f5e93',NULL,'{"id": "nam_0d25123b394d4fb69a72cce1c34f5e93", "text": "Sign-ins", "entity_id": "ent_ef12a30da5304eae820bd181db75d4e3", "generated_from_name_id": "nam_809dbc8158e94a15804b536d36114a6d", "created_at": "2026-10-24T16:00:07.317Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-24T16:00:07.318Z',NULL,'link','entity_link','ent_ef12a30da5304eae820bd181db75d4e3|ent_5bd7844b18c64e2fa87918f54ba9e956|contains',NULL,'{"from_entity_id": "ent_ef12a30da5304eae820bd181db75d4e3", "to_entity_id": "ent_5bd7844b18c64e2fa87918f54ba9e956", "link_type": "contains", "created_at": "2026-10-24T16:00:07.317Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-24T16:00:07.318Z',NULL,'create','statement','stm_14a72984b0884e8b9feee8e5e24fdf67',NULL,'{"id": "stm_14a72984b0884e8b9feee8e5e24fdf67", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-24T16:00:07.318Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-24T16:00:07.318Z',NULL,'create','statement','stm_9dada3151336472299d94d65b7e2b88a',NULL,'{"id": "stm_9dada3151336472299d94d65b7e2b88a", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-24T16:00:07.318Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-24T16:00:07.319Z',NULL,'create','statement','stm_130193b8c37e4366909ab2f0f20b0cb1',NULL,'{"id": "stm_130193b8c37e4366909ab2f0f20b0cb1", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-24T16:00:07.319Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-24T16:00:07.319Z',NULL,'create','statement','stm_a9a74f3758f046b9ba512a1fc981fab9',NULL,'{"id": "stm_a9a74f3758f046b9ba512a1fc981fab9", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-24T16:00:07.319Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-24T16:00:07.320Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_14a72984b0884e8b9feee8e5e24fdf67", "to_id": "stm_9dada3151336472299d94d65b7e2b88a", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_130193b8c37e4366909ab2f0f20b0cb1"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
