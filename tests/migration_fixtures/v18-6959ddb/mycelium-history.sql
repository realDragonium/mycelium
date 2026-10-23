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
INSERT INTO "history_events" VALUES(1,'2026-10-23T05:37:06.121Z',NULL,'create','entity','ent_8025970c31084674b534d4aaf2a4e6c5',NULL,'{"id": "ent_8025970c31084674b534d4aaf2a4e6c5", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T05:37:06.121Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-23T05:37:06.122Z',NULL,'create','name','nam_3c34977f11e546c3b1d45c0f65e76574',NULL,'{"id": "nam_3c34977f11e546c3b1d45c0f65e76574", "text": "Login", "entity_id": "ent_8025970c31084674b534d4aaf2a4e6c5", "generated_from_name_id": null, "created_at": "2026-10-23T05:37:06.122Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-23T05:37:06.122Z',NULL,'update','entity','ent_8025970c31084674b534d4aaf2a4e6c5','{"id": "ent_8025970c31084674b534d4aaf2a4e6c5", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T05:37:06.121Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_8025970c31084674b534d4aaf2a4e6c5", "description": "Signing in.", "preferred_name_id": "nam_3c34977f11e546c3b1d45c0f65e76574", "created_at": "2026-10-23T05:37:06.121Z", "updated_at": "2026-10-23T05:37:06.122Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-23T05:37:06.125Z',NULL,'create','name','nam_5c32ed16c67e4679a405c55d2300d3b8',NULL,'{"id": "nam_5c32ed16c67e4679a405c55d2300d3b8", "text": "Logins", "entity_id": "ent_8025970c31084674b534d4aaf2a4e6c5", "generated_from_name_id": "nam_3c34977f11e546c3b1d45c0f65e76574", "created_at": "2026-10-23T05:37:06.125Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-23T05:37:06.125Z',NULL,'create','entity','ent_e933c6257d714d9890a682f7285a39c9',NULL,'{"id": "ent_e933c6257d714d9890a682f7285a39c9", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T05:37:06.125Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-23T05:37:06.126Z',NULL,'create','name','nam_b80d4f9fac5c4f7c804bf811bdf0b1b8',NULL,'{"id": "nam_b80d4f9fac5c4f7c804bf811bdf0b1b8", "text": "Session", "entity_id": "ent_e933c6257d714d9890a682f7285a39c9", "generated_from_name_id": null, "created_at": "2026-10-23T05:37:06.125Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-23T05:37:06.126Z',NULL,'update','entity','ent_e933c6257d714d9890a682f7285a39c9','{"id": "ent_e933c6257d714d9890a682f7285a39c9", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T05:37:06.125Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_e933c6257d714d9890a682f7285a39c9", "description": "An authenticated visit.", "preferred_name_id": "nam_b80d4f9fac5c4f7c804bf811bdf0b1b8", "created_at": "2026-10-23T05:37:06.125Z", "updated_at": "2026-10-23T05:37:06.126Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-23T05:37:06.126Z',NULL,'create','name','nam_9911c1674ff0460d91d632e750c3d1bf',NULL,'{"id": "nam_9911c1674ff0460d91d632e750c3d1bf", "text": "Sessions", "entity_id": "ent_e933c6257d714d9890a682f7285a39c9", "generated_from_name_id": "nam_b80d4f9fac5c4f7c804bf811bdf0b1b8", "created_at": "2026-10-23T05:37:06.126Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-23T05:37:06.126Z',NULL,'create','name','nam_96cb0d82ad97438b8d8f205403540417',NULL,'{"id": "nam_96cb0d82ad97438b8d8f205403540417", "text": "Sign-in", "entity_id": "ent_8025970c31084674b534d4aaf2a4e6c5", "generated_from_name_id": null, "created_at": "2026-10-23T05:37:06.126Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-23T05:37:06.126Z',NULL,'create','name','nam_c135cebb4d824b1fae9a8f004f55f294',NULL,'{"id": "nam_c135cebb4d824b1fae9a8f004f55f294", "text": "Sign-ins", "entity_id": "ent_8025970c31084674b534d4aaf2a4e6c5", "generated_from_name_id": "nam_96cb0d82ad97438b8d8f205403540417", "created_at": "2026-10-23T05:37:06.126Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-23T05:37:06.126Z',NULL,'link','entity_link','ent_8025970c31084674b534d4aaf2a4e6c5|ent_e933c6257d714d9890a682f7285a39c9|contains',NULL,'{"from_entity_id": "ent_8025970c31084674b534d4aaf2a4e6c5", "to_entity_id": "ent_e933c6257d714d9890a682f7285a39c9", "link_type": "contains", "created_at": "2026-10-23T05:37:06.126Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-23T05:37:06.127Z',NULL,'create','statement','stm_1e0c9ebd8cf244f482af135c03034ca4',NULL,'{"id": "stm_1e0c9ebd8cf244f482af135c03034ca4", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-23T05:37:06.127Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-23T05:37:06.127Z',NULL,'create','statement','stm_e81eab6062e94df48e643631d0ddb278',NULL,'{"id": "stm_e81eab6062e94df48e643631d0ddb278", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-23T05:37:06.127Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-23T05:37:06.128Z',NULL,'create','statement','stm_a4d8c98ebad04937af3e9b4c787041d5',NULL,'{"id": "stm_a4d8c98ebad04937af3e9b4c787041d5", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-23T05:37:06.128Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-23T05:37:06.128Z',NULL,'create','statement','stm_5e7a258a8cd2471d99545ad21ec943fb',NULL,'{"id": "stm_5e7a258a8cd2471d99545ad21ec943fb", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-23T05:37:06.128Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-23T05:37:06.129Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_1e0c9ebd8cf244f482af135c03034ca4", "to_id": "stm_e81eab6062e94df48e643631d0ddb278", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_a4d8c98ebad04937af3e9b4c787041d5"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
