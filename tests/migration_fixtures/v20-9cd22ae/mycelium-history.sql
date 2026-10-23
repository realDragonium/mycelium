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
INSERT INTO "history_events" VALUES(1,'2026-10-23T07:08:16.620Z',NULL,'create','entity','ent_b24e6f6a717644b080ae3d580b40422c',NULL,'{"id": "ent_b24e6f6a717644b080ae3d580b40422c", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T07:08:16.620Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-23T07:08:16.620Z',NULL,'create','name','nam_92d09fce25aa4a5cb74d2d407bd274ce',NULL,'{"id": "nam_92d09fce25aa4a5cb74d2d407bd274ce", "text": "Login", "entity_id": "ent_b24e6f6a717644b080ae3d580b40422c", "generated_from_name_id": null, "created_at": "2026-10-23T07:08:16.620Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-23T07:08:16.620Z',NULL,'update','entity','ent_b24e6f6a717644b080ae3d580b40422c','{"id": "ent_b24e6f6a717644b080ae3d580b40422c", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T07:08:16.620Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_b24e6f6a717644b080ae3d580b40422c", "description": "Signing in.", "preferred_name_id": "nam_92d09fce25aa4a5cb74d2d407bd274ce", "created_at": "2026-10-23T07:08:16.620Z", "updated_at": "2026-10-23T07:08:16.620Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-23T07:08:16.624Z',NULL,'create','name','nam_bc526936e223423b947f21bffee7eae8',NULL,'{"id": "nam_bc526936e223423b947f21bffee7eae8", "text": "Logins", "entity_id": "ent_b24e6f6a717644b080ae3d580b40422c", "generated_from_name_id": "nam_92d09fce25aa4a5cb74d2d407bd274ce", "created_at": "2026-10-23T07:08:16.624Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-23T07:08:16.624Z',NULL,'create','entity','ent_8088ff46210c450e9235e150ed674f9e',NULL,'{"id": "ent_8088ff46210c450e9235e150ed674f9e", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T07:08:16.624Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-23T07:08:16.624Z',NULL,'create','name','nam_bf2b76cbaf87411e9f6105aff5c50e1a',NULL,'{"id": "nam_bf2b76cbaf87411e9f6105aff5c50e1a", "text": "Session", "entity_id": "ent_8088ff46210c450e9235e150ed674f9e", "generated_from_name_id": null, "created_at": "2026-10-23T07:08:16.624Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-23T07:08:16.624Z',NULL,'update','entity','ent_8088ff46210c450e9235e150ed674f9e','{"id": "ent_8088ff46210c450e9235e150ed674f9e", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T07:08:16.624Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_8088ff46210c450e9235e150ed674f9e", "description": "An authenticated visit.", "preferred_name_id": "nam_bf2b76cbaf87411e9f6105aff5c50e1a", "created_at": "2026-10-23T07:08:16.624Z", "updated_at": "2026-10-23T07:08:16.624Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-23T07:08:16.624Z',NULL,'create','name','nam_661d1bac790042ab9735a5692f8ece1d',NULL,'{"id": "nam_661d1bac790042ab9735a5692f8ece1d", "text": "Sessions", "entity_id": "ent_8088ff46210c450e9235e150ed674f9e", "generated_from_name_id": "nam_bf2b76cbaf87411e9f6105aff5c50e1a", "created_at": "2026-10-23T07:08:16.624Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-23T07:08:16.625Z',NULL,'create','name','nam_3751eff29f8a4d29a368e9daac8fccc1',NULL,'{"id": "nam_3751eff29f8a4d29a368e9daac8fccc1", "text": "Sign-in", "entity_id": "ent_b24e6f6a717644b080ae3d580b40422c", "generated_from_name_id": null, "created_at": "2026-10-23T07:08:16.625Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-23T07:08:16.625Z',NULL,'create','name','nam_a544c3448d1a4639b609da6c44219342',NULL,'{"id": "nam_a544c3448d1a4639b609da6c44219342", "text": "Sign-ins", "entity_id": "ent_b24e6f6a717644b080ae3d580b40422c", "generated_from_name_id": "nam_3751eff29f8a4d29a368e9daac8fccc1", "created_at": "2026-10-23T07:08:16.625Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-23T07:08:16.625Z',NULL,'link','entity_link','ent_b24e6f6a717644b080ae3d580b40422c|ent_8088ff46210c450e9235e150ed674f9e|contains',NULL,'{"from_entity_id": "ent_b24e6f6a717644b080ae3d580b40422c", "to_entity_id": "ent_8088ff46210c450e9235e150ed674f9e", "link_type": "contains", "created_at": "2026-10-23T07:08:16.625Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-23T07:08:16.625Z',NULL,'create','statement','stm_63b0013419bb4ab0837279055b7f6194',NULL,'{"id": "stm_63b0013419bb4ab0837279055b7f6194", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-23T07:08:16.625Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-23T07:08:16.626Z',NULL,'create','statement','stm_ee388f90196545c5b2d881c2b2dbb554',NULL,'{"id": "stm_ee388f90196545c5b2d881c2b2dbb554", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-23T07:08:16.626Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-23T07:08:16.626Z',NULL,'create','statement','stm_2979b2f87734459ab833bf361d6a7fae',NULL,'{"id": "stm_2979b2f87734459ab833bf361d6a7fae", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-23T07:08:16.626Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-23T07:08:16.627Z',NULL,'create','statement','stm_093050334c794fe38df1b9f5a212d2b4',NULL,'{"id": "stm_093050334c794fe38df1b9f5a212d2b4", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-23T07:08:16.627Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-23T07:08:16.627Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_63b0013419bb4ab0837279055b7f6194", "to_id": "stm_ee388f90196545c5b2d881c2b2dbb554", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_2979b2f87734459ab833bf361d6a7fae"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
