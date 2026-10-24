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
INSERT INTO "history_events" VALUES(1,'2026-10-24T20:01:51.862Z',NULL,'create','entity','ent_682b55f2594c41dba728125b8c09ac1e',NULL,'{"id": "ent_682b55f2594c41dba728125b8c09ac1e", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-24T20:01:51.861Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-24T20:01:51.862Z',NULL,'create','name','nam_ca0c0a1ccfb44c88b9798de7b64d0bd0',NULL,'{"id": "nam_ca0c0a1ccfb44c88b9798de7b64d0bd0", "text": "Login", "entity_id": "ent_682b55f2594c41dba728125b8c09ac1e", "generated_from_name_id": null, "created_at": "2026-10-24T20:01:51.862Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-24T20:01:51.862Z',NULL,'update','entity','ent_682b55f2594c41dba728125b8c09ac1e','{"id": "ent_682b55f2594c41dba728125b8c09ac1e", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-24T20:01:51.861Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_682b55f2594c41dba728125b8c09ac1e", "description": "Signing in.", "preferred_name_id": "nam_ca0c0a1ccfb44c88b9798de7b64d0bd0", "created_at": "2026-10-24T20:01:51.861Z", "updated_at": "2026-10-24T20:01:51.862Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-24T20:01:51.862Z',NULL,'create','name','nam_d6c8a1341b0d49fa9a2a1bd4714f0fd3',NULL,'{"id": "nam_d6c8a1341b0d49fa9a2a1bd4714f0fd3", "text": "Logins", "entity_id": "ent_682b55f2594c41dba728125b8c09ac1e", "generated_from_name_id": "nam_ca0c0a1ccfb44c88b9798de7b64d0bd0", "created_at": "2026-10-24T20:01:51.862Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-24T20:01:51.863Z',NULL,'create','entity','ent_3ef61a2e26c94c19bab7a30774df2ece',NULL,'{"id": "ent_3ef61a2e26c94c19bab7a30774df2ece", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-24T20:01:51.863Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-24T20:01:51.863Z',NULL,'create','name','nam_1215b7a3a63946888b3693fd637a23fe',NULL,'{"id": "nam_1215b7a3a63946888b3693fd637a23fe", "text": "Session", "entity_id": "ent_3ef61a2e26c94c19bab7a30774df2ece", "generated_from_name_id": null, "created_at": "2026-10-24T20:01:51.863Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-24T20:01:51.863Z',NULL,'update','entity','ent_3ef61a2e26c94c19bab7a30774df2ece','{"id": "ent_3ef61a2e26c94c19bab7a30774df2ece", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-24T20:01:51.863Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_3ef61a2e26c94c19bab7a30774df2ece", "description": "An authenticated visit.", "preferred_name_id": "nam_1215b7a3a63946888b3693fd637a23fe", "created_at": "2026-10-24T20:01:51.863Z", "updated_at": "2026-10-24T20:01:51.863Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-24T20:01:51.863Z',NULL,'create','name','nam_993fbd45fd34485398bd199dd58836fd',NULL,'{"id": "nam_993fbd45fd34485398bd199dd58836fd", "text": "Sessions", "entity_id": "ent_3ef61a2e26c94c19bab7a30774df2ece", "generated_from_name_id": "nam_1215b7a3a63946888b3693fd637a23fe", "created_at": "2026-10-24T20:01:51.863Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-24T20:01:51.864Z',NULL,'create','name','nam_1e3b31b393544353bf27985541f9c9d0',NULL,'{"id": "nam_1e3b31b393544353bf27985541f9c9d0", "text": "Sign-in", "entity_id": "ent_682b55f2594c41dba728125b8c09ac1e", "generated_from_name_id": null, "created_at": "2026-10-24T20:01:51.864Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-24T20:01:51.864Z',NULL,'create','name','nam_09f1bac99a5646849bba898f20ebace2',NULL,'{"id": "nam_09f1bac99a5646849bba898f20ebace2", "text": "Sign-ins", "entity_id": "ent_682b55f2594c41dba728125b8c09ac1e", "generated_from_name_id": "nam_1e3b31b393544353bf27985541f9c9d0", "created_at": "2026-10-24T20:01:51.864Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-24T20:01:51.864Z',NULL,'link','entity_link','ent_682b55f2594c41dba728125b8c09ac1e|ent_3ef61a2e26c94c19bab7a30774df2ece|contains',NULL,'{"from_entity_id": "ent_682b55f2594c41dba728125b8c09ac1e", "to_entity_id": "ent_3ef61a2e26c94c19bab7a30774df2ece", "link_type": "contains", "created_at": "2026-10-24T20:01:51.864Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-24T20:01:51.865Z',NULL,'create','statement','stm_537eb81d5b2940ff8e9d7618f527f9ef',NULL,'{"id": "stm_537eb81d5b2940ff8e9d7618f527f9ef", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-24T20:01:51.864Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-24T20:01:51.865Z',NULL,'create','statement','stm_3bbd2665a53e478e8a477473d5e338a3',NULL,'{"id": "stm_3bbd2665a53e478e8a477473d5e338a3", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-24T20:01:51.865Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-24T20:01:51.865Z',NULL,'create','statement','stm_f69b211794b14c86ac26e9ce13fb1165',NULL,'{"id": "stm_f69b211794b14c86ac26e9ce13fb1165", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-24T20:01:51.865Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-24T20:01:51.866Z',NULL,'create','statement','stm_6527100a801b43f68e79b66015e47124',NULL,'{"id": "stm_6527100a801b43f68e79b66015e47124", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-24T20:01:51.866Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-24T20:01:51.866Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_537eb81d5b2940ff8e9d7618f527f9ef", "to_id": "stm_3bbd2665a53e478e8a477473d5e338a3", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_f69b211794b14c86ac26e9ce13fb1165"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
