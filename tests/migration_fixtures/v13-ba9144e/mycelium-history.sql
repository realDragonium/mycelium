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
INSERT INTO "history_events" VALUES(1,'2026-10-22T18:38:57.663Z',NULL,'create','entity','ent_de81cc0ce13540eba0ba79160e7be90b',NULL,'{"id": "ent_de81cc0ce13540eba0ba79160e7be90b", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-22T18:38:57.663Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-22T18:38:57.663Z',NULL,'create','name','nam_ef8caf40d47e48d3ba13b6e0f6967ed5',NULL,'{"id": "nam_ef8caf40d47e48d3ba13b6e0f6967ed5", "text": "Login", "entity_id": "ent_de81cc0ce13540eba0ba79160e7be90b", "generated_from_name_id": null, "created_at": "2026-10-22T18:38:57.663Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-22T18:38:57.663Z',NULL,'update','entity','ent_de81cc0ce13540eba0ba79160e7be90b','{"id": "ent_de81cc0ce13540eba0ba79160e7be90b", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-22T18:38:57.663Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_de81cc0ce13540eba0ba79160e7be90b", "description": "Signing in.", "preferred_name_id": "nam_ef8caf40d47e48d3ba13b6e0f6967ed5", "created_at": "2026-10-22T18:38:57.663Z", "updated_at": "2026-10-22T18:38:57.663Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-22T18:38:57.672Z',NULL,'create','name','nam_b722fa6dd1264be286ecfebfe71ecb7c',NULL,'{"id": "nam_b722fa6dd1264be286ecfebfe71ecb7c", "text": "Logins", "entity_id": "ent_de81cc0ce13540eba0ba79160e7be90b", "generated_from_name_id": "nam_ef8caf40d47e48d3ba13b6e0f6967ed5", "created_at": "2026-10-22T18:38:57.672Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-22T18:38:57.674Z',NULL,'create','entity','ent_1982b47d2e9741f092902f731eeabe46',NULL,'{"id": "ent_1982b47d2e9741f092902f731eeabe46", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-22T18:38:57.674Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-22T18:38:57.674Z',NULL,'create','name','nam_1acd8b4c597c427f943ae75497dbecc2',NULL,'{"id": "nam_1acd8b4c597c427f943ae75497dbecc2", "text": "Session", "entity_id": "ent_1982b47d2e9741f092902f731eeabe46", "generated_from_name_id": null, "created_at": "2026-10-22T18:38:57.674Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-22T18:38:57.674Z',NULL,'update','entity','ent_1982b47d2e9741f092902f731eeabe46','{"id": "ent_1982b47d2e9741f092902f731eeabe46", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-22T18:38:57.674Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_1982b47d2e9741f092902f731eeabe46", "description": "An authenticated visit.", "preferred_name_id": "nam_1acd8b4c597c427f943ae75497dbecc2", "created_at": "2026-10-22T18:38:57.674Z", "updated_at": "2026-10-22T18:38:57.674Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-22T18:38:57.674Z',NULL,'create','name','nam_23f70210ed8e45c7a6640a14e72ee437',NULL,'{"id": "nam_23f70210ed8e45c7a6640a14e72ee437", "text": "Sessions", "entity_id": "ent_1982b47d2e9741f092902f731eeabe46", "generated_from_name_id": "nam_1acd8b4c597c427f943ae75497dbecc2", "created_at": "2026-10-22T18:38:57.674Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-22T18:38:57.676Z',NULL,'create','name','nam_add77bc6aea34ef88065111ab2f2fa4f',NULL,'{"id": "nam_add77bc6aea34ef88065111ab2f2fa4f", "text": "Sign-in", "entity_id": "ent_de81cc0ce13540eba0ba79160e7be90b", "generated_from_name_id": null, "created_at": "2026-10-22T18:38:57.676Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-22T18:38:57.676Z',NULL,'create','name','nam_ae7c7f9813aa4903a6dd9093ac2a662b',NULL,'{"id": "nam_ae7c7f9813aa4903a6dd9093ac2a662b", "text": "Sign-ins", "entity_id": "ent_de81cc0ce13540eba0ba79160e7be90b", "generated_from_name_id": "nam_add77bc6aea34ef88065111ab2f2fa4f", "created_at": "2026-10-22T18:38:57.676Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-22T18:38:57.677Z',NULL,'link','entity_link','ent_de81cc0ce13540eba0ba79160e7be90b|ent_1982b47d2e9741f092902f731eeabe46|contains',NULL,'{"from_entity_id": "ent_de81cc0ce13540eba0ba79160e7be90b", "to_entity_id": "ent_1982b47d2e9741f092902f731eeabe46", "link_type": "contains", "created_at": "2026-10-22T18:38:57.677Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-22T18:38:57.678Z',NULL,'create','statement','stm_9d5d045e01fc40d79ff86a5dab5bcce9',NULL,'{"id": "stm_9d5d045e01fc40d79ff86a5dab5bcce9", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-22T18:38:57.678Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-22T18:38:57.679Z',NULL,'create','statement','stm_40449d2bc5b74ef0823128d4e1e86f2e',NULL,'{"id": "stm_40449d2bc5b74ef0823128d4e1e86f2e", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-22T18:38:57.679Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-22T18:38:57.681Z',NULL,'create','statement','stm_3275e96b7644454fa622e3e49d790a50',NULL,'{"id": "stm_3275e96b7644454fa622e3e49d790a50", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-22T18:38:57.681Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-22T18:38:57.682Z',NULL,'create','statement','stm_0926417531734cf3ab59fd7fdb660cee',NULL,'{"id": "stm_0926417531734cf3ab59fd7fdb660cee", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-22T18:38:57.682Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-22T18:38:57.683Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_9d5d045e01fc40d79ff86a5dab5bcce9", "to_id": "stm_40449d2bc5b74ef0823128d4e1e86f2e", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_3275e96b7644454fa622e3e49d790a50"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
