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
INSERT INTO "history_events" VALUES(1,'2026-10-22T18:31:51.150Z',NULL,'create','entity','ent_9b39d6b92d694ae7a10d8e684bd56152',NULL,'{"id": "ent_9b39d6b92d694ae7a10d8e684bd56152", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-22T18:31:51.150Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-22T18:31:51.151Z',NULL,'create','name','nam_d2d1bf93a219413c95a764d4d1ed7973',NULL,'{"id": "nam_d2d1bf93a219413c95a764d4d1ed7973", "text": "Login", "entity_id": "ent_9b39d6b92d694ae7a10d8e684bd56152", "generated_from_name_id": null, "created_at": "2026-10-22T18:31:51.151Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-22T18:31:51.151Z',NULL,'update','entity','ent_9b39d6b92d694ae7a10d8e684bd56152','{"id": "ent_9b39d6b92d694ae7a10d8e684bd56152", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-22T18:31:51.150Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_9b39d6b92d694ae7a10d8e684bd56152", "description": "Signing in.", "preferred_name_id": "nam_d2d1bf93a219413c95a764d4d1ed7973", "created_at": "2026-10-22T18:31:51.150Z", "updated_at": "2026-10-22T18:31:51.151Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-22T18:31:51.160Z',NULL,'create','name','nam_7f2ef3cbbc7c4de4b1b5977c5566f808',NULL,'{"id": "nam_7f2ef3cbbc7c4de4b1b5977c5566f808", "text": "Logins", "entity_id": "ent_9b39d6b92d694ae7a10d8e684bd56152", "generated_from_name_id": "nam_d2d1bf93a219413c95a764d4d1ed7973", "created_at": "2026-10-22T18:31:51.160Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-22T18:31:51.161Z',NULL,'create','entity','ent_e6d494e306154235b0f9204412ad5c5e',NULL,'{"id": "ent_e6d494e306154235b0f9204412ad5c5e", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-22T18:31:51.161Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-22T18:31:51.162Z',NULL,'create','name','nam_a2cefb1497994d0db02ced227834c78c',NULL,'{"id": "nam_a2cefb1497994d0db02ced227834c78c", "text": "Session", "entity_id": "ent_e6d494e306154235b0f9204412ad5c5e", "generated_from_name_id": null, "created_at": "2026-10-22T18:31:51.162Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-22T18:31:51.162Z',NULL,'update','entity','ent_e6d494e306154235b0f9204412ad5c5e','{"id": "ent_e6d494e306154235b0f9204412ad5c5e", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-22T18:31:51.161Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_e6d494e306154235b0f9204412ad5c5e", "description": "An authenticated visit.", "preferred_name_id": "nam_a2cefb1497994d0db02ced227834c78c", "created_at": "2026-10-22T18:31:51.161Z", "updated_at": "2026-10-22T18:31:51.162Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-22T18:31:51.162Z',NULL,'create','name','nam_ba3c7b9e0a964d9b81030915d4cb0654',NULL,'{"id": "nam_ba3c7b9e0a964d9b81030915d4cb0654", "text": "Sessions", "entity_id": "ent_e6d494e306154235b0f9204412ad5c5e", "generated_from_name_id": "nam_a2cefb1497994d0db02ced227834c78c", "created_at": "2026-10-22T18:31:51.162Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-22T18:31:51.163Z',NULL,'create','name','nam_d9651202eab64af2ae976a7361de744e',NULL,'{"id": "nam_d9651202eab64af2ae976a7361de744e", "text": "Sign-in", "entity_id": "ent_9b39d6b92d694ae7a10d8e684bd56152", "generated_from_name_id": null, "created_at": "2026-10-22T18:31:51.163Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-22T18:31:51.164Z',NULL,'create','name','nam_8924e2dfb4844d758885bbaaa7990d40',NULL,'{"id": "nam_8924e2dfb4844d758885bbaaa7990d40", "text": "Sign-ins", "entity_id": "ent_9b39d6b92d694ae7a10d8e684bd56152", "generated_from_name_id": "nam_d9651202eab64af2ae976a7361de744e", "created_at": "2026-10-22T18:31:51.163Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-22T18:31:51.165Z',NULL,'link','entity_link','ent_9b39d6b92d694ae7a10d8e684bd56152|ent_e6d494e306154235b0f9204412ad5c5e|contains',NULL,'{"from_entity_id": "ent_9b39d6b92d694ae7a10d8e684bd56152", "to_entity_id": "ent_e6d494e306154235b0f9204412ad5c5e", "link_type": "contains", "created_at": "2026-10-22T18:31:51.165Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-22T18:31:51.166Z',NULL,'create','statement','stm_d1230ee76edc401c899769738b7b02ee',NULL,'{"id": "stm_d1230ee76edc401c899769738b7b02ee", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-22T18:31:51.166Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-22T18:31:51.167Z',NULL,'create','statement','stm_ad7268ef8d0149c9b825d76cb51c6b3d',NULL,'{"id": "stm_ad7268ef8d0149c9b825d76cb51c6b3d", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-22T18:31:51.167Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-22T18:31:51.168Z',NULL,'create','statement','stm_3a10aa9b39fc4d7bb9c520a5868a8f8f',NULL,'{"id": "stm_3a10aa9b39fc4d7bb9c520a5868a8f8f", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-22T18:31:51.168Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-22T18:31:51.170Z',NULL,'create','statement','stm_9ae77f3f099146a38cb31f48aeddd78c',NULL,'{"id": "stm_9ae77f3f099146a38cb31f48aeddd78c", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-22T18:31:51.170Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-22T18:31:51.171Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_d1230ee76edc401c899769738b7b02ee", "to_id": "stm_ad7268ef8d0149c9b825d76cb51c6b3d", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_3a10aa9b39fc4d7bb9c520a5868a8f8f"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
