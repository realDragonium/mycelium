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
INSERT INTO "history_events" VALUES(1,'2026-10-22T18:23:39.940Z',NULL,'create','entity','ent_dcfc287daa9b4e9bb7040431d06fdbfd',NULL,'{"id": "ent_dcfc287daa9b4e9bb7040431d06fdbfd", "description": "Signing in.", "created_at": "2026-10-22T18:23:39.940Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-22T18:23:39.940Z',NULL,'create','name','nam_843c52cd3bd148a5a8a9c2cc382b4110',NULL,'{"id": "nam_843c52cd3bd148a5a8a9c2cc382b4110", "text": "Login", "entity_id": "ent_dcfc287daa9b4e9bb7040431d06fdbfd", "generated_from_name_id": null, "created_at": "2026-10-22T18:23:39.940Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-22T18:23:39.949Z',NULL,'create','name','nam_71456c32b643443c82b60aab3d4ed3bc',NULL,'{"id": "nam_71456c32b643443c82b60aab3d4ed3bc", "text": "Logins", "entity_id": "ent_dcfc287daa9b4e9bb7040431d06fdbfd", "generated_from_name_id": "nam_843c52cd3bd148a5a8a9c2cc382b4110", "created_at": "2026-10-22T18:23:39.949Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-22T18:23:39.951Z',NULL,'create','entity','ent_1cf41b9a09334734a0dc10533ebe5955',NULL,'{"id": "ent_1cf41b9a09334734a0dc10533ebe5955", "description": "An authenticated visit.", "created_at": "2026-10-22T18:23:39.951Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-22T18:23:39.951Z',NULL,'create','name','nam_4af48afc4bac4b8f89885d4414b6c15f',NULL,'{"id": "nam_4af48afc4bac4b8f89885d4414b6c15f", "text": "Session", "entity_id": "ent_1cf41b9a09334734a0dc10533ebe5955", "generated_from_name_id": null, "created_at": "2026-10-22T18:23:39.951Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-22T18:23:39.951Z',NULL,'create','name','nam_6e238645c085437685a13895dda0eb9e',NULL,'{"id": "nam_6e238645c085437685a13895dda0eb9e", "text": "Sessions", "entity_id": "ent_1cf41b9a09334734a0dc10533ebe5955", "generated_from_name_id": "nam_4af48afc4bac4b8f89885d4414b6c15f", "created_at": "2026-10-22T18:23:39.951Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-22T18:23:39.953Z',NULL,'create','name','nam_0fdc6b9cddd14bc1a486ba0200e56125',NULL,'{"id": "nam_0fdc6b9cddd14bc1a486ba0200e56125", "text": "Sign-in", "entity_id": "ent_dcfc287daa9b4e9bb7040431d06fdbfd", "generated_from_name_id": null, "created_at": "2026-10-22T18:23:39.953Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-22T18:23:39.953Z',NULL,'create','name','nam_9e4e139192a44fe7b42eb1a3751e4b57',NULL,'{"id": "nam_9e4e139192a44fe7b42eb1a3751e4b57", "text": "Sign-ins", "entity_id": "ent_dcfc287daa9b4e9bb7040431d06fdbfd", "generated_from_name_id": "nam_0fdc6b9cddd14bc1a486ba0200e56125", "created_at": "2026-10-22T18:23:39.953Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-22T18:23:39.954Z',NULL,'link','entity_link','ent_dcfc287daa9b4e9bb7040431d06fdbfd|ent_1cf41b9a09334734a0dc10533ebe5955|contains',NULL,'{"from_entity_id": "ent_dcfc287daa9b4e9bb7040431d06fdbfd", "to_entity_id": "ent_1cf41b9a09334734a0dc10533ebe5955", "link_type": "contains", "created_at": "2026-10-22T18:23:39.954Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-22T18:23:39.955Z',NULL,'create','statement','stm_920edab7de004495a8cf23f519c9e911',NULL,'{"id": "stm_920edab7de004495a8cf23f519c9e911", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-22T18:23:39.955Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-22T18:23:39.956Z',NULL,'create','statement','stm_04de7487876e480c95ca1d2718b1d86c',NULL,'{"id": "stm_04de7487876e480c95ca1d2718b1d86c", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-22T18:23:39.956Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-22T18:23:39.957Z',NULL,'create','statement','stm_e1ffab96f684420d86b1273ba6b0a3f1',NULL,'{"id": "stm_e1ffab96f684420d86b1273ba6b0a3f1", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-22T18:23:39.957Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-22T18:23:39.958Z',NULL,'create','statement','stm_78db1281b9db4231a58d8520c5f7a031',NULL,'{"id": "stm_78db1281b9db4231a58d8520c5f7a031", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-22T18:23:39.958Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-22T18:23:39.960Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_920edab7de004495a8cf23f519c9e911", "to_id": "stm_04de7487876e480c95ca1d2718b1d86c", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_e1ffab96f684420d86b1273ba6b0a3f1"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',14);
COMMIT;
