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
INSERT INTO "history_events" VALUES(1,'2026-10-23T05:55:51.621Z',NULL,'create','entity','ent_360805df02134fdeaa7766f547e64e85',NULL,'{"id": "ent_360805df02134fdeaa7766f547e64e85", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T05:55:51.621Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-23T05:55:51.621Z',NULL,'create','name','nam_1d7e79f7cd2e44eb941487db04bdc772',NULL,'{"id": "nam_1d7e79f7cd2e44eb941487db04bdc772", "text": "Login", "entity_id": "ent_360805df02134fdeaa7766f547e64e85", "generated_from_name_id": null, "created_at": "2026-10-23T05:55:51.621Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-23T05:55:51.621Z',NULL,'update','entity','ent_360805df02134fdeaa7766f547e64e85','{"id": "ent_360805df02134fdeaa7766f547e64e85", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T05:55:51.621Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_360805df02134fdeaa7766f547e64e85", "description": "Signing in.", "preferred_name_id": "nam_1d7e79f7cd2e44eb941487db04bdc772", "created_at": "2026-10-23T05:55:51.621Z", "updated_at": "2026-10-23T05:55:51.621Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-23T05:55:51.630Z',NULL,'create','name','nam_f63d7f540b514e68a2a1ad03be588794',NULL,'{"id": "nam_f63d7f540b514e68a2a1ad03be588794", "text": "Logins", "entity_id": "ent_360805df02134fdeaa7766f547e64e85", "generated_from_name_id": "nam_1d7e79f7cd2e44eb941487db04bdc772", "created_at": "2026-10-23T05:55:51.630Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-23T05:55:51.632Z',NULL,'create','entity','ent_f0dd41b072384840800b5c2b2dd8bfdf',NULL,'{"id": "ent_f0dd41b072384840800b5c2b2dd8bfdf", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T05:55:51.632Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-23T05:55:51.632Z',NULL,'create','name','nam_e89ee8dc7a8d49d7b33210488767f86a',NULL,'{"id": "nam_e89ee8dc7a8d49d7b33210488767f86a", "text": "Session", "entity_id": "ent_f0dd41b072384840800b5c2b2dd8bfdf", "generated_from_name_id": null, "created_at": "2026-10-23T05:55:51.632Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-23T05:55:51.632Z',NULL,'update','entity','ent_f0dd41b072384840800b5c2b2dd8bfdf','{"id": "ent_f0dd41b072384840800b5c2b2dd8bfdf", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T05:55:51.632Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_f0dd41b072384840800b5c2b2dd8bfdf", "description": "An authenticated visit.", "preferred_name_id": "nam_e89ee8dc7a8d49d7b33210488767f86a", "created_at": "2026-10-23T05:55:51.632Z", "updated_at": "2026-10-23T05:55:51.632Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-23T05:55:51.632Z',NULL,'create','name','nam_78a9a5c40791496397d71cdcc6e6b88b',NULL,'{"id": "nam_78a9a5c40791496397d71cdcc6e6b88b", "text": "Sessions", "entity_id": "ent_f0dd41b072384840800b5c2b2dd8bfdf", "generated_from_name_id": "nam_e89ee8dc7a8d49d7b33210488767f86a", "created_at": "2026-10-23T05:55:51.632Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-23T05:55:51.633Z',NULL,'create','name','nam_dc8af8684f14470496ca02669d18e85e',NULL,'{"id": "nam_dc8af8684f14470496ca02669d18e85e", "text": "Sign-in", "entity_id": "ent_360805df02134fdeaa7766f547e64e85", "generated_from_name_id": null, "created_at": "2026-10-23T05:55:51.633Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-23T05:55:51.633Z',NULL,'create','name','nam_9a078c1c88854918be65198d6c20938e',NULL,'{"id": "nam_9a078c1c88854918be65198d6c20938e", "text": "Sign-ins", "entity_id": "ent_360805df02134fdeaa7766f547e64e85", "generated_from_name_id": "nam_dc8af8684f14470496ca02669d18e85e", "created_at": "2026-10-23T05:55:51.633Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-23T05:55:51.634Z',NULL,'link','entity_link','ent_360805df02134fdeaa7766f547e64e85|ent_f0dd41b072384840800b5c2b2dd8bfdf|contains',NULL,'{"from_entity_id": "ent_360805df02134fdeaa7766f547e64e85", "to_entity_id": "ent_f0dd41b072384840800b5c2b2dd8bfdf", "link_type": "contains", "created_at": "2026-10-23T05:55:51.634Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-23T05:55:51.635Z',NULL,'create','statement','stm_edb40dd7f1754f4ab1c83b40d0f1dad4',NULL,'{"id": "stm_edb40dd7f1754f4ab1c83b40d0f1dad4", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-23T05:55:51.635Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-23T05:55:51.636Z',NULL,'create','statement','stm_1957b6db576d4b00932c6aee3b0d01fc',NULL,'{"id": "stm_1957b6db576d4b00932c6aee3b0d01fc", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-23T05:55:51.636Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-23T05:55:51.637Z',NULL,'create','statement','stm_e2a93ae7bfb143e09d723d42f3eec22f',NULL,'{"id": "stm_e2a93ae7bfb143e09d723d42f3eec22f", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-23T05:55:51.637Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-23T05:55:51.638Z',NULL,'create','statement','stm_2c68af43435a4e2aab9c803df0d810b8',NULL,'{"id": "stm_2c68af43435a4e2aab9c803df0d810b8", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-23T05:55:51.638Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-23T05:55:51.639Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_edb40dd7f1754f4ab1c83b40d0f1dad4", "to_id": "stm_1957b6db576d4b00932c6aee3b0d01fc", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_e2a93ae7bfb143e09d723d42f3eec22f"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
