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
INSERT INTO "history_events" VALUES(1,'2026-10-22T18:38:44.167Z',NULL,'create','entity','ent_70f32e2bd1e14438976fbf3b7ad0de54',NULL,'{"id": "ent_70f32e2bd1e14438976fbf3b7ad0de54", "description": "Signing in.", "created_at": "2026-10-22T18:38:44.167Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-22T18:38:44.167Z',NULL,'create','name','nam_20d31be5a7c14db0ae0829b2145d9125',NULL,'{"id": "nam_20d31be5a7c14db0ae0829b2145d9125", "text": "Login", "entity_id": "ent_70f32e2bd1e14438976fbf3b7ad0de54", "generated_from_name_id": null, "created_at": "2026-10-22T18:38:44.167Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-22T18:38:44.177Z',NULL,'create','name','nam_acb8713b11be4348aee16ac1f6cc5811',NULL,'{"id": "nam_acb8713b11be4348aee16ac1f6cc5811", "text": "Logins", "entity_id": "ent_70f32e2bd1e14438976fbf3b7ad0de54", "generated_from_name_id": "nam_20d31be5a7c14db0ae0829b2145d9125", "created_at": "2026-10-22T18:38:44.177Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-22T18:38:44.178Z',NULL,'create','entity','ent_0090b72e0f094bcdb8eab2a251e7e4e1',NULL,'{"id": "ent_0090b72e0f094bcdb8eab2a251e7e4e1", "description": "An authenticated visit.", "created_at": "2026-10-22T18:38:44.178Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-22T18:38:44.178Z',NULL,'create','name','nam_bd31974a09294568b583efb5f5475a19',NULL,'{"id": "nam_bd31974a09294568b583efb5f5475a19", "text": "Session", "entity_id": "ent_0090b72e0f094bcdb8eab2a251e7e4e1", "generated_from_name_id": null, "created_at": "2026-10-22T18:38:44.178Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-22T18:38:44.179Z',NULL,'create','name','nam_12aef12bcf784bb0922ec8ee5450ff3c',NULL,'{"id": "nam_12aef12bcf784bb0922ec8ee5450ff3c", "text": "Sessions", "entity_id": "ent_0090b72e0f094bcdb8eab2a251e7e4e1", "generated_from_name_id": "nam_bd31974a09294568b583efb5f5475a19", "created_at": "2026-10-22T18:38:44.179Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-22T18:38:44.180Z',NULL,'create','name','nam_663d655b1f7542f89a52e762d24056ff',NULL,'{"id": "nam_663d655b1f7542f89a52e762d24056ff", "text": "Sign-in", "entity_id": "ent_70f32e2bd1e14438976fbf3b7ad0de54", "generated_from_name_id": null, "created_at": "2026-10-22T18:38:44.180Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-22T18:38:44.181Z',NULL,'create','name','nam_f9cc0b3a40464bbf8be2bd4fe79e19fd',NULL,'{"id": "nam_f9cc0b3a40464bbf8be2bd4fe79e19fd", "text": "Sign-ins", "entity_id": "ent_70f32e2bd1e14438976fbf3b7ad0de54", "generated_from_name_id": "nam_663d655b1f7542f89a52e762d24056ff", "created_at": "2026-10-22T18:38:44.180Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-22T18:38:44.182Z',NULL,'link','entity_link','ent_70f32e2bd1e14438976fbf3b7ad0de54|ent_0090b72e0f094bcdb8eab2a251e7e4e1|contains',NULL,'{"from_entity_id": "ent_70f32e2bd1e14438976fbf3b7ad0de54", "to_entity_id": "ent_0090b72e0f094bcdb8eab2a251e7e4e1", "link_type": "contains", "created_at": "2026-10-22T18:38:44.181Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-22T18:38:44.183Z',NULL,'create','statement','stm_c3916517d6644fce8342b92cbd56a3fd',NULL,'{"id": "stm_c3916517d6644fce8342b92cbd56a3fd", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-22T18:38:44.182Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-22T18:38:44.184Z',NULL,'create','statement','stm_6043625116ef488eac5d4e08c386ee6a',NULL,'{"id": "stm_6043625116ef488eac5d4e08c386ee6a", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-22T18:38:44.184Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-22T18:38:44.185Z',NULL,'create','statement','stm_f1704741d828438c8a1dba7cc3220f5d',NULL,'{"id": "stm_f1704741d828438c8a1dba7cc3220f5d", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-22T18:38:44.185Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-22T18:38:44.186Z',NULL,'create','statement','stm_00e3e96abfeb40dd82579e0924f28f66',NULL,'{"id": "stm_00e3e96abfeb40dd82579e0924f28f66", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-22T18:38:44.186Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-22T18:38:44.188Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_c3916517d6644fce8342b92cbd56a3fd", "to_id": "stm_6043625116ef488eac5d4e08c386ee6a", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_f1704741d828438c8a1dba7cc3220f5d"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',14);
COMMIT;
