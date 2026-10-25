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
INSERT INTO "history_events" VALUES(1,'2026-10-24T20:13:52.490Z',NULL,'create','entity','ent_2115ceaf550f4e27bb47cbc6ebdc6292',NULL,'{"id": "ent_2115ceaf550f4e27bb47cbc6ebdc6292", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-24T20:13:52.490Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-24T20:13:52.490Z',NULL,'create','name','nam_3d8cd5921653415f891adb22d3ff8eed',NULL,'{"id": "nam_3d8cd5921653415f891adb22d3ff8eed", "text": "Login", "entity_id": "ent_2115ceaf550f4e27bb47cbc6ebdc6292", "generated_from_name_id": null, "created_at": "2026-10-24T20:13:52.490Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-24T20:13:52.490Z',NULL,'update','entity','ent_2115ceaf550f4e27bb47cbc6ebdc6292','{"id": "ent_2115ceaf550f4e27bb47cbc6ebdc6292", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-24T20:13:52.490Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_2115ceaf550f4e27bb47cbc6ebdc6292", "description": "Signing in.", "preferred_name_id": "nam_3d8cd5921653415f891adb22d3ff8eed", "created_at": "2026-10-24T20:13:52.490Z", "updated_at": "2026-10-24T20:13:52.490Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-24T20:13:52.490Z',NULL,'create','name','nam_28e11b36068f469b9e21ccc095d5858e',NULL,'{"id": "nam_28e11b36068f469b9e21ccc095d5858e", "text": "Logins", "entity_id": "ent_2115ceaf550f4e27bb47cbc6ebdc6292", "generated_from_name_id": "nam_3d8cd5921653415f891adb22d3ff8eed", "created_at": "2026-10-24T20:13:52.490Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-24T20:13:52.491Z',NULL,'create','entity','ent_b545ad4b26fd42c3b1faef7e31784438',NULL,'{"id": "ent_b545ad4b26fd42c3b1faef7e31784438", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-24T20:13:52.491Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-24T20:13:52.491Z',NULL,'create','name','nam_0f42a35072a449c2a8454e24424ae483',NULL,'{"id": "nam_0f42a35072a449c2a8454e24424ae483", "text": "Session", "entity_id": "ent_b545ad4b26fd42c3b1faef7e31784438", "generated_from_name_id": null, "created_at": "2026-10-24T20:13:52.491Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-24T20:13:52.491Z',NULL,'update','entity','ent_b545ad4b26fd42c3b1faef7e31784438','{"id": "ent_b545ad4b26fd42c3b1faef7e31784438", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-24T20:13:52.491Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_b545ad4b26fd42c3b1faef7e31784438", "description": "An authenticated visit.", "preferred_name_id": "nam_0f42a35072a449c2a8454e24424ae483", "created_at": "2026-10-24T20:13:52.491Z", "updated_at": "2026-10-24T20:13:52.491Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-24T20:13:52.491Z',NULL,'create','name','nam_741f554843cf4e1390df7777b3f25a63',NULL,'{"id": "nam_741f554843cf4e1390df7777b3f25a63", "text": "Sessions", "entity_id": "ent_b545ad4b26fd42c3b1faef7e31784438", "generated_from_name_id": "nam_0f42a35072a449c2a8454e24424ae483", "created_at": "2026-10-24T20:13:52.491Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-24T20:13:52.492Z',NULL,'create','name','nam_0d36cdc28dd14078b9fc076926f9902d',NULL,'{"id": "nam_0d36cdc28dd14078b9fc076926f9902d", "text": "Sign-in", "entity_id": "ent_2115ceaf550f4e27bb47cbc6ebdc6292", "generated_from_name_id": null, "created_at": "2026-10-24T20:13:52.492Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-24T20:13:52.492Z',NULL,'create','name','nam_1903d5c36922483995d3b8d07f2befbf',NULL,'{"id": "nam_1903d5c36922483995d3b8d07f2befbf", "text": "Sign-ins", "entity_id": "ent_2115ceaf550f4e27bb47cbc6ebdc6292", "generated_from_name_id": "nam_0d36cdc28dd14078b9fc076926f9902d", "created_at": "2026-10-24T20:13:52.492Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-24T20:13:52.492Z',NULL,'link','entity_link','ent_2115ceaf550f4e27bb47cbc6ebdc6292|ent_b545ad4b26fd42c3b1faef7e31784438|contains',NULL,'{"from_entity_id": "ent_2115ceaf550f4e27bb47cbc6ebdc6292", "to_entity_id": "ent_b545ad4b26fd42c3b1faef7e31784438", "link_type": "contains", "created_at": "2026-10-24T20:13:52.492Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-24T20:13:52.493Z',NULL,'create','statement','stm_59c5f06ae4164ce3b31fa1b0968d0dca',NULL,'{"id": "stm_59c5f06ae4164ce3b31fa1b0968d0dca", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-24T20:13:52.492Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-24T20:13:52.493Z',NULL,'create','statement','stm_a4d2b9c063ba4ac5bd2a812c2abad85d',NULL,'{"id": "stm_a4d2b9c063ba4ac5bd2a812c2abad85d", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-24T20:13:52.493Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-24T20:13:52.493Z',NULL,'create','statement','stm_1eaa7391e8b34053bd01f43d1cbb066b',NULL,'{"id": "stm_1eaa7391e8b34053bd01f43d1cbb066b", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-24T20:13:52.493Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-24T20:13:52.494Z',NULL,'create','statement','stm_9957d2a61dd443cdaef6e26ac72f7d42',NULL,'{"id": "stm_9957d2a61dd443cdaef6e26ac72f7d42", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-24T20:13:52.494Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-24T20:13:52.494Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_59c5f06ae4164ce3b31fa1b0968d0dca", "to_id": "stm_a4d2b9c063ba4ac5bd2a812c2abad85d", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_1eaa7391e8b34053bd01f43d1cbb066b"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
