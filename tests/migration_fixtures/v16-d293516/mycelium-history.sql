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
INSERT INTO "history_events" VALUES(1,'2026-10-22T20:10:04.594Z',NULL,'create','entity','ent_587f64532ca846759aea85dad9f48813',NULL,'{"id": "ent_587f64532ca846759aea85dad9f48813", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-22T20:10:04.594Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-22T20:10:04.594Z',NULL,'create','name','nam_a5e4ebbdb65949ecb7eb904648cc5780',NULL,'{"id": "nam_a5e4ebbdb65949ecb7eb904648cc5780", "text": "Login", "entity_id": "ent_587f64532ca846759aea85dad9f48813", "generated_from_name_id": null, "created_at": "2026-10-22T20:10:04.594Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-22T20:10:04.594Z',NULL,'update','entity','ent_587f64532ca846759aea85dad9f48813','{"id": "ent_587f64532ca846759aea85dad9f48813", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-22T20:10:04.594Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_587f64532ca846759aea85dad9f48813", "description": "Signing in.", "preferred_name_id": "nam_a5e4ebbdb65949ecb7eb904648cc5780", "created_at": "2026-10-22T20:10:04.594Z", "updated_at": "2026-10-22T20:10:04.594Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-22T20:10:04.603Z',NULL,'create','name','nam_c4648654e9df4f278c5a2c737d086bfc',NULL,'{"id": "nam_c4648654e9df4f278c5a2c737d086bfc", "text": "Logins", "entity_id": "ent_587f64532ca846759aea85dad9f48813", "generated_from_name_id": "nam_a5e4ebbdb65949ecb7eb904648cc5780", "created_at": "2026-10-22T20:10:04.603Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-22T20:10:04.604Z',NULL,'create','entity','ent_4cafa8bec225432aa4e9137f0e1e080a',NULL,'{"id": "ent_4cafa8bec225432aa4e9137f0e1e080a", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-22T20:10:04.604Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-22T20:10:04.605Z',NULL,'create','name','nam_753bae36bfa6401a82d4e660fb542b07',NULL,'{"id": "nam_753bae36bfa6401a82d4e660fb542b07", "text": "Session", "entity_id": "ent_4cafa8bec225432aa4e9137f0e1e080a", "generated_from_name_id": null, "created_at": "2026-10-22T20:10:04.605Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-22T20:10:04.605Z',NULL,'update','entity','ent_4cafa8bec225432aa4e9137f0e1e080a','{"id": "ent_4cafa8bec225432aa4e9137f0e1e080a", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-22T20:10:04.604Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_4cafa8bec225432aa4e9137f0e1e080a", "description": "An authenticated visit.", "preferred_name_id": "nam_753bae36bfa6401a82d4e660fb542b07", "created_at": "2026-10-22T20:10:04.604Z", "updated_at": "2026-10-22T20:10:04.605Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-22T20:10:04.605Z',NULL,'create','name','nam_7bd308a6b42a4a14b7d48e3b07d297f5',NULL,'{"id": "nam_7bd308a6b42a4a14b7d48e3b07d297f5", "text": "Sessions", "entity_id": "ent_4cafa8bec225432aa4e9137f0e1e080a", "generated_from_name_id": "nam_753bae36bfa6401a82d4e660fb542b07", "created_at": "2026-10-22T20:10:04.605Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-22T20:10:04.606Z',NULL,'create','name','nam_b6bc1f89983845dbba22459d24803c44',NULL,'{"id": "nam_b6bc1f89983845dbba22459d24803c44", "text": "Sign-in", "entity_id": "ent_587f64532ca846759aea85dad9f48813", "generated_from_name_id": null, "created_at": "2026-10-22T20:10:04.606Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-22T20:10:04.606Z',NULL,'create','name','nam_1709cc8fc2594c949f1f9b3b98fd6d83',NULL,'{"id": "nam_1709cc8fc2594c949f1f9b3b98fd6d83", "text": "Sign-ins", "entity_id": "ent_587f64532ca846759aea85dad9f48813", "generated_from_name_id": "nam_b6bc1f89983845dbba22459d24803c44", "created_at": "2026-10-22T20:10:04.606Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-22T20:10:04.607Z',NULL,'link','entity_link','ent_587f64532ca846759aea85dad9f48813|ent_4cafa8bec225432aa4e9137f0e1e080a|contains',NULL,'{"from_entity_id": "ent_587f64532ca846759aea85dad9f48813", "to_entity_id": "ent_4cafa8bec225432aa4e9137f0e1e080a", "link_type": "contains", "created_at": "2026-10-22T20:10:04.607Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-22T20:10:04.609Z',NULL,'create','statement','stm_9b3ae0a2e0074d8fb54af1471ae0562b',NULL,'{"id": "stm_9b3ae0a2e0074d8fb54af1471ae0562b", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-22T20:10:04.608Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-22T20:10:04.610Z',NULL,'create','statement','stm_410822eccf54432c9ccd1b72abdfb1e0',NULL,'{"id": "stm_410822eccf54432c9ccd1b72abdfb1e0", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-22T20:10:04.610Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-22T20:10:04.611Z',NULL,'create','statement','stm_caa9cbf93def46a6aef9ad46fc7043c6',NULL,'{"id": "stm_caa9cbf93def46a6aef9ad46fc7043c6", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-22T20:10:04.611Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-22T20:10:04.612Z',NULL,'create','statement','stm_d77578f51a2a47cea55798b5a1af7d55',NULL,'{"id": "stm_d77578f51a2a47cea55798b5a1af7d55", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-22T20:10:04.612Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-22T20:10:04.614Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_9b3ae0a2e0074d8fb54af1471ae0562b", "to_id": "stm_410822eccf54432c9ccd1b72abdfb1e0", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_caa9cbf93def46a6aef9ad46fc7043c6"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
