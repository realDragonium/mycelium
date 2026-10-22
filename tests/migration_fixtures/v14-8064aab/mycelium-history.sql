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
INSERT INTO "history_events" VALUES(1,'2026-10-22T18:39:00.111Z',NULL,'create','entity','ent_fd88cee10c974d92a3bf59bdc9d7d4e8',NULL,'{"id": "ent_fd88cee10c974d92a3bf59bdc9d7d4e8", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-22T18:39:00.111Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-22T18:39:00.112Z',NULL,'create','name','nam_d6fd0e01020947ecaf6b24a9b163e443',NULL,'{"id": "nam_d6fd0e01020947ecaf6b24a9b163e443", "text": "Login", "entity_id": "ent_fd88cee10c974d92a3bf59bdc9d7d4e8", "generated_from_name_id": null, "created_at": "2026-10-22T18:39:00.112Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-22T18:39:00.112Z',NULL,'update','entity','ent_fd88cee10c974d92a3bf59bdc9d7d4e8','{"id": "ent_fd88cee10c974d92a3bf59bdc9d7d4e8", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-22T18:39:00.111Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_fd88cee10c974d92a3bf59bdc9d7d4e8", "description": "Signing in.", "preferred_name_id": "nam_d6fd0e01020947ecaf6b24a9b163e443", "created_at": "2026-10-22T18:39:00.111Z", "updated_at": "2026-10-22T18:39:00.112Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-22T18:39:00.120Z',NULL,'create','name','nam_8bc119ae1a984034823d98846dd02e9c',NULL,'{"id": "nam_8bc119ae1a984034823d98846dd02e9c", "text": "Logins", "entity_id": "ent_fd88cee10c974d92a3bf59bdc9d7d4e8", "generated_from_name_id": "nam_d6fd0e01020947ecaf6b24a9b163e443", "created_at": "2026-10-22T18:39:00.120Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-22T18:39:00.121Z',NULL,'create','entity','ent_b61160bfef1b4237bf2b7937cbea51a0',NULL,'{"id": "ent_b61160bfef1b4237bf2b7937cbea51a0", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-22T18:39:00.121Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-22T18:39:00.122Z',NULL,'create','name','nam_c5e81234113f4cdfaf016a6bf0d6f91d',NULL,'{"id": "nam_c5e81234113f4cdfaf016a6bf0d6f91d", "text": "Session", "entity_id": "ent_b61160bfef1b4237bf2b7937cbea51a0", "generated_from_name_id": null, "created_at": "2026-10-22T18:39:00.122Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-22T18:39:00.122Z',NULL,'update','entity','ent_b61160bfef1b4237bf2b7937cbea51a0','{"id": "ent_b61160bfef1b4237bf2b7937cbea51a0", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-22T18:39:00.121Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_b61160bfef1b4237bf2b7937cbea51a0", "description": "An authenticated visit.", "preferred_name_id": "nam_c5e81234113f4cdfaf016a6bf0d6f91d", "created_at": "2026-10-22T18:39:00.121Z", "updated_at": "2026-10-22T18:39:00.122Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-22T18:39:00.122Z',NULL,'create','name','nam_23c17fa782bb4b6d9d0ebaa27451ba43',NULL,'{"id": "nam_23c17fa782bb4b6d9d0ebaa27451ba43", "text": "Sessions", "entity_id": "ent_b61160bfef1b4237bf2b7937cbea51a0", "generated_from_name_id": "nam_c5e81234113f4cdfaf016a6bf0d6f91d", "created_at": "2026-10-22T18:39:00.122Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-22T18:39:00.123Z',NULL,'create','name','nam_b60f3d0dfb574b9f934ce5cd379205af',NULL,'{"id": "nam_b60f3d0dfb574b9f934ce5cd379205af", "text": "Sign-in", "entity_id": "ent_fd88cee10c974d92a3bf59bdc9d7d4e8", "generated_from_name_id": null, "created_at": "2026-10-22T18:39:00.123Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-22T18:39:00.123Z',NULL,'create','name','nam_89f2fb50ccb5437f887479d783a5afa8',NULL,'{"id": "nam_89f2fb50ccb5437f887479d783a5afa8", "text": "Sign-ins", "entity_id": "ent_fd88cee10c974d92a3bf59bdc9d7d4e8", "generated_from_name_id": "nam_b60f3d0dfb574b9f934ce5cd379205af", "created_at": "2026-10-22T18:39:00.123Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-22T18:39:00.124Z',NULL,'link','entity_link','ent_fd88cee10c974d92a3bf59bdc9d7d4e8|ent_b61160bfef1b4237bf2b7937cbea51a0|contains',NULL,'{"from_entity_id": "ent_fd88cee10c974d92a3bf59bdc9d7d4e8", "to_entity_id": "ent_b61160bfef1b4237bf2b7937cbea51a0", "link_type": "contains", "created_at": "2026-10-22T18:39:00.124Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-22T18:39:00.125Z',NULL,'create','statement','stm_a491ab8133904cc9ac7e5b4683420cb0',NULL,'{"id": "stm_a491ab8133904cc9ac7e5b4683420cb0", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-22T18:39:00.125Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-22T18:39:00.127Z',NULL,'create','statement','stm_dcb447bcb2674e5a9d620af26fcd6ae9',NULL,'{"id": "stm_dcb447bcb2674e5a9d620af26fcd6ae9", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-22T18:39:00.127Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-22T18:39:00.128Z',NULL,'create','statement','stm_f10fa2dc8cf241e1bebb56b1e8aea632',NULL,'{"id": "stm_f10fa2dc8cf241e1bebb56b1e8aea632", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-22T18:39:00.128Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-22T18:39:00.129Z',NULL,'create','statement','stm_a0dbd7abe3994de6bd8eba8ee7872d8f',NULL,'{"id": "stm_a0dbd7abe3994de6bd8eba8ee7872d8f", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-22T18:39:00.129Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-22T18:39:00.130Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_a491ab8133904cc9ac7e5b4683420cb0", "to_id": "stm_dcb447bcb2674e5a9d620af26fcd6ae9", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_f10fa2dc8cf241e1bebb56b1e8aea632"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
