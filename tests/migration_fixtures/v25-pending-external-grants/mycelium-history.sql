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
INSERT INTO "history_events" VALUES(1,'2026-10-23T19:19:07.036Z',NULL,'create','entity','ent_cab35bdd2af041dd8af46d21fb0b2037',NULL,'{"id": "ent_cab35bdd2af041dd8af46d21fb0b2037", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T19:19:07.035Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-23T19:19:07.036Z',NULL,'create','name','nam_b750d0337cbb47199dbaa760264bcb02',NULL,'{"id": "nam_b750d0337cbb47199dbaa760264bcb02", "text": "Login", "entity_id": "ent_cab35bdd2af041dd8af46d21fb0b2037", "generated_from_name_id": null, "created_at": "2026-10-23T19:19:07.036Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-23T19:19:07.036Z',NULL,'update','entity','ent_cab35bdd2af041dd8af46d21fb0b2037','{"id": "ent_cab35bdd2af041dd8af46d21fb0b2037", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T19:19:07.035Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_cab35bdd2af041dd8af46d21fb0b2037", "description": "Signing in.", "preferred_name_id": "nam_b750d0337cbb47199dbaa760264bcb02", "created_at": "2026-10-23T19:19:07.035Z", "updated_at": "2026-10-23T19:19:07.036Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-23T19:19:07.041Z',NULL,'create','name','nam_335fe1fd166d4a70a125a5dbd02e5703',NULL,'{"id": "nam_335fe1fd166d4a70a125a5dbd02e5703", "text": "Logins", "entity_id": "ent_cab35bdd2af041dd8af46d21fb0b2037", "generated_from_name_id": "nam_b750d0337cbb47199dbaa760264bcb02", "created_at": "2026-10-23T19:19:07.041Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-23T19:19:07.042Z',NULL,'create','entity','ent_7ed8ce50f53a43639e9b4834c10efee9',NULL,'{"id": "ent_7ed8ce50f53a43639e9b4834c10efee9", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T19:19:07.042Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-23T19:19:07.042Z',NULL,'create','name','nam_5adcd007e8f140ed9382a2972cfc3d26',NULL,'{"id": "nam_5adcd007e8f140ed9382a2972cfc3d26", "text": "Session", "entity_id": "ent_7ed8ce50f53a43639e9b4834c10efee9", "generated_from_name_id": null, "created_at": "2026-10-23T19:19:07.042Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-23T19:19:07.042Z',NULL,'update','entity','ent_7ed8ce50f53a43639e9b4834c10efee9','{"id": "ent_7ed8ce50f53a43639e9b4834c10efee9", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T19:19:07.042Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_7ed8ce50f53a43639e9b4834c10efee9", "description": "An authenticated visit.", "preferred_name_id": "nam_5adcd007e8f140ed9382a2972cfc3d26", "created_at": "2026-10-23T19:19:07.042Z", "updated_at": "2026-10-23T19:19:07.042Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-23T19:19:07.042Z',NULL,'create','name','nam_1bb9902386b94385ae150230764b0e18',NULL,'{"id": "nam_1bb9902386b94385ae150230764b0e18", "text": "Sessions", "entity_id": "ent_7ed8ce50f53a43639e9b4834c10efee9", "generated_from_name_id": "nam_5adcd007e8f140ed9382a2972cfc3d26", "created_at": "2026-10-23T19:19:07.042Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-23T19:19:07.042Z',NULL,'create','name','nam_30fd463f130b4f3bb6cf8fe56515ca3f',NULL,'{"id": "nam_30fd463f130b4f3bb6cf8fe56515ca3f", "text": "Sign-in", "entity_id": "ent_cab35bdd2af041dd8af46d21fb0b2037", "generated_from_name_id": null, "created_at": "2026-10-23T19:19:07.042Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-23T19:19:07.042Z',NULL,'create','name','nam_2421f52aed5342c18e48a2581b56c149',NULL,'{"id": "nam_2421f52aed5342c18e48a2581b56c149", "text": "Sign-ins", "entity_id": "ent_cab35bdd2af041dd8af46d21fb0b2037", "generated_from_name_id": "nam_30fd463f130b4f3bb6cf8fe56515ca3f", "created_at": "2026-10-23T19:19:07.042Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-23T19:19:07.043Z',NULL,'link','entity_link','ent_cab35bdd2af041dd8af46d21fb0b2037|ent_7ed8ce50f53a43639e9b4834c10efee9|contains',NULL,'{"from_entity_id": "ent_cab35bdd2af041dd8af46d21fb0b2037", "to_entity_id": "ent_7ed8ce50f53a43639e9b4834c10efee9", "link_type": "contains", "created_at": "2026-10-23T19:19:07.043Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-23T19:19:07.043Z',NULL,'create','statement','stm_8d9379bead084fd094cf9128796ead7b',NULL,'{"id": "stm_8d9379bead084fd094cf9128796ead7b", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-23T19:19:07.043Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-23T19:19:07.044Z',NULL,'create','statement','stm_af612f7fee9445ce8ac86286b3c00922',NULL,'{"id": "stm_af612f7fee9445ce8ac86286b3c00922", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-23T19:19:07.044Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-23T19:19:07.044Z',NULL,'create','statement','stm_774082fa848a4c2e812913ccfc860f3f',NULL,'{"id": "stm_774082fa848a4c2e812913ccfc860f3f", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-23T19:19:07.044Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-23T19:19:07.045Z',NULL,'create','statement','stm_edb1b6d837f54a1ab3ddebe1512d3879',NULL,'{"id": "stm_edb1b6d837f54a1ab3ddebe1512d3879", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-23T19:19:07.045Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-23T19:19:07.045Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_8d9379bead084fd094cf9128796ead7b", "to_id": "stm_af612f7fee9445ce8ac86286b3c00922", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_774082fa848a4c2e812913ccfc860f3f"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
