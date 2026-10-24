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
INSERT INTO "history_events" VALUES(1,'2026-10-24T08:34:26.975Z',NULL,'create','entity','ent_497f97e2db7e4063b363ea92c424370b',NULL,'{"id": "ent_497f97e2db7e4063b363ea92c424370b", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-24T08:34:26.975Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-24T08:34:26.975Z',NULL,'create','name','nam_bafb6bbb7dde4c0faeb7e6be34392329',NULL,'{"id": "nam_bafb6bbb7dde4c0faeb7e6be34392329", "text": "Login", "entity_id": "ent_497f97e2db7e4063b363ea92c424370b", "generated_from_name_id": null, "created_at": "2026-10-24T08:34:26.975Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-24T08:34:26.975Z',NULL,'update','entity','ent_497f97e2db7e4063b363ea92c424370b','{"id": "ent_497f97e2db7e4063b363ea92c424370b", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-24T08:34:26.975Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_497f97e2db7e4063b363ea92c424370b", "description": "Signing in.", "preferred_name_id": "nam_bafb6bbb7dde4c0faeb7e6be34392329", "created_at": "2026-10-24T08:34:26.975Z", "updated_at": "2026-10-24T08:34:26.975Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-24T08:34:26.975Z',NULL,'create','name','nam_e1b833781bce44a3822056c7a55209fe',NULL,'{"id": "nam_e1b833781bce44a3822056c7a55209fe", "text": "Logins", "entity_id": "ent_497f97e2db7e4063b363ea92c424370b", "generated_from_name_id": "nam_bafb6bbb7dde4c0faeb7e6be34392329", "created_at": "2026-10-24T08:34:26.975Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-24T08:34:26.976Z',NULL,'create','entity','ent_9911074c1ab54b679af5264c4cf1640b',NULL,'{"id": "ent_9911074c1ab54b679af5264c4cf1640b", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-24T08:34:26.976Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-24T08:34:26.976Z',NULL,'create','name','nam_3fdb5e6799cc45a08adb5f3c26d40b64',NULL,'{"id": "nam_3fdb5e6799cc45a08adb5f3c26d40b64", "text": "Session", "entity_id": "ent_9911074c1ab54b679af5264c4cf1640b", "generated_from_name_id": null, "created_at": "2026-10-24T08:34:26.976Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-24T08:34:26.976Z',NULL,'update','entity','ent_9911074c1ab54b679af5264c4cf1640b','{"id": "ent_9911074c1ab54b679af5264c4cf1640b", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-24T08:34:26.976Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_9911074c1ab54b679af5264c4cf1640b", "description": "An authenticated visit.", "preferred_name_id": "nam_3fdb5e6799cc45a08adb5f3c26d40b64", "created_at": "2026-10-24T08:34:26.976Z", "updated_at": "2026-10-24T08:34:26.976Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-24T08:34:26.976Z',NULL,'create','name','nam_cbabc5b5db5a4e4f8051841e363c402a',NULL,'{"id": "nam_cbabc5b5db5a4e4f8051841e363c402a", "text": "Sessions", "entity_id": "ent_9911074c1ab54b679af5264c4cf1640b", "generated_from_name_id": "nam_3fdb5e6799cc45a08adb5f3c26d40b64", "created_at": "2026-10-24T08:34:26.976Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-24T08:34:26.977Z',NULL,'create','name','nam_a40068187c754e76bc9817fd1d639165',NULL,'{"id": "nam_a40068187c754e76bc9817fd1d639165", "text": "Sign-in", "entity_id": "ent_497f97e2db7e4063b363ea92c424370b", "generated_from_name_id": null, "created_at": "2026-10-24T08:34:26.977Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-24T08:34:26.977Z',NULL,'create','name','nam_3c0c5712658348efbcf82fb483890e23',NULL,'{"id": "nam_3c0c5712658348efbcf82fb483890e23", "text": "Sign-ins", "entity_id": "ent_497f97e2db7e4063b363ea92c424370b", "generated_from_name_id": "nam_a40068187c754e76bc9817fd1d639165", "created_at": "2026-10-24T08:34:26.977Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-24T08:34:26.977Z',NULL,'link','entity_link','ent_497f97e2db7e4063b363ea92c424370b|ent_9911074c1ab54b679af5264c4cf1640b|contains',NULL,'{"from_entity_id": "ent_497f97e2db7e4063b363ea92c424370b", "to_entity_id": "ent_9911074c1ab54b679af5264c4cf1640b", "link_type": "contains", "created_at": "2026-10-24T08:34:26.977Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-24T08:34:26.978Z',NULL,'create','statement','stm_7f316c188acd401f94e320dc65138d97',NULL,'{"id": "stm_7f316c188acd401f94e320dc65138d97", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-24T08:34:26.978Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-24T08:34:26.978Z',NULL,'create','statement','stm_30fb654997b54f99ba6207d6c0cf6502',NULL,'{"id": "stm_30fb654997b54f99ba6207d6c0cf6502", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-24T08:34:26.978Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-24T08:34:26.979Z',NULL,'create','statement','stm_46eb6d102035420fbb9c5f3107e521dc',NULL,'{"id": "stm_46eb6d102035420fbb9c5f3107e521dc", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-24T08:34:26.979Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-24T08:34:26.979Z',NULL,'create','statement','stm_dedb66d31f564b3b8f262458a686334b',NULL,'{"id": "stm_dedb66d31f564b3b8f262458a686334b", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-24T08:34:26.979Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-24T08:34:26.980Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_7f316c188acd401f94e320dc65138d97", "to_id": "stm_30fb654997b54f99ba6207d6c0cf6502", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_46eb6d102035420fbb9c5f3107e521dc"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
