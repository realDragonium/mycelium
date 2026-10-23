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
INSERT INTO "history_events" VALUES(1,'2026-10-23T17:20:46.133Z',NULL,'create','entity','ent_19dac16dc7b3447480df081b453fca8c',NULL,'{"id": "ent_19dac16dc7b3447480df081b453fca8c", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T17:20:46.133Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-23T17:20:46.133Z',NULL,'create','name','nam_9e939c532cb24a9c8bf8dd0eef58e26a',NULL,'{"id": "nam_9e939c532cb24a9c8bf8dd0eef58e26a", "text": "Login", "entity_id": "ent_19dac16dc7b3447480df081b453fca8c", "generated_from_name_id": null, "created_at": "2026-10-23T17:20:46.133Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-23T17:20:46.133Z',NULL,'update','entity','ent_19dac16dc7b3447480df081b453fca8c','{"id": "ent_19dac16dc7b3447480df081b453fca8c", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T17:20:46.133Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_19dac16dc7b3447480df081b453fca8c", "description": "Signing in.", "preferred_name_id": "nam_9e939c532cb24a9c8bf8dd0eef58e26a", "created_at": "2026-10-23T17:20:46.133Z", "updated_at": "2026-10-23T17:20:46.133Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-23T17:20:46.137Z',NULL,'create','name','nam_538df2df5af34ca291079d882423c458',NULL,'{"id": "nam_538df2df5af34ca291079d882423c458", "text": "Logins", "entity_id": "ent_19dac16dc7b3447480df081b453fca8c", "generated_from_name_id": "nam_9e939c532cb24a9c8bf8dd0eef58e26a", "created_at": "2026-10-23T17:20:46.137Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-23T17:20:46.138Z',NULL,'create','entity','ent_80bac94a52264f26a8a706a57387687f',NULL,'{"id": "ent_80bac94a52264f26a8a706a57387687f", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T17:20:46.138Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-23T17:20:46.138Z',NULL,'create','name','nam_219299ca8d6b4613998bedab8ca04baf',NULL,'{"id": "nam_219299ca8d6b4613998bedab8ca04baf", "text": "Session", "entity_id": "ent_80bac94a52264f26a8a706a57387687f", "generated_from_name_id": null, "created_at": "2026-10-23T17:20:46.138Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-23T17:20:46.138Z',NULL,'update','entity','ent_80bac94a52264f26a8a706a57387687f','{"id": "ent_80bac94a52264f26a8a706a57387687f", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T17:20:46.138Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_80bac94a52264f26a8a706a57387687f", "description": "An authenticated visit.", "preferred_name_id": "nam_219299ca8d6b4613998bedab8ca04baf", "created_at": "2026-10-23T17:20:46.138Z", "updated_at": "2026-10-23T17:20:46.138Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-23T17:20:46.138Z',NULL,'create','name','nam_1285bc75cd594759b1f1858959876bf4',NULL,'{"id": "nam_1285bc75cd594759b1f1858959876bf4", "text": "Sessions", "entity_id": "ent_80bac94a52264f26a8a706a57387687f", "generated_from_name_id": "nam_219299ca8d6b4613998bedab8ca04baf", "created_at": "2026-10-23T17:20:46.138Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-23T17:20:46.139Z',NULL,'create','name','nam_a54f7f0325d84e5d90783d426a6b3cf4',NULL,'{"id": "nam_a54f7f0325d84e5d90783d426a6b3cf4", "text": "Sign-in", "entity_id": "ent_19dac16dc7b3447480df081b453fca8c", "generated_from_name_id": null, "created_at": "2026-10-23T17:20:46.139Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-23T17:20:46.139Z',NULL,'create','name','nam_e0aed8b5d0724c01a07041b034f7299e',NULL,'{"id": "nam_e0aed8b5d0724c01a07041b034f7299e", "text": "Sign-ins", "entity_id": "ent_19dac16dc7b3447480df081b453fca8c", "generated_from_name_id": "nam_a54f7f0325d84e5d90783d426a6b3cf4", "created_at": "2026-10-23T17:20:46.139Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-23T17:20:46.139Z',NULL,'link','entity_link','ent_19dac16dc7b3447480df081b453fca8c|ent_80bac94a52264f26a8a706a57387687f|contains',NULL,'{"from_entity_id": "ent_19dac16dc7b3447480df081b453fca8c", "to_entity_id": "ent_80bac94a52264f26a8a706a57387687f", "link_type": "contains", "created_at": "2026-10-23T17:20:46.139Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-23T17:20:46.140Z',NULL,'create','statement','stm_07bc1b1a4481438d9660426a0fad104d',NULL,'{"id": "stm_07bc1b1a4481438d9660426a0fad104d", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-23T17:20:46.140Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-23T17:20:46.140Z',NULL,'create','statement','stm_e4c02cf316af41e7a3f396c0cadc99fc',NULL,'{"id": "stm_e4c02cf316af41e7a3f396c0cadc99fc", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-23T17:20:46.140Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-23T17:20:46.140Z',NULL,'create','statement','stm_fd46b8804a63411494f1dc19f3677f1d',NULL,'{"id": "stm_fd46b8804a63411494f1dc19f3677f1d", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-23T17:20:46.140Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-23T17:20:46.141Z',NULL,'create','statement','stm_fe1b4eed36dd482bb8ca59acd3287880',NULL,'{"id": "stm_fe1b4eed36dd482bb8ca59acd3287880", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-23T17:20:46.141Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-23T17:20:46.141Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_07bc1b1a4481438d9660426a0fad104d", "to_id": "stm_e4c02cf316af41e7a3f396c0cadc99fc", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_fd46b8804a63411494f1dc19f3677f1d"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
