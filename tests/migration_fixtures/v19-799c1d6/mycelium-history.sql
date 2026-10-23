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
INSERT INTO "history_events" VALUES(1,'2026-10-23T06:20:00.452Z',NULL,'create','entity','ent_8563adffb3064971be6e438bc50040a4',NULL,'{"id": "ent_8563adffb3064971be6e438bc50040a4", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T06:20:00.452Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-23T06:20:00.453Z',NULL,'create','name','nam_7b608f87693f4ab6988af809cc22cf22',NULL,'{"id": "nam_7b608f87693f4ab6988af809cc22cf22", "text": "Login", "entity_id": "ent_8563adffb3064971be6e438bc50040a4", "generated_from_name_id": null, "created_at": "2026-10-23T06:20:00.453Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-23T06:20:00.453Z',NULL,'update','entity','ent_8563adffb3064971be6e438bc50040a4','{"id": "ent_8563adffb3064971be6e438bc50040a4", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T06:20:00.452Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_8563adffb3064971be6e438bc50040a4", "description": "Signing in.", "preferred_name_id": "nam_7b608f87693f4ab6988af809cc22cf22", "created_at": "2026-10-23T06:20:00.452Z", "updated_at": "2026-10-23T06:20:00.453Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-23T06:20:00.462Z',NULL,'create','name','nam_8b957f81ef9b4502be18369e9dcdc3c2',NULL,'{"id": "nam_8b957f81ef9b4502be18369e9dcdc3c2", "text": "Logins", "entity_id": "ent_8563adffb3064971be6e438bc50040a4", "generated_from_name_id": "nam_7b608f87693f4ab6988af809cc22cf22", "created_at": "2026-10-23T06:20:00.462Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-23T06:20:00.463Z',NULL,'create','entity','ent_f668256cdd28433a977a471307854dea',NULL,'{"id": "ent_f668256cdd28433a977a471307854dea", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T06:20:00.463Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-23T06:20:00.463Z',NULL,'create','name','nam_094d8ee703f740d388ec5c1cd6e0d258',NULL,'{"id": "nam_094d8ee703f740d388ec5c1cd6e0d258", "text": "Session", "entity_id": "ent_f668256cdd28433a977a471307854dea", "generated_from_name_id": null, "created_at": "2026-10-23T06:20:00.463Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-23T06:20:00.463Z',NULL,'update','entity','ent_f668256cdd28433a977a471307854dea','{"id": "ent_f668256cdd28433a977a471307854dea", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T06:20:00.463Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_f668256cdd28433a977a471307854dea", "description": "An authenticated visit.", "preferred_name_id": "nam_094d8ee703f740d388ec5c1cd6e0d258", "created_at": "2026-10-23T06:20:00.463Z", "updated_at": "2026-10-23T06:20:00.463Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-23T06:20:00.463Z',NULL,'create','name','nam_6149a13e14724deabd7fbb144056cee1',NULL,'{"id": "nam_6149a13e14724deabd7fbb144056cee1", "text": "Sessions", "entity_id": "ent_f668256cdd28433a977a471307854dea", "generated_from_name_id": "nam_094d8ee703f740d388ec5c1cd6e0d258", "created_at": "2026-10-23T06:20:00.463Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-23T06:20:00.464Z',NULL,'create','name','nam_0e745860f5f74405959d717500645709',NULL,'{"id": "nam_0e745860f5f74405959d717500645709", "text": "Sign-in", "entity_id": "ent_8563adffb3064971be6e438bc50040a4", "generated_from_name_id": null, "created_at": "2026-10-23T06:20:00.464Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-23T06:20:00.465Z',NULL,'create','name','nam_0346a25ef2b94e6c961862e630fe95f9',NULL,'{"id": "nam_0346a25ef2b94e6c961862e630fe95f9", "text": "Sign-ins", "entity_id": "ent_8563adffb3064971be6e438bc50040a4", "generated_from_name_id": "nam_0e745860f5f74405959d717500645709", "created_at": "2026-10-23T06:20:00.465Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-23T06:20:00.465Z',NULL,'link','entity_link','ent_8563adffb3064971be6e438bc50040a4|ent_f668256cdd28433a977a471307854dea|contains',NULL,'{"from_entity_id": "ent_8563adffb3064971be6e438bc50040a4", "to_entity_id": "ent_f668256cdd28433a977a471307854dea", "link_type": "contains", "created_at": "2026-10-23T06:20:00.465Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-23T06:20:00.466Z',NULL,'create','statement','stm_6be5da0d01bc4f07aacb169425f60343',NULL,'{"id": "stm_6be5da0d01bc4f07aacb169425f60343", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-23T06:20:00.466Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-23T06:20:00.468Z',NULL,'create','statement','stm_9116fd6e544941a685ea9f6dfe5556c2',NULL,'{"id": "stm_9116fd6e544941a685ea9f6dfe5556c2", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-23T06:20:00.468Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-23T06:20:00.469Z',NULL,'create','statement','stm_1381711b46954469850f355e1a1f0d55',NULL,'{"id": "stm_1381711b46954469850f355e1a1f0d55", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-23T06:20:00.469Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-23T06:20:00.470Z',NULL,'create','statement','stm_32d4c8e1e91d4b30b99d66ff5d9a2613',NULL,'{"id": "stm_32d4c8e1e91d4b30b99d66ff5d9a2613", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-23T06:20:00.470Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-23T06:20:00.471Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_6be5da0d01bc4f07aacb169425f60343", "to_id": "stm_9116fd6e544941a685ea9f6dfe5556c2", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_1381711b46954469850f355e1a1f0d55"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
