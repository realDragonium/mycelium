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
INSERT INTO "history_events" VALUES(1,'2026-10-23T13:31:15.357Z',NULL,'create','entity','ent_10b555d5310b45b3a215e18b6dc7276b',NULL,'{"id": "ent_10b555d5310b45b3a215e18b6dc7276b", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T13:31:15.357Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-23T13:31:15.357Z',NULL,'create','name','nam_8e62c9e0a6e746e0a30360cc56d7e59e',NULL,'{"id": "nam_8e62c9e0a6e746e0a30360cc56d7e59e", "text": "Login", "entity_id": "ent_10b555d5310b45b3a215e18b6dc7276b", "generated_from_name_id": null, "created_at": "2026-10-23T13:31:15.357Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-23T13:31:15.357Z',NULL,'update','entity','ent_10b555d5310b45b3a215e18b6dc7276b','{"id": "ent_10b555d5310b45b3a215e18b6dc7276b", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T13:31:15.357Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_10b555d5310b45b3a215e18b6dc7276b", "description": "Signing in.", "preferred_name_id": "nam_8e62c9e0a6e746e0a30360cc56d7e59e", "created_at": "2026-10-23T13:31:15.357Z", "updated_at": "2026-10-23T13:31:15.357Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-23T13:31:15.360Z',NULL,'create','name','nam_2b674fbf70cf4d66bab762c1a553d442',NULL,'{"id": "nam_2b674fbf70cf4d66bab762c1a553d442", "text": "Logins", "entity_id": "ent_10b555d5310b45b3a215e18b6dc7276b", "generated_from_name_id": "nam_8e62c9e0a6e746e0a30360cc56d7e59e", "created_at": "2026-10-23T13:31:15.360Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-23T13:31:15.361Z',NULL,'create','entity','ent_72d50923739b4fd08a75a5ba9b59eea7',NULL,'{"id": "ent_72d50923739b4fd08a75a5ba9b59eea7", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T13:31:15.361Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-23T13:31:15.361Z',NULL,'create','name','nam_e4b1a904599442d58da8c39cbdebba21',NULL,'{"id": "nam_e4b1a904599442d58da8c39cbdebba21", "text": "Session", "entity_id": "ent_72d50923739b4fd08a75a5ba9b59eea7", "generated_from_name_id": null, "created_at": "2026-10-23T13:31:15.361Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-23T13:31:15.361Z',NULL,'update','entity','ent_72d50923739b4fd08a75a5ba9b59eea7','{"id": "ent_72d50923739b4fd08a75a5ba9b59eea7", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T13:31:15.361Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_72d50923739b4fd08a75a5ba9b59eea7", "description": "An authenticated visit.", "preferred_name_id": "nam_e4b1a904599442d58da8c39cbdebba21", "created_at": "2026-10-23T13:31:15.361Z", "updated_at": "2026-10-23T13:31:15.361Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-23T13:31:15.361Z',NULL,'create','name','nam_becd84754e7c41e5bed4fe6e8ac10d1f',NULL,'{"id": "nam_becd84754e7c41e5bed4fe6e8ac10d1f", "text": "Sessions", "entity_id": "ent_72d50923739b4fd08a75a5ba9b59eea7", "generated_from_name_id": "nam_e4b1a904599442d58da8c39cbdebba21", "created_at": "2026-10-23T13:31:15.361Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-23T13:31:15.362Z',NULL,'create','name','nam_e54db8fe03f9420e85f68a3e8c0f4d55',NULL,'{"id": "nam_e54db8fe03f9420e85f68a3e8c0f4d55", "text": "Sign-in", "entity_id": "ent_10b555d5310b45b3a215e18b6dc7276b", "generated_from_name_id": null, "created_at": "2026-10-23T13:31:15.362Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-23T13:31:15.362Z',NULL,'create','name','nam_aed725b495ad4171aa6bed2f5bc4d11c',NULL,'{"id": "nam_aed725b495ad4171aa6bed2f5bc4d11c", "text": "Sign-ins", "entity_id": "ent_10b555d5310b45b3a215e18b6dc7276b", "generated_from_name_id": "nam_e54db8fe03f9420e85f68a3e8c0f4d55", "created_at": "2026-10-23T13:31:15.362Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-23T13:31:15.362Z',NULL,'link','entity_link','ent_10b555d5310b45b3a215e18b6dc7276b|ent_72d50923739b4fd08a75a5ba9b59eea7|contains',NULL,'{"from_entity_id": "ent_10b555d5310b45b3a215e18b6dc7276b", "to_entity_id": "ent_72d50923739b4fd08a75a5ba9b59eea7", "link_type": "contains", "created_at": "2026-10-23T13:31:15.362Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-23T13:31:15.362Z',NULL,'create','statement','stm_018360ce78ae4f9196bb6269fe86ab69',NULL,'{"id": "stm_018360ce78ae4f9196bb6269fe86ab69", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-23T13:31:15.362Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-23T13:31:15.363Z',NULL,'create','statement','stm_5f15cc40fd574481888fc4905a2852c0',NULL,'{"id": "stm_5f15cc40fd574481888fc4905a2852c0", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-23T13:31:15.363Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-23T13:31:15.363Z',NULL,'create','statement','stm_7d6f9a0b49bd4bc2a771e48a6e7d4e42',NULL,'{"id": "stm_7d6f9a0b49bd4bc2a771e48a6e7d4e42", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-23T13:31:15.363Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-23T13:31:15.364Z',NULL,'create','statement','stm_9c17453468c545fd88e28a38f11dd5d8',NULL,'{"id": "stm_9c17453468c545fd88e28a38f11dd5d8", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-23T13:31:15.364Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-23T13:31:15.364Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_018360ce78ae4f9196bb6269fe86ab69", "to_id": "stm_5f15cc40fd574481888fc4905a2852c0", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_7d6f9a0b49bd4bc2a771e48a6e7d4e42"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
