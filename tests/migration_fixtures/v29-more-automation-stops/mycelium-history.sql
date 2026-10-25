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
INSERT INTO "history_events" VALUES(1,'2026-10-25T10:00:28.287Z',NULL,'create','entity','ent_e54cc60ca1224757946df8ce1f427747',NULL,'{"id": "ent_e54cc60ca1224757946df8ce1f427747", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-25T10:00:28.287Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-25T10:00:28.288Z',NULL,'create','name','nam_d4de1aa7e4b847e2b49a03dd4093bc2c',NULL,'{"id": "nam_d4de1aa7e4b847e2b49a03dd4093bc2c", "text": "Login", "entity_id": "ent_e54cc60ca1224757946df8ce1f427747", "generated_from_name_id": null, "created_at": "2026-10-25T10:00:28.288Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-25T10:00:28.288Z',NULL,'update','entity','ent_e54cc60ca1224757946df8ce1f427747','{"id": "ent_e54cc60ca1224757946df8ce1f427747", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-25T10:00:28.287Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_e54cc60ca1224757946df8ce1f427747", "description": "Signing in.", "preferred_name_id": "nam_d4de1aa7e4b847e2b49a03dd4093bc2c", "created_at": "2026-10-25T10:00:28.287Z", "updated_at": "2026-10-25T10:00:28.288Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-25T10:00:28.288Z',NULL,'create','name','nam_f1a1d4e86357496681f9ecf2d3898a1d',NULL,'{"id": "nam_f1a1d4e86357496681f9ecf2d3898a1d", "text": "Logins", "entity_id": "ent_e54cc60ca1224757946df8ce1f427747", "generated_from_name_id": "nam_d4de1aa7e4b847e2b49a03dd4093bc2c", "created_at": "2026-10-25T10:00:28.288Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-25T10:00:28.289Z',NULL,'create','entity','ent_3af22de5ab7140158724f591685ede40',NULL,'{"id": "ent_3af22de5ab7140158724f591685ede40", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-25T10:00:28.289Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-25T10:00:28.289Z',NULL,'create','name','nam_b93156ae008041f5bcbbb63b9418a385',NULL,'{"id": "nam_b93156ae008041f5bcbbb63b9418a385", "text": "Session", "entity_id": "ent_3af22de5ab7140158724f591685ede40", "generated_from_name_id": null, "created_at": "2026-10-25T10:00:28.289Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-25T10:00:28.289Z',NULL,'update','entity','ent_3af22de5ab7140158724f591685ede40','{"id": "ent_3af22de5ab7140158724f591685ede40", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-25T10:00:28.289Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_3af22de5ab7140158724f591685ede40", "description": "An authenticated visit.", "preferred_name_id": "nam_b93156ae008041f5bcbbb63b9418a385", "created_at": "2026-10-25T10:00:28.289Z", "updated_at": "2026-10-25T10:00:28.289Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-25T10:00:28.289Z',NULL,'create','name','nam_bbd2e79024c54c6fb414581a5d415164',NULL,'{"id": "nam_bbd2e79024c54c6fb414581a5d415164", "text": "Sessions", "entity_id": "ent_3af22de5ab7140158724f591685ede40", "generated_from_name_id": "nam_b93156ae008041f5bcbbb63b9418a385", "created_at": "2026-10-25T10:00:28.289Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-25T10:00:28.289Z',NULL,'create','name','nam_729e77448fb242e1bc643ec0200391ae',NULL,'{"id": "nam_729e77448fb242e1bc643ec0200391ae", "text": "Sign-in", "entity_id": "ent_e54cc60ca1224757946df8ce1f427747", "generated_from_name_id": null, "created_at": "2026-10-25T10:00:28.289Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-25T10:00:28.290Z',NULL,'create','name','nam_037d3996e2c944b081adc8b5ec0db2af',NULL,'{"id": "nam_037d3996e2c944b081adc8b5ec0db2af", "text": "Sign-ins", "entity_id": "ent_e54cc60ca1224757946df8ce1f427747", "generated_from_name_id": "nam_729e77448fb242e1bc643ec0200391ae", "created_at": "2026-10-25T10:00:28.290Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-25T10:00:28.290Z',NULL,'link','entity_link','ent_e54cc60ca1224757946df8ce1f427747|ent_3af22de5ab7140158724f591685ede40|contains',NULL,'{"from_entity_id": "ent_e54cc60ca1224757946df8ce1f427747", "to_entity_id": "ent_3af22de5ab7140158724f591685ede40", "link_type": "contains", "created_at": "2026-10-25T10:00:28.290Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-25T10:00:28.290Z',NULL,'create','statement','stm_2f88336cbac44a1d83592c6cfdf4c937',NULL,'{"id": "stm_2f88336cbac44a1d83592c6cfdf4c937", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-25T10:00:28.290Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-25T10:00:28.291Z',NULL,'create','statement','stm_546948ff0b2c4dbb91f48eb398b0bf3c',NULL,'{"id": "stm_546948ff0b2c4dbb91f48eb398b0bf3c", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-25T10:00:28.291Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-25T10:00:28.291Z',NULL,'create','statement','stm_fc259e2a34794cee91789661ca76db34',NULL,'{"id": "stm_fc259e2a34794cee91789661ca76db34", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-25T10:00:28.291Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-25T10:00:28.292Z',NULL,'create','statement','stm_0ea96ad8955e42cb89fa8838bcd9b730',NULL,'{"id": "stm_0ea96ad8955e42cb89fa8838bcd9b730", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-25T10:00:28.292Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-25T10:00:28.292Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_2f88336cbac44a1d83592c6cfdf4c937", "to_id": "stm_546948ff0b2c4dbb91f48eb398b0bf3c", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_fc259e2a34794cee91789661ca76db34"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
