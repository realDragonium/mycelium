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
INSERT INTO "history_events" VALUES(1,'2026-11-21T17:26:16.274Z',NULL,'create','entity','ent_cccea847dd254021abc8f7d9fbb92dac',NULL,'{"id": "ent_cccea847dd254021abc8f7d9fbb92dac", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-11-21T17:26:16.274Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-11-21T17:26:16.274Z',NULL,'create','name','nam_2289462313de4c418f4e757f9bf4399c',NULL,'{"id": "nam_2289462313de4c418f4e757f9bf4399c", "text": "Login", "entity_id": "ent_cccea847dd254021abc8f7d9fbb92dac", "generated_from_name_id": null, "created_at": "2026-11-21T17:26:16.274Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-11-21T17:26:16.275Z',NULL,'update','entity','ent_cccea847dd254021abc8f7d9fbb92dac','{"id": "ent_cccea847dd254021abc8f7d9fbb92dac", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-11-21T17:26:16.274Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_cccea847dd254021abc8f7d9fbb92dac", "description": "Signing in.", "preferred_name_id": "nam_2289462313de4c418f4e757f9bf4399c", "created_at": "2026-11-21T17:26:16.274Z", "updated_at": "2026-11-21T17:26:16.275Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-11-21T17:26:16.275Z',NULL,'create','name','nam_b2756a05d45947dfbc55559fb54e9f8e',NULL,'{"id": "nam_b2756a05d45947dfbc55559fb54e9f8e", "text": "Logins", "entity_id": "ent_cccea847dd254021abc8f7d9fbb92dac", "generated_from_name_id": "nam_2289462313de4c418f4e757f9bf4399c", "created_at": "2026-11-21T17:26:16.275Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-11-21T17:26:16.276Z',NULL,'create','entity','ent_0b208fbb4ad645c18d91b82e59819297',NULL,'{"id": "ent_0b208fbb4ad645c18d91b82e59819297", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-11-21T17:26:16.276Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-11-21T17:26:16.277Z',NULL,'create','name','nam_dff58e72b82b414198587954b2947460',NULL,'{"id": "nam_dff58e72b82b414198587954b2947460", "text": "Session", "entity_id": "ent_0b208fbb4ad645c18d91b82e59819297", "generated_from_name_id": null, "created_at": "2026-11-21T17:26:16.277Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-11-21T17:26:16.277Z',NULL,'update','entity','ent_0b208fbb4ad645c18d91b82e59819297','{"id": "ent_0b208fbb4ad645c18d91b82e59819297", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-11-21T17:26:16.276Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_0b208fbb4ad645c18d91b82e59819297", "description": "An authenticated visit.", "preferred_name_id": "nam_dff58e72b82b414198587954b2947460", "created_at": "2026-11-21T17:26:16.276Z", "updated_at": "2026-11-21T17:26:16.277Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-11-21T17:26:16.277Z',NULL,'create','name','nam_07fca7fe2e43443abf546d3e2d1e8cc4',NULL,'{"id": "nam_07fca7fe2e43443abf546d3e2d1e8cc4", "text": "Sessions", "entity_id": "ent_0b208fbb4ad645c18d91b82e59819297", "generated_from_name_id": "nam_dff58e72b82b414198587954b2947460", "created_at": "2026-11-21T17:26:16.277Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-11-21T17:26:16.278Z',NULL,'create','name','nam_cbd0c1224bc24c71a747967c2dc107a0',NULL,'{"id": "nam_cbd0c1224bc24c71a747967c2dc107a0", "text": "Sign-in", "entity_id": "ent_cccea847dd254021abc8f7d9fbb92dac", "generated_from_name_id": null, "created_at": "2026-11-21T17:26:16.278Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-11-21T17:26:16.279Z',NULL,'create','name','nam_00880cdb3bcd418d936f83c21052f131',NULL,'{"id": "nam_00880cdb3bcd418d936f83c21052f131", "text": "Sign-ins", "entity_id": "ent_cccea847dd254021abc8f7d9fbb92dac", "generated_from_name_id": "nam_cbd0c1224bc24c71a747967c2dc107a0", "created_at": "2026-11-21T17:26:16.279Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-11-21T17:26:16.279Z',NULL,'link','entity_link','ent_cccea847dd254021abc8f7d9fbb92dac|ent_0b208fbb4ad645c18d91b82e59819297|contains',NULL,'{"from_entity_id": "ent_cccea847dd254021abc8f7d9fbb92dac", "to_entity_id": "ent_0b208fbb4ad645c18d91b82e59819297", "link_type": "contains", "created_at": "2026-11-21T17:26:16.279Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-11-21T17:26:16.280Z',NULL,'create','statement','stm_c0d5cefc3fc94bedabaaf0598e5dbdf5',NULL,'{"id": "stm_c0d5cefc3fc94bedabaaf0598e5dbdf5", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-11-21T17:26:16.280Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-11-21T17:26:16.282Z',NULL,'create','statement','stm_24bd2555ae444da193e633282805afea',NULL,'{"id": "stm_24bd2555ae444da193e633282805afea", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-11-21T17:26:16.282Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-11-21T17:26:16.283Z',NULL,'create','statement','stm_b39336178b89451b9cc818573ddc7c76',NULL,'{"id": "stm_b39336178b89451b9cc818573ddc7c76", "kind": "state", "text": "The account is locked.", "created_at": "2026-11-21T17:26:16.283Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-11-21T17:26:16.284Z',NULL,'create','statement','stm_c8a2edc4e02b4845aa401fcb19822c51',NULL,'{"id": "stm_c8a2edc4e02b4845aa401fcb19822c51", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-11-21T17:26:16.284Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-11-21T17:26:16.285Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_c0d5cefc3fc94bedabaaf0598e5dbdf5", "to_id": "stm_24bd2555ae444da193e633282805afea", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_b39336178b89451b9cc818573ddc7c76"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
