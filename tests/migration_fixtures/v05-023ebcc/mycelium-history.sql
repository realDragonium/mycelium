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
INSERT INTO "history_events" VALUES(1,'2026-10-22T18:23:37.895Z',NULL,'create','entity','ent_a7a9761fc0b44240991308e3e69734cf',NULL,'{"id": "ent_a7a9761fc0b44240991308e3e69734cf", "description": "Signing in.", "created_at": "2026-10-22T18:23:37.895Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-22T18:23:37.895Z',NULL,'create','name','nam_76b7a7c7964d4a07a008dc00f7f79dcb',NULL,'{"id": "nam_76b7a7c7964d4a07a008dc00f7f79dcb", "text": "Login", "entity_id": "ent_a7a9761fc0b44240991308e3e69734cf", "generated_from_name_id": null, "created_at": "2026-10-22T18:23:37.895Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-22T18:23:37.904Z',NULL,'create','name','nam_8176f4453d954a748a5dbb6b5b435eea',NULL,'{"id": "nam_8176f4453d954a748a5dbb6b5b435eea", "text": "Logins", "entity_id": "ent_a7a9761fc0b44240991308e3e69734cf", "generated_from_name_id": "nam_76b7a7c7964d4a07a008dc00f7f79dcb", "created_at": "2026-10-22T18:23:37.904Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-22T18:23:37.905Z',NULL,'create','entity','ent_79dc201701214a4fafcc0f56093f892d',NULL,'{"id": "ent_79dc201701214a4fafcc0f56093f892d", "description": "An authenticated visit.", "created_at": "2026-10-22T18:23:37.905Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-22T18:23:37.906Z',NULL,'create','name','nam_fe529a8ad8f64d7fb38c62d577db115d',NULL,'{"id": "nam_fe529a8ad8f64d7fb38c62d577db115d", "text": "Session", "entity_id": "ent_79dc201701214a4fafcc0f56093f892d", "generated_from_name_id": null, "created_at": "2026-10-22T18:23:37.906Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-22T18:23:37.906Z',NULL,'create','name','nam_f843b55bef6b455fad43fd489015f219',NULL,'{"id": "nam_f843b55bef6b455fad43fd489015f219", "text": "Sessions", "entity_id": "ent_79dc201701214a4fafcc0f56093f892d", "generated_from_name_id": "nam_fe529a8ad8f64d7fb38c62d577db115d", "created_at": "2026-10-22T18:23:37.906Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-22T18:23:37.907Z',NULL,'create','name','nam_1b6eb5d81d78454a94534c5dc68934c6',NULL,'{"id": "nam_1b6eb5d81d78454a94534c5dc68934c6", "text": "Sign-in", "entity_id": "ent_a7a9761fc0b44240991308e3e69734cf", "generated_from_name_id": null, "created_at": "2026-10-22T18:23:37.907Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-22T18:23:37.908Z',NULL,'create','name','nam_301c55738c7741e2a74a5ffdf62d4c36',NULL,'{"id": "nam_301c55738c7741e2a74a5ffdf62d4c36", "text": "Sign-ins", "entity_id": "ent_a7a9761fc0b44240991308e3e69734cf", "generated_from_name_id": "nam_1b6eb5d81d78454a94534c5dc68934c6", "created_at": "2026-10-22T18:23:37.908Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-22T18:23:37.909Z',NULL,'link','entity_link','ent_a7a9761fc0b44240991308e3e69734cf|ent_79dc201701214a4fafcc0f56093f892d|contains',NULL,'{"from_entity_id": "ent_a7a9761fc0b44240991308e3e69734cf", "to_entity_id": "ent_79dc201701214a4fafcc0f56093f892d", "link_type": "contains", "created_at": "2026-10-22T18:23:37.908Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-22T18:23:37.909Z',NULL,'create','statement','stm_936d825299b848cfaf7432ca20f139a8',NULL,'{"id": "stm_936d825299b848cfaf7432ca20f139a8", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-22T18:23:37.909Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-22T18:23:37.911Z',NULL,'create','statement','stm_0b7e574d6f8543aa882f0751a0ade38a',NULL,'{"id": "stm_0b7e574d6f8543aa882f0751a0ade38a", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-22T18:23:37.911Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-22T18:23:37.912Z',NULL,'create','statement','stm_4bbe0dd3764c4af9add948a0b840467d',NULL,'{"id": "stm_4bbe0dd3764c4af9add948a0b840467d", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-22T18:23:37.912Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-22T18:23:37.913Z',NULL,'create','statement','stm_70a4c39f27974cca97eca2dd74bd63be',NULL,'{"id": "stm_70a4c39f27974cca97eca2dd74bd63be", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-22T18:23:37.913Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-22T18:23:37.915Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_936d825299b848cfaf7432ca20f139a8", "to_id": "stm_0b7e574d6f8543aa882f0751a0ade38a", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_4bbe0dd3764c4af9add948a0b840467d"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',14);
COMMIT;
