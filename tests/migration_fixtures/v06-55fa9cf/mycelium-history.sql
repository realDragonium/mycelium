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
INSERT INTO "history_events" VALUES(1,'2026-10-22T18:38:42.170Z',NULL,'create','entity','ent_de013687d92d492592c2a4e0aa3f5a4c',NULL,'{"id": "ent_de013687d92d492592c2a4e0aa3f5a4c", "description": "Signing in.", "created_at": "2026-10-22T18:38:42.170Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-22T18:38:42.170Z',NULL,'create','name','nam_655095bc07f24f14b574352f4edcc96f',NULL,'{"id": "nam_655095bc07f24f14b574352f4edcc96f", "text": "Login", "entity_id": "ent_de013687d92d492592c2a4e0aa3f5a4c", "generated_from_name_id": null, "created_at": "2026-10-22T18:38:42.170Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-22T18:38:42.179Z',NULL,'create','name','nam_2da4703e68534a21a43d6fb7d87db324',NULL,'{"id": "nam_2da4703e68534a21a43d6fb7d87db324", "text": "Logins", "entity_id": "ent_de013687d92d492592c2a4e0aa3f5a4c", "generated_from_name_id": "nam_655095bc07f24f14b574352f4edcc96f", "created_at": "2026-10-22T18:38:42.179Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-22T18:38:42.181Z',NULL,'create','entity','ent_e6683a04c6a54dec84e8966cd3a8db0a',NULL,'{"id": "ent_e6683a04c6a54dec84e8966cd3a8db0a", "description": "An authenticated visit.", "created_at": "2026-10-22T18:38:42.181Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-22T18:38:42.181Z',NULL,'create','name','nam_782e9b2350ef4f0aa73b0cb27f59c9d9',NULL,'{"id": "nam_782e9b2350ef4f0aa73b0cb27f59c9d9", "text": "Session", "entity_id": "ent_e6683a04c6a54dec84e8966cd3a8db0a", "generated_from_name_id": null, "created_at": "2026-10-22T18:38:42.181Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-22T18:38:42.181Z',NULL,'create','name','nam_d20a9b3fa25345acb5b6c2776cd62108',NULL,'{"id": "nam_d20a9b3fa25345acb5b6c2776cd62108", "text": "Sessions", "entity_id": "ent_e6683a04c6a54dec84e8966cd3a8db0a", "generated_from_name_id": "nam_782e9b2350ef4f0aa73b0cb27f59c9d9", "created_at": "2026-10-22T18:38:42.181Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-22T18:38:42.182Z',NULL,'create','name','nam_25423718608542868f51b9d9f985606d',NULL,'{"id": "nam_25423718608542868f51b9d9f985606d", "text": "Sign-in", "entity_id": "ent_de013687d92d492592c2a4e0aa3f5a4c", "generated_from_name_id": null, "created_at": "2026-10-22T18:38:42.182Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-22T18:38:42.182Z',NULL,'create','name','nam_d4cd8ea1d66647dba2407c5ffadc41c2',NULL,'{"id": "nam_d4cd8ea1d66647dba2407c5ffadc41c2", "text": "Sign-ins", "entity_id": "ent_de013687d92d492592c2a4e0aa3f5a4c", "generated_from_name_id": "nam_25423718608542868f51b9d9f985606d", "created_at": "2026-10-22T18:38:42.182Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-22T18:38:42.184Z',NULL,'link','entity_link','ent_de013687d92d492592c2a4e0aa3f5a4c|ent_e6683a04c6a54dec84e8966cd3a8db0a|contains',NULL,'{"from_entity_id": "ent_de013687d92d492592c2a4e0aa3f5a4c", "to_entity_id": "ent_e6683a04c6a54dec84e8966cd3a8db0a", "link_type": "contains", "created_at": "2026-10-22T18:38:42.183Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-22T18:38:42.184Z',NULL,'create','statement','stm_30ad9900628c41c5b2f06fcf67f10a1c',NULL,'{"id": "stm_30ad9900628c41c5b2f06fcf67f10a1c", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-22T18:38:42.184Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-22T18:38:42.186Z',NULL,'create','statement','stm_93a88ffe79e74395b1719c271c583d9b',NULL,'{"id": "stm_93a88ffe79e74395b1719c271c583d9b", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-22T18:38:42.186Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-22T18:38:42.187Z',NULL,'create','statement','stm_88062ada90514a8a9ec4ee287108516a',NULL,'{"id": "stm_88062ada90514a8a9ec4ee287108516a", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-22T18:38:42.187Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-22T18:38:42.188Z',NULL,'create','statement','stm_c176d23dc4bd4321b14129cecbbbc1a0',NULL,'{"id": "stm_c176d23dc4bd4321b14129cecbbbc1a0", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-22T18:38:42.188Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-22T18:38:42.190Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_30ad9900628c41c5b2f06fcf67f10a1c", "to_id": "stm_93a88ffe79e74395b1719c271c583d9b", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_88062ada90514a8a9ec4ee287108516a"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',14);
COMMIT;
