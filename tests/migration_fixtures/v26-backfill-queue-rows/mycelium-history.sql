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
INSERT INTO "history_events" VALUES(1,'2026-10-24T10:17:25.887Z',NULL,'create','entity','ent_f2262406ac7147f9aafaf714b4dc8448',NULL,'{"id": "ent_f2262406ac7147f9aafaf714b4dc8448", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-24T10:17:25.887Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-24T10:17:25.887Z',NULL,'create','name','nam_5a09a3abb8ef49028d3216ac0b2a9d22',NULL,'{"id": "nam_5a09a3abb8ef49028d3216ac0b2a9d22", "text": "Login", "entity_id": "ent_f2262406ac7147f9aafaf714b4dc8448", "generated_from_name_id": null, "created_at": "2026-10-24T10:17:25.887Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-24T10:17:25.887Z',NULL,'update','entity','ent_f2262406ac7147f9aafaf714b4dc8448','{"id": "ent_f2262406ac7147f9aafaf714b4dc8448", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-24T10:17:25.887Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_f2262406ac7147f9aafaf714b4dc8448", "description": "Signing in.", "preferred_name_id": "nam_5a09a3abb8ef49028d3216ac0b2a9d22", "created_at": "2026-10-24T10:17:25.887Z", "updated_at": "2026-10-24T10:17:25.887Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-24T10:17:25.888Z',NULL,'create','name','nam_b4759b4d9bf74fe88e83760f4beaa6c0',NULL,'{"id": "nam_b4759b4d9bf74fe88e83760f4beaa6c0", "text": "Logins", "entity_id": "ent_f2262406ac7147f9aafaf714b4dc8448", "generated_from_name_id": "nam_5a09a3abb8ef49028d3216ac0b2a9d22", "created_at": "2026-10-24T10:17:25.888Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-24T10:17:25.889Z',NULL,'create','entity','ent_4ca80502895b4c80b3b90783aaa208d5',NULL,'{"id": "ent_4ca80502895b4c80b3b90783aaa208d5", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-24T10:17:25.889Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-24T10:17:25.889Z',NULL,'create','name','nam_141952b514ad403fb2d914b2bfad5453',NULL,'{"id": "nam_141952b514ad403fb2d914b2bfad5453", "text": "Session", "entity_id": "ent_4ca80502895b4c80b3b90783aaa208d5", "generated_from_name_id": null, "created_at": "2026-10-24T10:17:25.889Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-24T10:17:25.889Z',NULL,'update','entity','ent_4ca80502895b4c80b3b90783aaa208d5','{"id": "ent_4ca80502895b4c80b3b90783aaa208d5", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-24T10:17:25.889Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_4ca80502895b4c80b3b90783aaa208d5", "description": "An authenticated visit.", "preferred_name_id": "nam_141952b514ad403fb2d914b2bfad5453", "created_at": "2026-10-24T10:17:25.889Z", "updated_at": "2026-10-24T10:17:25.889Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-24T10:17:25.889Z',NULL,'create','name','nam_465ec88282164c85a5906fda86b1ef30',NULL,'{"id": "nam_465ec88282164c85a5906fda86b1ef30", "text": "Sessions", "entity_id": "ent_4ca80502895b4c80b3b90783aaa208d5", "generated_from_name_id": "nam_141952b514ad403fb2d914b2bfad5453", "created_at": "2026-10-24T10:17:25.889Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-24T10:17:25.889Z',NULL,'create','name','nam_2f489b23a6674264b672ed9d4ecbcec8',NULL,'{"id": "nam_2f489b23a6674264b672ed9d4ecbcec8", "text": "Sign-in", "entity_id": "ent_f2262406ac7147f9aafaf714b4dc8448", "generated_from_name_id": null, "created_at": "2026-10-24T10:17:25.889Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-24T10:17:25.890Z',NULL,'create','name','nam_9d0754c9c45f4231a6ec1573935c77e3',NULL,'{"id": "nam_9d0754c9c45f4231a6ec1573935c77e3", "text": "Sign-ins", "entity_id": "ent_f2262406ac7147f9aafaf714b4dc8448", "generated_from_name_id": "nam_2f489b23a6674264b672ed9d4ecbcec8", "created_at": "2026-10-24T10:17:25.890Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-24T10:17:25.890Z',NULL,'link','entity_link','ent_f2262406ac7147f9aafaf714b4dc8448|ent_4ca80502895b4c80b3b90783aaa208d5|contains',NULL,'{"from_entity_id": "ent_f2262406ac7147f9aafaf714b4dc8448", "to_entity_id": "ent_4ca80502895b4c80b3b90783aaa208d5", "link_type": "contains", "created_at": "2026-10-24T10:17:25.890Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-24T10:17:25.890Z',NULL,'create','statement','stm_ea66760a23b5462fa2c1523efd3b9a05',NULL,'{"id": "stm_ea66760a23b5462fa2c1523efd3b9a05", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-24T10:17:25.890Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-24T10:17:25.891Z',NULL,'create','statement','stm_2359299b347443e5a0c0e91978840c3b',NULL,'{"id": "stm_2359299b347443e5a0c0e91978840c3b", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-24T10:17:25.891Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-24T10:17:25.891Z',NULL,'create','statement','stm_1cca1ba5c4a34ed789550fa0e3149970',NULL,'{"id": "stm_1cca1ba5c4a34ed789550fa0e3149970", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-24T10:17:25.891Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-24T10:17:25.892Z',NULL,'create','statement','stm_0a88f905592741a8b73966df5fa79109',NULL,'{"id": "stm_0a88f905592741a8b73966df5fa79109", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-24T10:17:25.892Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-24T10:17:25.892Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_ea66760a23b5462fa2c1523efd3b9a05", "to_id": "stm_2359299b347443e5a0c0e91978840c3b", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_1cca1ba5c4a34ed789550fa0e3149970"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
