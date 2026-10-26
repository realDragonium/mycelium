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
INSERT INTO "history_events" VALUES(1,'2026-10-26T10:00:18.605Z',NULL,'create','entity','ent_e963cd883f7e4d5fb0def859ede9eed8',NULL,'{"id": "ent_e963cd883f7e4d5fb0def859ede9eed8", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-26T10:00:18.605Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-26T10:00:18.605Z',NULL,'create','name','nam_595439f539f744f5a62366adb195202f',NULL,'{"id": "nam_595439f539f744f5a62366adb195202f", "text": "Login", "entity_id": "ent_e963cd883f7e4d5fb0def859ede9eed8", "generated_from_name_id": null, "created_at": "2026-10-26T10:00:18.605Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-26T10:00:18.605Z',NULL,'update','entity','ent_e963cd883f7e4d5fb0def859ede9eed8','{"id": "ent_e963cd883f7e4d5fb0def859ede9eed8", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-26T10:00:18.605Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_e963cd883f7e4d5fb0def859ede9eed8", "description": "Signing in.", "preferred_name_id": "nam_595439f539f744f5a62366adb195202f", "created_at": "2026-10-26T10:00:18.605Z", "updated_at": "2026-10-26T10:00:18.605Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-26T10:00:18.606Z',NULL,'create','name','nam_d6ae1199f697432ab05639acbf8db5ab',NULL,'{"id": "nam_d6ae1199f697432ab05639acbf8db5ab", "text": "Logins", "entity_id": "ent_e963cd883f7e4d5fb0def859ede9eed8", "generated_from_name_id": "nam_595439f539f744f5a62366adb195202f", "created_at": "2026-10-26T10:00:18.606Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-26T10:00:18.606Z',NULL,'create','entity','ent_d752c266b3244aa8b84cfe6e4ebedb58',NULL,'{"id": "ent_d752c266b3244aa8b84cfe6e4ebedb58", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-26T10:00:18.606Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-26T10:00:18.606Z',NULL,'create','name','nam_7be486b3e7d842b39dd6e8689a331adb',NULL,'{"id": "nam_7be486b3e7d842b39dd6e8689a331adb", "text": "Session", "entity_id": "ent_d752c266b3244aa8b84cfe6e4ebedb58", "generated_from_name_id": null, "created_at": "2026-10-26T10:00:18.606Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-26T10:00:18.606Z',NULL,'update','entity','ent_d752c266b3244aa8b84cfe6e4ebedb58','{"id": "ent_d752c266b3244aa8b84cfe6e4ebedb58", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-26T10:00:18.606Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_d752c266b3244aa8b84cfe6e4ebedb58", "description": "An authenticated visit.", "preferred_name_id": "nam_7be486b3e7d842b39dd6e8689a331adb", "created_at": "2026-10-26T10:00:18.606Z", "updated_at": "2026-10-26T10:00:18.606Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-26T10:00:18.607Z',NULL,'create','name','nam_27e838ab8e364ad181de9f41d89b5b89',NULL,'{"id": "nam_27e838ab8e364ad181de9f41d89b5b89", "text": "Sessions", "entity_id": "ent_d752c266b3244aa8b84cfe6e4ebedb58", "generated_from_name_id": "nam_7be486b3e7d842b39dd6e8689a331adb", "created_at": "2026-10-26T10:00:18.607Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-26T10:00:18.607Z',NULL,'create','name','nam_2569060a8d9a44679d57d0e657d2be8d',NULL,'{"id": "nam_2569060a8d9a44679d57d0e657d2be8d", "text": "Sign-in", "entity_id": "ent_e963cd883f7e4d5fb0def859ede9eed8", "generated_from_name_id": null, "created_at": "2026-10-26T10:00:18.607Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-26T10:00:18.607Z',NULL,'create','name','nam_2882ff6fc7af4086ad0600ad115253ff',NULL,'{"id": "nam_2882ff6fc7af4086ad0600ad115253ff", "text": "Sign-ins", "entity_id": "ent_e963cd883f7e4d5fb0def859ede9eed8", "generated_from_name_id": "nam_2569060a8d9a44679d57d0e657d2be8d", "created_at": "2026-10-26T10:00:18.607Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-26T10:00:18.608Z',NULL,'link','entity_link','ent_e963cd883f7e4d5fb0def859ede9eed8|ent_d752c266b3244aa8b84cfe6e4ebedb58|contains',NULL,'{"from_entity_id": "ent_e963cd883f7e4d5fb0def859ede9eed8", "to_entity_id": "ent_d752c266b3244aa8b84cfe6e4ebedb58", "link_type": "contains", "created_at": "2026-10-26T10:00:18.608Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-26T10:00:18.608Z',NULL,'create','statement','stm_6964b679737348f3ab224aba690a43b4',NULL,'{"id": "stm_6964b679737348f3ab224aba690a43b4", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-26T10:00:18.608Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-26T10:00:18.609Z',NULL,'create','statement','stm_5670843def2148d38515309f2e15e433',NULL,'{"id": "stm_5670843def2148d38515309f2e15e433", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-26T10:00:18.609Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-26T10:00:18.609Z',NULL,'create','statement','stm_2bf9de813684456884ca66540eeaec0c',NULL,'{"id": "stm_2bf9de813684456884ca66540eeaec0c", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-26T10:00:18.609Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-26T10:00:18.609Z',NULL,'create','statement','stm_64ff173c546445b6847c67eb72562cb5',NULL,'{"id": "stm_64ff173c546445b6847c67eb72562cb5", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-26T10:00:18.609Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-26T10:00:18.610Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_6964b679737348f3ab224aba690a43b4", "to_id": "stm_5670843def2148d38515309f2e15e433", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_2bf9de813684456884ca66540eeaec0c"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
