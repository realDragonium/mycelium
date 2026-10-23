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
INSERT INTO "history_events" VALUES(1,'2026-10-23T19:04:14.316Z',NULL,'create','entity','ent_57ed2c94c0a948ef833e8a5da631a94a',NULL,'{"id": "ent_57ed2c94c0a948ef833e8a5da631a94a", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T19:04:14.316Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-23T19:04:14.316Z',NULL,'create','name','nam_19c4572951404d7ab0bb9ec787b9d8ec',NULL,'{"id": "nam_19c4572951404d7ab0bb9ec787b9d8ec", "text": "Login", "entity_id": "ent_57ed2c94c0a948ef833e8a5da631a94a", "generated_from_name_id": null, "created_at": "2026-10-23T19:04:14.316Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-23T19:04:14.317Z',NULL,'update','entity','ent_57ed2c94c0a948ef833e8a5da631a94a','{"id": "ent_57ed2c94c0a948ef833e8a5da631a94a", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T19:04:14.316Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_57ed2c94c0a948ef833e8a5da631a94a", "description": "Signing in.", "preferred_name_id": "nam_19c4572951404d7ab0bb9ec787b9d8ec", "created_at": "2026-10-23T19:04:14.316Z", "updated_at": "2026-10-23T19:04:14.316Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-23T19:04:14.320Z',NULL,'create','name','nam_aab49f0bed844f0b84bf1edb43cf37b9',NULL,'{"id": "nam_aab49f0bed844f0b84bf1edb43cf37b9", "text": "Logins", "entity_id": "ent_57ed2c94c0a948ef833e8a5da631a94a", "generated_from_name_id": "nam_19c4572951404d7ab0bb9ec787b9d8ec", "created_at": "2026-10-23T19:04:14.320Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-23T19:04:14.321Z',NULL,'create','entity','ent_453c988308904f3c8b590181c4b2cdaa',NULL,'{"id": "ent_453c988308904f3c8b590181c4b2cdaa", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T19:04:14.321Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-23T19:04:14.321Z',NULL,'create','name','nam_5742bdc88476408fa7e8b9cc873793a7',NULL,'{"id": "nam_5742bdc88476408fa7e8b9cc873793a7", "text": "Session", "entity_id": "ent_453c988308904f3c8b590181c4b2cdaa", "generated_from_name_id": null, "created_at": "2026-10-23T19:04:14.321Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-23T19:04:14.321Z',NULL,'update','entity','ent_453c988308904f3c8b590181c4b2cdaa','{"id": "ent_453c988308904f3c8b590181c4b2cdaa", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T19:04:14.321Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_453c988308904f3c8b590181c4b2cdaa", "description": "An authenticated visit.", "preferred_name_id": "nam_5742bdc88476408fa7e8b9cc873793a7", "created_at": "2026-10-23T19:04:14.321Z", "updated_at": "2026-10-23T19:04:14.321Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-23T19:04:14.321Z',NULL,'create','name','nam_c422736258854f1592c3f9beb935c5a8',NULL,'{"id": "nam_c422736258854f1592c3f9beb935c5a8", "text": "Sessions", "entity_id": "ent_453c988308904f3c8b590181c4b2cdaa", "generated_from_name_id": "nam_5742bdc88476408fa7e8b9cc873793a7", "created_at": "2026-10-23T19:04:14.321Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-23T19:04:14.321Z',NULL,'create','name','nam_be0e20c0935a404ebb5180451e9186e3',NULL,'{"id": "nam_be0e20c0935a404ebb5180451e9186e3", "text": "Sign-in", "entity_id": "ent_57ed2c94c0a948ef833e8a5da631a94a", "generated_from_name_id": null, "created_at": "2026-10-23T19:04:14.321Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-23T19:04:14.322Z',NULL,'create','name','nam_b3d207e3f5cf48b98245c724445844ae',NULL,'{"id": "nam_b3d207e3f5cf48b98245c724445844ae", "text": "Sign-ins", "entity_id": "ent_57ed2c94c0a948ef833e8a5da631a94a", "generated_from_name_id": "nam_be0e20c0935a404ebb5180451e9186e3", "created_at": "2026-10-23T19:04:14.322Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-23T19:04:14.322Z',NULL,'link','entity_link','ent_57ed2c94c0a948ef833e8a5da631a94a|ent_453c988308904f3c8b590181c4b2cdaa|contains',NULL,'{"from_entity_id": "ent_57ed2c94c0a948ef833e8a5da631a94a", "to_entity_id": "ent_453c988308904f3c8b590181c4b2cdaa", "link_type": "contains", "created_at": "2026-10-23T19:04:14.322Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-23T19:04:14.322Z',NULL,'create','statement','stm_6f5605bca7e441c590af87ab2b739625',NULL,'{"id": "stm_6f5605bca7e441c590af87ab2b739625", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-23T19:04:14.322Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-23T19:04:14.323Z',NULL,'create','statement','stm_9f6c72d694aa46309719016dd142ff51',NULL,'{"id": "stm_9f6c72d694aa46309719016dd142ff51", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-23T19:04:14.323Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-23T19:04:14.323Z',NULL,'create','statement','stm_d6108522f9d14f30a9a97170a4659f55',NULL,'{"id": "stm_d6108522f9d14f30a9a97170a4659f55", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-23T19:04:14.323Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-23T19:04:14.324Z',NULL,'create','statement','stm_a80985d6e1e24db7a18f821467b49b8b',NULL,'{"id": "stm_a80985d6e1e24db7a18f821467b49b8b", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-23T19:04:14.324Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-23T19:04:14.324Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_6f5605bca7e441c590af87ab2b739625", "to_id": "stm_9f6c72d694aa46309719016dd142ff51", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_d6108522f9d14f30a9a97170a4659f55"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
