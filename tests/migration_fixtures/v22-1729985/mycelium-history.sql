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
INSERT INTO "history_events" VALUES(1,'2026-10-23T14:32:49.026Z',NULL,'create','entity','ent_90522e6e13f145839adb99f59f44ed45',NULL,'{"id": "ent_90522e6e13f145839adb99f59f44ed45", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T14:32:49.026Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-23T14:32:49.027Z',NULL,'create','name','nam_9d04897022654f2d86c92155035f1b0a',NULL,'{"id": "nam_9d04897022654f2d86c92155035f1b0a", "text": "Login", "entity_id": "ent_90522e6e13f145839adb99f59f44ed45", "generated_from_name_id": null, "created_at": "2026-10-23T14:32:49.027Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-23T14:32:49.027Z',NULL,'update','entity','ent_90522e6e13f145839adb99f59f44ed45','{"id": "ent_90522e6e13f145839adb99f59f44ed45", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T14:32:49.026Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_90522e6e13f145839adb99f59f44ed45", "description": "Signing in.", "preferred_name_id": "nam_9d04897022654f2d86c92155035f1b0a", "created_at": "2026-10-23T14:32:49.026Z", "updated_at": "2026-10-23T14:32:49.027Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-23T14:32:49.036Z',NULL,'create','name','nam_15d4abcfa89c4f2dae1b3d7534132648',NULL,'{"id": "nam_15d4abcfa89c4f2dae1b3d7534132648", "text": "Logins", "entity_id": "ent_90522e6e13f145839adb99f59f44ed45", "generated_from_name_id": "nam_9d04897022654f2d86c92155035f1b0a", "created_at": "2026-10-23T14:32:49.036Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-23T14:32:49.037Z',NULL,'create','entity','ent_80b30d76ff0a4284af6b30f5c12cd7fc',NULL,'{"id": "ent_80b30d76ff0a4284af6b30f5c12cd7fc", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T14:32:49.037Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-23T14:32:49.037Z',NULL,'create','name','nam_3da338f844db4276b7dc1dcbd5865392',NULL,'{"id": "nam_3da338f844db4276b7dc1dcbd5865392", "text": "Session", "entity_id": "ent_80b30d76ff0a4284af6b30f5c12cd7fc", "generated_from_name_id": null, "created_at": "2026-10-23T14:32:49.037Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-23T14:32:49.037Z',NULL,'update','entity','ent_80b30d76ff0a4284af6b30f5c12cd7fc','{"id": "ent_80b30d76ff0a4284af6b30f5c12cd7fc", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T14:32:49.037Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_80b30d76ff0a4284af6b30f5c12cd7fc", "description": "An authenticated visit.", "preferred_name_id": "nam_3da338f844db4276b7dc1dcbd5865392", "created_at": "2026-10-23T14:32:49.037Z", "updated_at": "2026-10-23T14:32:49.037Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-23T14:32:49.037Z',NULL,'create','name','nam_21f465f059ca4f769c248e63dd07a9b3',NULL,'{"id": "nam_21f465f059ca4f769c248e63dd07a9b3", "text": "Sessions", "entity_id": "ent_80b30d76ff0a4284af6b30f5c12cd7fc", "generated_from_name_id": "nam_3da338f844db4276b7dc1dcbd5865392", "created_at": "2026-10-23T14:32:49.037Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-23T14:32:49.039Z',NULL,'create','name','nam_0697054ab55e48cbb252c59ecefb546e',NULL,'{"id": "nam_0697054ab55e48cbb252c59ecefb546e", "text": "Sign-in", "entity_id": "ent_90522e6e13f145839adb99f59f44ed45", "generated_from_name_id": null, "created_at": "2026-10-23T14:32:49.039Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-23T14:32:49.039Z',NULL,'create','name','nam_41cc397af66643a2a626d79f33ac55c3',NULL,'{"id": "nam_41cc397af66643a2a626d79f33ac55c3", "text": "Sign-ins", "entity_id": "ent_90522e6e13f145839adb99f59f44ed45", "generated_from_name_id": "nam_0697054ab55e48cbb252c59ecefb546e", "created_at": "2026-10-23T14:32:49.039Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-23T14:32:49.040Z',NULL,'link','entity_link','ent_90522e6e13f145839adb99f59f44ed45|ent_80b30d76ff0a4284af6b30f5c12cd7fc|contains',NULL,'{"from_entity_id": "ent_90522e6e13f145839adb99f59f44ed45", "to_entity_id": "ent_80b30d76ff0a4284af6b30f5c12cd7fc", "link_type": "contains", "created_at": "2026-10-23T14:32:49.040Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-23T14:32:49.041Z',NULL,'create','statement','stm_5e400da8341b4379b5c65242cce60322',NULL,'{"id": "stm_5e400da8341b4379b5c65242cce60322", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-23T14:32:49.041Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-23T14:32:49.043Z',NULL,'create','statement','stm_77d0c5245a244a9c8bbd95d173c648db',NULL,'{"id": "stm_77d0c5245a244a9c8bbd95d173c648db", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-23T14:32:49.042Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-23T14:32:49.044Z',NULL,'create','statement','stm_f49833c000cd42bc8353d1c67acf23ac',NULL,'{"id": "stm_f49833c000cd42bc8353d1c67acf23ac", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-23T14:32:49.044Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-23T14:32:49.045Z',NULL,'create','statement','stm_0447cff21a4e48ac95c20432fcf09017',NULL,'{"id": "stm_0447cff21a4e48ac95c20432fcf09017", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-23T14:32:49.045Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-23T14:32:49.047Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_5e400da8341b4379b5c65242cce60322", "to_id": "stm_77d0c5245a244a9c8bbd95d173c648db", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_f49833c000cd42bc8353d1c67acf23ac"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
