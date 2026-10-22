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
INSERT INTO "history_events" VALUES(1,'2026-10-22T18:38:46.180Z',NULL,'create','entity','ent_fa9cf37428c1498e854df5c136c36583',NULL,'{"id": "ent_fa9cf37428c1498e854df5c136c36583", "description": "Signing in.", "created_at": "2026-10-22T18:38:46.180Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-22T18:38:46.180Z',NULL,'create','name','nam_99b11d439ac74a5b936d2720f577a43f',NULL,'{"id": "nam_99b11d439ac74a5b936d2720f577a43f", "text": "Login", "entity_id": "ent_fa9cf37428c1498e854df5c136c36583", "generated_from_name_id": null, "created_at": "2026-10-22T18:38:46.180Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-22T18:38:46.190Z',NULL,'create','name','nam_f0a2ccabde554addb86636063d2ce121',NULL,'{"id": "nam_f0a2ccabde554addb86636063d2ce121", "text": "Logins", "entity_id": "ent_fa9cf37428c1498e854df5c136c36583", "generated_from_name_id": "nam_99b11d439ac74a5b936d2720f577a43f", "created_at": "2026-10-22T18:38:46.190Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-22T18:38:46.191Z',NULL,'create','entity','ent_4e4f50eae5054a639da0d0496eb1dcf8',NULL,'{"id": "ent_4e4f50eae5054a639da0d0496eb1dcf8", "description": "An authenticated visit.", "created_at": "2026-10-22T18:38:46.191Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-22T18:38:46.192Z',NULL,'create','name','nam_a8a4a68f54e5499c85105ab0f2cd9ade',NULL,'{"id": "nam_a8a4a68f54e5499c85105ab0f2cd9ade", "text": "Session", "entity_id": "ent_4e4f50eae5054a639da0d0496eb1dcf8", "generated_from_name_id": null, "created_at": "2026-10-22T18:38:46.192Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-22T18:38:46.192Z',NULL,'create','name','nam_84eb05f48fdc44df9f68f2d85dadaaec',NULL,'{"id": "nam_84eb05f48fdc44df9f68f2d85dadaaec", "text": "Sessions", "entity_id": "ent_4e4f50eae5054a639da0d0496eb1dcf8", "generated_from_name_id": "nam_a8a4a68f54e5499c85105ab0f2cd9ade", "created_at": "2026-10-22T18:38:46.192Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-22T18:38:46.193Z',NULL,'create','name','nam_9cedeb38bef541e6a93b30658bb48c4a',NULL,'{"id": "nam_9cedeb38bef541e6a93b30658bb48c4a", "text": "Sign-in", "entity_id": "ent_fa9cf37428c1498e854df5c136c36583", "generated_from_name_id": null, "created_at": "2026-10-22T18:38:46.193Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-22T18:38:46.194Z',NULL,'create','name','nam_8169943f157f4625bf208177c7c9782b',NULL,'{"id": "nam_8169943f157f4625bf208177c7c9782b", "text": "Sign-ins", "entity_id": "ent_fa9cf37428c1498e854df5c136c36583", "generated_from_name_id": "nam_9cedeb38bef541e6a93b30658bb48c4a", "created_at": "2026-10-22T18:38:46.194Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-22T18:38:46.195Z',NULL,'link','entity_link','ent_fa9cf37428c1498e854df5c136c36583|ent_4e4f50eae5054a639da0d0496eb1dcf8|contains',NULL,'{"from_entity_id": "ent_fa9cf37428c1498e854df5c136c36583", "to_entity_id": "ent_4e4f50eae5054a639da0d0496eb1dcf8", "link_type": "contains", "created_at": "2026-10-22T18:38:46.195Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-22T18:38:46.196Z',NULL,'create','statement','stm_9709802eb6fe4ac989544d00c6d6f4de',NULL,'{"id": "stm_9709802eb6fe4ac989544d00c6d6f4de", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-22T18:38:46.196Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-22T18:38:46.198Z',NULL,'create','statement','stm_ba77d0a0c7be4c4283e3fabe11422de3',NULL,'{"id": "stm_ba77d0a0c7be4c4283e3fabe11422de3", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-22T18:38:46.198Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-22T18:38:46.199Z',NULL,'create','statement','stm_3b5d45c8e509439997f8a728ff6a8f89',NULL,'{"id": "stm_3b5d45c8e509439997f8a728ff6a8f89", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-22T18:38:46.199Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-22T18:38:46.200Z',NULL,'create','statement','stm_717d3d39426a4b80a5c329db398ce6fc',NULL,'{"id": "stm_717d3d39426a4b80a5c329db398ce6fc", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-22T18:38:46.200Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-22T18:38:46.202Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_9709802eb6fe4ac989544d00c6d6f4de", "to_id": "stm_ba77d0a0c7be4c4283e3fabe11422de3", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_3b5d45c8e509439997f8a728ff6a8f89"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',14);
COMMIT;
