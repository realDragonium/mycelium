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
INSERT INTO "history_events" VALUES(1,'2026-10-23T04:21:13.340Z',NULL,'create','entity','ent_b9ff99fc221c4a1a946f6c66dfa63422',NULL,'{"id": "ent_b9ff99fc221c4a1a946f6c66dfa63422", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T04:21:13.340Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-23T04:21:13.340Z',NULL,'create','name','nam_bd62a2662fa54cb99e8482f978ce2514',NULL,'{"id": "nam_bd62a2662fa54cb99e8482f978ce2514", "text": "Login", "entity_id": "ent_b9ff99fc221c4a1a946f6c66dfa63422", "generated_from_name_id": null, "created_at": "2026-10-23T04:21:13.340Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-23T04:21:13.340Z',NULL,'update','entity','ent_b9ff99fc221c4a1a946f6c66dfa63422','{"id": "ent_b9ff99fc221c4a1a946f6c66dfa63422", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T04:21:13.340Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_b9ff99fc221c4a1a946f6c66dfa63422", "description": "Signing in.", "preferred_name_id": "nam_bd62a2662fa54cb99e8482f978ce2514", "created_at": "2026-10-23T04:21:13.340Z", "updated_at": "2026-10-23T04:21:13.340Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-23T04:21:13.344Z',NULL,'create','name','nam_faca8a278e3e415ea2b69d1380c5ef89',NULL,'{"id": "nam_faca8a278e3e415ea2b69d1380c5ef89", "text": "Logins", "entity_id": "ent_b9ff99fc221c4a1a946f6c66dfa63422", "generated_from_name_id": "nam_bd62a2662fa54cb99e8482f978ce2514", "created_at": "2026-10-23T04:21:13.344Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-23T04:21:13.344Z',NULL,'create','entity','ent_5fe8d99ccec9407f8484ce5ffd4cc831',NULL,'{"id": "ent_5fe8d99ccec9407f8484ce5ffd4cc831", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T04:21:13.344Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-23T04:21:13.344Z',NULL,'create','name','nam_e2c00cccec624b418b5fd919f36a1e24',NULL,'{"id": "nam_e2c00cccec624b418b5fd919f36a1e24", "text": "Session", "entity_id": "ent_5fe8d99ccec9407f8484ce5ffd4cc831", "generated_from_name_id": null, "created_at": "2026-10-23T04:21:13.344Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-23T04:21:13.344Z',NULL,'update','entity','ent_5fe8d99ccec9407f8484ce5ffd4cc831','{"id": "ent_5fe8d99ccec9407f8484ce5ffd4cc831", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T04:21:13.344Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_5fe8d99ccec9407f8484ce5ffd4cc831", "description": "An authenticated visit.", "preferred_name_id": "nam_e2c00cccec624b418b5fd919f36a1e24", "created_at": "2026-10-23T04:21:13.344Z", "updated_at": "2026-10-23T04:21:13.344Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-23T04:21:13.344Z',NULL,'create','name','nam_e0a9ac4f150c4c319acabdb633935225',NULL,'{"id": "nam_e0a9ac4f150c4c319acabdb633935225", "text": "Sessions", "entity_id": "ent_5fe8d99ccec9407f8484ce5ffd4cc831", "generated_from_name_id": "nam_e2c00cccec624b418b5fd919f36a1e24", "created_at": "2026-10-23T04:21:13.344Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-23T04:21:13.345Z',NULL,'create','name','nam_acd09c8569c14117acaf1852449ad89a',NULL,'{"id": "nam_acd09c8569c14117acaf1852449ad89a", "text": "Sign-in", "entity_id": "ent_b9ff99fc221c4a1a946f6c66dfa63422", "generated_from_name_id": null, "created_at": "2026-10-23T04:21:13.345Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-23T04:21:13.345Z',NULL,'create','name','nam_9410ad2b0484401aabe5a1378cfd90d2',NULL,'{"id": "nam_9410ad2b0484401aabe5a1378cfd90d2", "text": "Sign-ins", "entity_id": "ent_b9ff99fc221c4a1a946f6c66dfa63422", "generated_from_name_id": "nam_acd09c8569c14117acaf1852449ad89a", "created_at": "2026-10-23T04:21:13.345Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-23T04:21:13.345Z',NULL,'link','entity_link','ent_b9ff99fc221c4a1a946f6c66dfa63422|ent_5fe8d99ccec9407f8484ce5ffd4cc831|contains',NULL,'{"from_entity_id": "ent_b9ff99fc221c4a1a946f6c66dfa63422", "to_entity_id": "ent_5fe8d99ccec9407f8484ce5ffd4cc831", "link_type": "contains", "created_at": "2026-10-23T04:21:13.345Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-23T04:21:13.346Z',NULL,'create','statement','stm_7e155bedf4b54205aa2d7a07105703a7',NULL,'{"id": "stm_7e155bedf4b54205aa2d7a07105703a7", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-23T04:21:13.346Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-23T04:21:13.346Z',NULL,'create','statement','stm_a6d61da660cc4d4c99fc4eb3a83a38ea',NULL,'{"id": "stm_a6d61da660cc4d4c99fc4eb3a83a38ea", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-23T04:21:13.346Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-23T04:21:13.346Z',NULL,'create','statement','stm_bba1359f3b8f456982754548b7b31383',NULL,'{"id": "stm_bba1359f3b8f456982754548b7b31383", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-23T04:21:13.346Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-23T04:21:13.347Z',NULL,'create','statement','stm_999845b926d3421f9d6d80621465b6d6',NULL,'{"id": "stm_999845b926d3421f9d6d80621465b6d6", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-23T04:21:13.347Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-23T04:21:13.347Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_7e155bedf4b54205aa2d7a07105703a7", "to_id": "stm_a6d61da660cc4d4c99fc4eb3a83a38ea", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_bba1359f3b8f456982754548b7b31383"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
