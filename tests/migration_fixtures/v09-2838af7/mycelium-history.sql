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
INSERT INTO "history_events" VALUES(1,'2026-10-22T18:23:46.347Z',NULL,'create','entity','ent_d2afa4c089fb4e6f9e96a6dfde9df665',NULL,'{"id": "ent_d2afa4c089fb4e6f9e96a6dfde9df665", "description": "Signing in.", "created_at": "2026-10-22T18:23:46.347Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-22T18:23:46.347Z',NULL,'create','name','nam_032b0f6ad7144de39f65f26fac5439b2',NULL,'{"id": "nam_032b0f6ad7144de39f65f26fac5439b2", "text": "Login", "entity_id": "ent_d2afa4c089fb4e6f9e96a6dfde9df665", "generated_from_name_id": null, "created_at": "2026-10-22T18:23:46.347Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-22T18:23:46.359Z',NULL,'create','name','nam_c424777a8583426aa4c02bb4d0dda4d5',NULL,'{"id": "nam_c424777a8583426aa4c02bb4d0dda4d5", "text": "Logins", "entity_id": "ent_d2afa4c089fb4e6f9e96a6dfde9df665", "generated_from_name_id": "nam_032b0f6ad7144de39f65f26fac5439b2", "created_at": "2026-10-22T18:23:46.359Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-22T18:23:46.360Z',NULL,'create','entity','ent_6b44444025b44f7393c84c8f0aad8382',NULL,'{"id": "ent_6b44444025b44f7393c84c8f0aad8382", "description": "An authenticated visit.", "created_at": "2026-10-22T18:23:46.360Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-22T18:23:46.360Z',NULL,'create','name','nam_acc26c951b9148e5957bbeb9f965b924',NULL,'{"id": "nam_acc26c951b9148e5957bbeb9f965b924", "text": "Session", "entity_id": "ent_6b44444025b44f7393c84c8f0aad8382", "generated_from_name_id": null, "created_at": "2026-10-22T18:23:46.360Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-22T18:23:46.361Z',NULL,'create','name','nam_a26b8a3ae65a4092849dcf3054ab22fa',NULL,'{"id": "nam_a26b8a3ae65a4092849dcf3054ab22fa", "text": "Sessions", "entity_id": "ent_6b44444025b44f7393c84c8f0aad8382", "generated_from_name_id": "nam_acc26c951b9148e5957bbeb9f965b924", "created_at": "2026-10-22T18:23:46.361Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-22T18:23:46.362Z',NULL,'create','name','nam_b3a655bac57645d19ca505530c851a87',NULL,'{"id": "nam_b3a655bac57645d19ca505530c851a87", "text": "Sign-in", "entity_id": "ent_d2afa4c089fb4e6f9e96a6dfde9df665", "generated_from_name_id": null, "created_at": "2026-10-22T18:23:46.362Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-22T18:23:46.363Z',NULL,'create','name','nam_ad6033f598454efdafc4f1232ab75a54',NULL,'{"id": "nam_ad6033f598454efdafc4f1232ab75a54", "text": "Sign-ins", "entity_id": "ent_d2afa4c089fb4e6f9e96a6dfde9df665", "generated_from_name_id": "nam_b3a655bac57645d19ca505530c851a87", "created_at": "2026-10-22T18:23:46.363Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-22T18:23:46.364Z',NULL,'link','entity_link','ent_d2afa4c089fb4e6f9e96a6dfde9df665|ent_6b44444025b44f7393c84c8f0aad8382|contains',NULL,'{"from_entity_id": "ent_d2afa4c089fb4e6f9e96a6dfde9df665", "to_entity_id": "ent_6b44444025b44f7393c84c8f0aad8382", "link_type": "contains", "created_at": "2026-10-22T18:23:46.364Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-22T18:23:46.365Z',NULL,'create','statement','stm_e9ec6d335f6443a8b752a4d20105bcb2',NULL,'{"id": "stm_e9ec6d335f6443a8b752a4d20105bcb2", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-22T18:23:46.365Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-22T18:23:46.367Z',NULL,'create','statement','stm_a0ac1d58405840a18ddf654a6b02f965',NULL,'{"id": "stm_a0ac1d58405840a18ddf654a6b02f965", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-22T18:23:46.367Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-22T18:23:46.368Z',NULL,'create','statement','stm_c9e291492336483b88d6a7695117729d',NULL,'{"id": "stm_c9e291492336483b88d6a7695117729d", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-22T18:23:46.368Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-22T18:23:46.369Z',NULL,'create','statement','stm_4b37210ee4d54a5989605582115083b7',NULL,'{"id": "stm_4b37210ee4d54a5989605582115083b7", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-22T18:23:46.369Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-22T18:23:46.371Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_e9ec6d335f6443a8b752a4d20105bcb2", "to_id": "stm_a0ac1d58405840a18ddf654a6b02f965", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_c9e291492336483b88d6a7695117729d"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',14);
COMMIT;
