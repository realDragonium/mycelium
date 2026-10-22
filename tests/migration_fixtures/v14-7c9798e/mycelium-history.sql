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
INSERT INTO "history_events" VALUES(1,'2026-10-22T18:39:02.672Z',NULL,'create','entity','ent_054e62d96e314c3e9835cb6565ea721f',NULL,'{"id": "ent_054e62d96e314c3e9835cb6565ea721f", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-22T18:39:02.672Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-22T18:39:02.673Z',NULL,'create','name','nam_a4dddf2a972645e19802e7bbefd27c73',NULL,'{"id": "nam_a4dddf2a972645e19802e7bbefd27c73", "text": "Login", "entity_id": "ent_054e62d96e314c3e9835cb6565ea721f", "generated_from_name_id": null, "created_at": "2026-10-22T18:39:02.673Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-22T18:39:02.673Z',NULL,'update','entity','ent_054e62d96e314c3e9835cb6565ea721f','{"id": "ent_054e62d96e314c3e9835cb6565ea721f", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-22T18:39:02.672Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_054e62d96e314c3e9835cb6565ea721f", "description": "Signing in.", "preferred_name_id": "nam_a4dddf2a972645e19802e7bbefd27c73", "created_at": "2026-10-22T18:39:02.672Z", "updated_at": "2026-10-22T18:39:02.673Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-22T18:39:02.682Z',NULL,'create','name','nam_6d0eb65822c44fa2877e8bebfd8bd638',NULL,'{"id": "nam_6d0eb65822c44fa2877e8bebfd8bd638", "text": "Logins", "entity_id": "ent_054e62d96e314c3e9835cb6565ea721f", "generated_from_name_id": "nam_a4dddf2a972645e19802e7bbefd27c73", "created_at": "2026-10-22T18:39:02.682Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-22T18:39:02.684Z',NULL,'create','entity','ent_78cbf98fc2f74ba5838af643bdd07b9b',NULL,'{"id": "ent_78cbf98fc2f74ba5838af643bdd07b9b", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-22T18:39:02.684Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-22T18:39:02.684Z',NULL,'create','name','nam_3ab02a56886f4630a2d35ab01e07956a',NULL,'{"id": "nam_3ab02a56886f4630a2d35ab01e07956a", "text": "Session", "entity_id": "ent_78cbf98fc2f74ba5838af643bdd07b9b", "generated_from_name_id": null, "created_at": "2026-10-22T18:39:02.684Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-22T18:39:02.684Z',NULL,'update','entity','ent_78cbf98fc2f74ba5838af643bdd07b9b','{"id": "ent_78cbf98fc2f74ba5838af643bdd07b9b", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-22T18:39:02.684Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_78cbf98fc2f74ba5838af643bdd07b9b", "description": "An authenticated visit.", "preferred_name_id": "nam_3ab02a56886f4630a2d35ab01e07956a", "created_at": "2026-10-22T18:39:02.684Z", "updated_at": "2026-10-22T18:39:02.684Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-22T18:39:02.685Z',NULL,'create','name','nam_58771f6d6b364141ab17b87794331391',NULL,'{"id": "nam_58771f6d6b364141ab17b87794331391", "text": "Sessions", "entity_id": "ent_78cbf98fc2f74ba5838af643bdd07b9b", "generated_from_name_id": "nam_3ab02a56886f4630a2d35ab01e07956a", "created_at": "2026-10-22T18:39:02.685Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-22T18:39:02.686Z',NULL,'create','name','nam_cbb3fa4c77f8458cb84faf12a614765b',NULL,'{"id": "nam_cbb3fa4c77f8458cb84faf12a614765b", "text": "Sign-in", "entity_id": "ent_054e62d96e314c3e9835cb6565ea721f", "generated_from_name_id": null, "created_at": "2026-10-22T18:39:02.686Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-22T18:39:02.687Z',NULL,'create','name','nam_dbcc16c21c2f434395a4e4618c184625',NULL,'{"id": "nam_dbcc16c21c2f434395a4e4618c184625", "text": "Sign-ins", "entity_id": "ent_054e62d96e314c3e9835cb6565ea721f", "generated_from_name_id": "nam_cbb3fa4c77f8458cb84faf12a614765b", "created_at": "2026-10-22T18:39:02.687Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-22T18:39:02.688Z',NULL,'link','entity_link','ent_054e62d96e314c3e9835cb6565ea721f|ent_78cbf98fc2f74ba5838af643bdd07b9b|contains',NULL,'{"from_entity_id": "ent_054e62d96e314c3e9835cb6565ea721f", "to_entity_id": "ent_78cbf98fc2f74ba5838af643bdd07b9b", "link_type": "contains", "created_at": "2026-10-22T18:39:02.688Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-22T18:39:02.690Z',NULL,'create','statement','stm_880c56e87c8d4ffba695e0cda9dae0e6',NULL,'{"id": "stm_880c56e87c8d4ffba695e0cda9dae0e6", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-22T18:39:02.689Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-22T18:39:02.692Z',NULL,'create','statement','stm_09e40bb387fe41bfb8bac2b366eec3ba',NULL,'{"id": "stm_09e40bb387fe41bfb8bac2b366eec3ba", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-22T18:39:02.692Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-22T18:39:02.693Z',NULL,'create','statement','stm_77642bba2ac646288545c44e96b2847c',NULL,'{"id": "stm_77642bba2ac646288545c44e96b2847c", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-22T18:39:02.693Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-22T18:39:02.695Z',NULL,'create','statement','stm_dfe0d5f69d9d430aa1fc6294c16daa4c',NULL,'{"id": "stm_dfe0d5f69d9d430aa1fc6294c16daa4c", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-22T18:39:02.695Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-22T18:39:02.696Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_880c56e87c8d4ffba695e0cda9dae0e6", "to_id": "stm_09e40bb387fe41bfb8bac2b366eec3ba", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_77642bba2ac646288545c44e96b2847c"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
