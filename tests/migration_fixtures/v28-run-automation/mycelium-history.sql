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
INSERT INTO "history_events" VALUES(1,'2026-10-25T09:29:41.661Z',NULL,'create','entity','ent_b30130ea6834468a8813708daa18c48c',NULL,'{"id": "ent_b30130ea6834468a8813708daa18c48c", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-25T09:29:41.661Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-25T09:29:41.661Z',NULL,'create','name','nam_5112bbaccda3403fa1ade3b5f755c43f',NULL,'{"id": "nam_5112bbaccda3403fa1ade3b5f755c43f", "text": "Login", "entity_id": "ent_b30130ea6834468a8813708daa18c48c", "generated_from_name_id": null, "created_at": "2026-10-25T09:29:41.661Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-25T09:29:41.661Z',NULL,'update','entity','ent_b30130ea6834468a8813708daa18c48c','{"id": "ent_b30130ea6834468a8813708daa18c48c", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-25T09:29:41.661Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_b30130ea6834468a8813708daa18c48c", "description": "Signing in.", "preferred_name_id": "nam_5112bbaccda3403fa1ade3b5f755c43f", "created_at": "2026-10-25T09:29:41.661Z", "updated_at": "2026-10-25T09:29:41.661Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-25T09:29:41.661Z',NULL,'create','name','nam_a3a77a8e5f8b43708d36306d75868343',NULL,'{"id": "nam_a3a77a8e5f8b43708d36306d75868343", "text": "Logins", "entity_id": "ent_b30130ea6834468a8813708daa18c48c", "generated_from_name_id": "nam_5112bbaccda3403fa1ade3b5f755c43f", "created_at": "2026-10-25T09:29:41.661Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-25T09:29:41.662Z',NULL,'create','entity','ent_3ea267370c38445290f261d45634260e',NULL,'{"id": "ent_3ea267370c38445290f261d45634260e", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-25T09:29:41.662Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-25T09:29:41.662Z',NULL,'create','name','nam_7c25776724ac4da49103c520653477ad',NULL,'{"id": "nam_7c25776724ac4da49103c520653477ad", "text": "Session", "entity_id": "ent_3ea267370c38445290f261d45634260e", "generated_from_name_id": null, "created_at": "2026-10-25T09:29:41.662Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-25T09:29:41.662Z',NULL,'update','entity','ent_3ea267370c38445290f261d45634260e','{"id": "ent_3ea267370c38445290f261d45634260e", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-25T09:29:41.662Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_3ea267370c38445290f261d45634260e", "description": "An authenticated visit.", "preferred_name_id": "nam_7c25776724ac4da49103c520653477ad", "created_at": "2026-10-25T09:29:41.662Z", "updated_at": "2026-10-25T09:29:41.662Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-25T09:29:41.662Z',NULL,'create','name','nam_8406c645c863431b9456c5b1c69815a3',NULL,'{"id": "nam_8406c645c863431b9456c5b1c69815a3", "text": "Sessions", "entity_id": "ent_3ea267370c38445290f261d45634260e", "generated_from_name_id": "nam_7c25776724ac4da49103c520653477ad", "created_at": "2026-10-25T09:29:41.662Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-25T09:29:41.663Z',NULL,'create','name','nam_9d4fbe4d824c4f8881fc14472acad1f2',NULL,'{"id": "nam_9d4fbe4d824c4f8881fc14472acad1f2", "text": "Sign-in", "entity_id": "ent_b30130ea6834468a8813708daa18c48c", "generated_from_name_id": null, "created_at": "2026-10-25T09:29:41.663Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-25T09:29:41.663Z',NULL,'create','name','nam_5db6097a3bf6460b8f20e66817497be7',NULL,'{"id": "nam_5db6097a3bf6460b8f20e66817497be7", "text": "Sign-ins", "entity_id": "ent_b30130ea6834468a8813708daa18c48c", "generated_from_name_id": "nam_9d4fbe4d824c4f8881fc14472acad1f2", "created_at": "2026-10-25T09:29:41.663Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-25T09:29:41.663Z',NULL,'link','entity_link','ent_b30130ea6834468a8813708daa18c48c|ent_3ea267370c38445290f261d45634260e|contains',NULL,'{"from_entity_id": "ent_b30130ea6834468a8813708daa18c48c", "to_entity_id": "ent_3ea267370c38445290f261d45634260e", "link_type": "contains", "created_at": "2026-10-25T09:29:41.663Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-25T09:29:41.664Z',NULL,'create','statement','stm_af121a8242c248c88bae5101488b524a',NULL,'{"id": "stm_af121a8242c248c88bae5101488b524a", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-25T09:29:41.663Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-25T09:29:41.664Z',NULL,'create','statement','stm_3e16b78f6cf64c109bbb239b3fe4af5d',NULL,'{"id": "stm_3e16b78f6cf64c109bbb239b3fe4af5d", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-25T09:29:41.664Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-25T09:29:41.664Z',NULL,'create','statement','stm_02fef935133e4ce2a84da33b6c7a21e3',NULL,'{"id": "stm_02fef935133e4ce2a84da33b6c7a21e3", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-25T09:29:41.664Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-25T09:29:41.665Z',NULL,'create','statement','stm_e3d00d5e27d54cfe99763fcee05e99e8',NULL,'{"id": "stm_e3d00d5e27d54cfe99763fcee05e99e8", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-25T09:29:41.665Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-25T09:29:41.665Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_af121a8242c248c88bae5101488b524a", "to_id": "stm_3e16b78f6cf64c109bbb239b3fe4af5d", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_02fef935133e4ce2a84da33b6c7a21e3"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
