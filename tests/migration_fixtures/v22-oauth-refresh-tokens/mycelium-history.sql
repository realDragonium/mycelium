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
INSERT INTO "history_events" VALUES(1,'2026-10-23T14:46:13.431Z',NULL,'create','entity','ent_8cd5e2022e724a3ba2962bfc9cc0f58e',NULL,'{"id": "ent_8cd5e2022e724a3ba2962bfc9cc0f58e", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T14:46:13.431Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-23T14:46:13.431Z',NULL,'create','name','nam_772f06861ef547f18d9af2da2dc364ff',NULL,'{"id": "nam_772f06861ef547f18d9af2da2dc364ff", "text": "Login", "entity_id": "ent_8cd5e2022e724a3ba2962bfc9cc0f58e", "generated_from_name_id": null, "created_at": "2026-10-23T14:46:13.431Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-23T14:46:13.431Z',NULL,'update','entity','ent_8cd5e2022e724a3ba2962bfc9cc0f58e','{"id": "ent_8cd5e2022e724a3ba2962bfc9cc0f58e", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T14:46:13.431Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_8cd5e2022e724a3ba2962bfc9cc0f58e", "description": "Signing in.", "preferred_name_id": "nam_772f06861ef547f18d9af2da2dc364ff", "created_at": "2026-10-23T14:46:13.431Z", "updated_at": "2026-10-23T14:46:13.431Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-23T14:46:13.435Z',NULL,'create','name','nam_2d60440f5950480ca4c44b8a944a338d',NULL,'{"id": "nam_2d60440f5950480ca4c44b8a944a338d", "text": "Logins", "entity_id": "ent_8cd5e2022e724a3ba2962bfc9cc0f58e", "generated_from_name_id": "nam_772f06861ef547f18d9af2da2dc364ff", "created_at": "2026-10-23T14:46:13.435Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-23T14:46:13.435Z',NULL,'create','entity','ent_56c84cdac3b6480fbb3b2087409d8ee7',NULL,'{"id": "ent_56c84cdac3b6480fbb3b2087409d8ee7", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T14:46:13.435Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-23T14:46:13.435Z',NULL,'create','name','nam_7db00c22fd5041fbbb00ef7a3cd6d42a',NULL,'{"id": "nam_7db00c22fd5041fbbb00ef7a3cd6d42a", "text": "Session", "entity_id": "ent_56c84cdac3b6480fbb3b2087409d8ee7", "generated_from_name_id": null, "created_at": "2026-10-23T14:46:13.435Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-23T14:46:13.435Z',NULL,'update','entity','ent_56c84cdac3b6480fbb3b2087409d8ee7','{"id": "ent_56c84cdac3b6480fbb3b2087409d8ee7", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T14:46:13.435Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_56c84cdac3b6480fbb3b2087409d8ee7", "description": "An authenticated visit.", "preferred_name_id": "nam_7db00c22fd5041fbbb00ef7a3cd6d42a", "created_at": "2026-10-23T14:46:13.435Z", "updated_at": "2026-10-23T14:46:13.435Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-23T14:46:13.435Z',NULL,'create','name','nam_c9af68fee7b745c88e8c72a4445fcdd1',NULL,'{"id": "nam_c9af68fee7b745c88e8c72a4445fcdd1", "text": "Sessions", "entity_id": "ent_56c84cdac3b6480fbb3b2087409d8ee7", "generated_from_name_id": "nam_7db00c22fd5041fbbb00ef7a3cd6d42a", "created_at": "2026-10-23T14:46:13.435Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-23T14:46:13.436Z',NULL,'create','name','nam_6ca552a2d05643c79b47af8ad9fdd73e',NULL,'{"id": "nam_6ca552a2d05643c79b47af8ad9fdd73e", "text": "Sign-in", "entity_id": "ent_8cd5e2022e724a3ba2962bfc9cc0f58e", "generated_from_name_id": null, "created_at": "2026-10-23T14:46:13.436Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-23T14:46:13.436Z',NULL,'create','name','nam_58b99e0516e145db8df7506998c85d7d',NULL,'{"id": "nam_58b99e0516e145db8df7506998c85d7d", "text": "Sign-ins", "entity_id": "ent_8cd5e2022e724a3ba2962bfc9cc0f58e", "generated_from_name_id": "nam_6ca552a2d05643c79b47af8ad9fdd73e", "created_at": "2026-10-23T14:46:13.436Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-23T14:46:13.436Z',NULL,'link','entity_link','ent_8cd5e2022e724a3ba2962bfc9cc0f58e|ent_56c84cdac3b6480fbb3b2087409d8ee7|contains',NULL,'{"from_entity_id": "ent_8cd5e2022e724a3ba2962bfc9cc0f58e", "to_entity_id": "ent_56c84cdac3b6480fbb3b2087409d8ee7", "link_type": "contains", "created_at": "2026-10-23T14:46:13.436Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-23T14:46:13.437Z',NULL,'create','statement','stm_7f6b4d0163da4166ada0510e80709ef7',NULL,'{"id": "stm_7f6b4d0163da4166ada0510e80709ef7", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-23T14:46:13.437Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-23T14:46:13.437Z',NULL,'create','statement','stm_ed7f01b400fe483fb7a1986dd351b170',NULL,'{"id": "stm_ed7f01b400fe483fb7a1986dd351b170", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-23T14:46:13.437Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-23T14:46:13.437Z',NULL,'create','statement','stm_de269f68d951498ea3361edd4afd7fe3',NULL,'{"id": "stm_de269f68d951498ea3361edd4afd7fe3", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-23T14:46:13.437Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-23T14:46:13.438Z',NULL,'create','statement','stm_09345e117e55400cbfb7d8a47eb60c33',NULL,'{"id": "stm_09345e117e55400cbfb7d8a47eb60c33", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-23T14:46:13.438Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-23T14:46:13.438Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_7f6b4d0163da4166ada0510e80709ef7", "to_id": "stm_ed7f01b400fe483fb7a1986dd351b170", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_de269f68d951498ea3361edd4afd7fe3"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
