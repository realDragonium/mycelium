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
INSERT INTO "history_events" VALUES(1,'2026-10-22T18:23:44.269Z',NULL,'create','entity','ent_84cb2dc4786249ef85d2163ba8a317ed',NULL,'{"id": "ent_84cb2dc4786249ef85d2163ba8a317ed", "description": "Signing in.", "created_at": "2026-10-22T18:23:44.269Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-22T18:23:44.270Z',NULL,'create','name','nam_1ca111282d704fa380ba20072612a80c',NULL,'{"id": "nam_1ca111282d704fa380ba20072612a80c", "text": "Login", "entity_id": "ent_84cb2dc4786249ef85d2163ba8a317ed", "generated_from_name_id": null, "created_at": "2026-10-22T18:23:44.270Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-22T18:23:44.280Z',NULL,'create','name','nam_136cf51ffc524b08bb860deab44c2d9f',NULL,'{"id": "nam_136cf51ffc524b08bb860deab44c2d9f", "text": "Logins", "entity_id": "ent_84cb2dc4786249ef85d2163ba8a317ed", "generated_from_name_id": "nam_1ca111282d704fa380ba20072612a80c", "created_at": "2026-10-22T18:23:44.280Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-22T18:23:44.281Z',NULL,'create','entity','ent_475d1cc191ce493a946f67c1b7862d57',NULL,'{"id": "ent_475d1cc191ce493a946f67c1b7862d57", "description": "An authenticated visit.", "created_at": "2026-10-22T18:23:44.281Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-22T18:23:44.281Z',NULL,'create','name','nam_4439b88f43b04ab8ace0f49c055e1d00',NULL,'{"id": "nam_4439b88f43b04ab8ace0f49c055e1d00", "text": "Session", "entity_id": "ent_475d1cc191ce493a946f67c1b7862d57", "generated_from_name_id": null, "created_at": "2026-10-22T18:23:44.281Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-22T18:23:44.282Z',NULL,'create','name','nam_42ada6ef3fe8431fb50dbfd1ee96b362',NULL,'{"id": "nam_42ada6ef3fe8431fb50dbfd1ee96b362", "text": "Sessions", "entity_id": "ent_475d1cc191ce493a946f67c1b7862d57", "generated_from_name_id": "nam_4439b88f43b04ab8ace0f49c055e1d00", "created_at": "2026-10-22T18:23:44.282Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-22T18:23:44.283Z',NULL,'create','name','nam_3ca262c9b2b24b739c4d2d1335ceaa45',NULL,'{"id": "nam_3ca262c9b2b24b739c4d2d1335ceaa45", "text": "Sign-in", "entity_id": "ent_84cb2dc4786249ef85d2163ba8a317ed", "generated_from_name_id": null, "created_at": "2026-10-22T18:23:44.283Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-22T18:23:44.283Z',NULL,'create','name','nam_ba71a65e57d04b47a144f1efbddf99ac',NULL,'{"id": "nam_ba71a65e57d04b47a144f1efbddf99ac", "text": "Sign-ins", "entity_id": "ent_84cb2dc4786249ef85d2163ba8a317ed", "generated_from_name_id": "nam_3ca262c9b2b24b739c4d2d1335ceaa45", "created_at": "2026-10-22T18:23:44.283Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-22T18:23:44.284Z',NULL,'link','entity_link','ent_84cb2dc4786249ef85d2163ba8a317ed|ent_475d1cc191ce493a946f67c1b7862d57|contains',NULL,'{"from_entity_id": "ent_84cb2dc4786249ef85d2163ba8a317ed", "to_entity_id": "ent_475d1cc191ce493a946f67c1b7862d57", "link_type": "contains", "created_at": "2026-10-22T18:23:44.284Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-22T18:23:44.285Z',NULL,'create','statement','stm_b9bfb649366c4746902812f9a38c6308',NULL,'{"id": "stm_b9bfb649366c4746902812f9a38c6308", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-22T18:23:44.285Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-22T18:23:44.286Z',NULL,'create','statement','stm_50b6aadb163449019e70e293d367fc0d',NULL,'{"id": "stm_50b6aadb163449019e70e293d367fc0d", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-22T18:23:44.286Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-22T18:23:44.288Z',NULL,'create','statement','stm_8ec50024f2454bdf8bab85af6c7e242e',NULL,'{"id": "stm_8ec50024f2454bdf8bab85af6c7e242e", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-22T18:23:44.288Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-22T18:23:44.289Z',NULL,'create','statement','stm_571ed6daec34478181ed7705eb7c6089',NULL,'{"id": "stm_571ed6daec34478181ed7705eb7c6089", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-22T18:23:44.289Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-22T18:23:44.290Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_b9bfb649366c4746902812f9a38c6308", "to_id": "stm_50b6aadb163449019e70e293d367fc0d", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_8ec50024f2454bdf8bab85af6c7e242e"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',14);
COMMIT;
