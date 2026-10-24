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
INSERT INTO "history_events" VALUES(1,'2026-10-24T08:53:26.272Z',NULL,'create','entity','ent_e4945e3d8a8b4b589435ffb226b9dfaf',NULL,'{"id": "ent_e4945e3d8a8b4b589435ffb226b9dfaf", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-24T08:53:26.272Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-24T08:53:26.272Z',NULL,'create','name','nam_d9dc0e95d92c4313a9fbad55d80f4d40',NULL,'{"id": "nam_d9dc0e95d92c4313a9fbad55d80f4d40", "text": "Login", "entity_id": "ent_e4945e3d8a8b4b589435ffb226b9dfaf", "generated_from_name_id": null, "created_at": "2026-10-24T08:53:26.272Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-24T08:53:26.272Z',NULL,'update','entity','ent_e4945e3d8a8b4b589435ffb226b9dfaf','{"id": "ent_e4945e3d8a8b4b589435ffb226b9dfaf", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-24T08:53:26.272Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_e4945e3d8a8b4b589435ffb226b9dfaf", "description": "Signing in.", "preferred_name_id": "nam_d9dc0e95d92c4313a9fbad55d80f4d40", "created_at": "2026-10-24T08:53:26.272Z", "updated_at": "2026-10-24T08:53:26.272Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-24T08:53:26.272Z',NULL,'create','name','nam_616a7ba19e9d43e49750cfac7fcd086d',NULL,'{"id": "nam_616a7ba19e9d43e49750cfac7fcd086d", "text": "Logins", "entity_id": "ent_e4945e3d8a8b4b589435ffb226b9dfaf", "generated_from_name_id": "nam_d9dc0e95d92c4313a9fbad55d80f4d40", "created_at": "2026-10-24T08:53:26.272Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-24T08:53:26.273Z',NULL,'create','entity','ent_b1cb37dad8a24490b3c71633b1262344',NULL,'{"id": "ent_b1cb37dad8a24490b3c71633b1262344", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-24T08:53:26.273Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-24T08:53:26.273Z',NULL,'create','name','nam_89f016c13c7e4cba9caf2a6f9e84d313',NULL,'{"id": "nam_89f016c13c7e4cba9caf2a6f9e84d313", "text": "Session", "entity_id": "ent_b1cb37dad8a24490b3c71633b1262344", "generated_from_name_id": null, "created_at": "2026-10-24T08:53:26.273Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-24T08:53:26.273Z',NULL,'update','entity','ent_b1cb37dad8a24490b3c71633b1262344','{"id": "ent_b1cb37dad8a24490b3c71633b1262344", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-24T08:53:26.273Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_b1cb37dad8a24490b3c71633b1262344", "description": "An authenticated visit.", "preferred_name_id": "nam_89f016c13c7e4cba9caf2a6f9e84d313", "created_at": "2026-10-24T08:53:26.273Z", "updated_at": "2026-10-24T08:53:26.273Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-24T08:53:26.274Z',NULL,'create','name','nam_27d96986cb104fdd8be40558b454950b',NULL,'{"id": "nam_27d96986cb104fdd8be40558b454950b", "text": "Sessions", "entity_id": "ent_b1cb37dad8a24490b3c71633b1262344", "generated_from_name_id": "nam_89f016c13c7e4cba9caf2a6f9e84d313", "created_at": "2026-10-24T08:53:26.274Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-24T08:53:26.274Z',NULL,'create','name','nam_9ecd8df2d5714f839206ed8c1d47a858',NULL,'{"id": "nam_9ecd8df2d5714f839206ed8c1d47a858", "text": "Sign-in", "entity_id": "ent_e4945e3d8a8b4b589435ffb226b9dfaf", "generated_from_name_id": null, "created_at": "2026-10-24T08:53:26.274Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-24T08:53:26.274Z',NULL,'create','name','nam_df7cec44a11747a89f8303fed281e3f7',NULL,'{"id": "nam_df7cec44a11747a89f8303fed281e3f7", "text": "Sign-ins", "entity_id": "ent_e4945e3d8a8b4b589435ffb226b9dfaf", "generated_from_name_id": "nam_9ecd8df2d5714f839206ed8c1d47a858", "created_at": "2026-10-24T08:53:26.274Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-24T08:53:26.274Z',NULL,'link','entity_link','ent_e4945e3d8a8b4b589435ffb226b9dfaf|ent_b1cb37dad8a24490b3c71633b1262344|contains',NULL,'{"from_entity_id": "ent_e4945e3d8a8b4b589435ffb226b9dfaf", "to_entity_id": "ent_b1cb37dad8a24490b3c71633b1262344", "link_type": "contains", "created_at": "2026-10-24T08:53:26.274Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-24T08:53:26.275Z',NULL,'create','statement','stm_3c29978ba243419da56147621eb5ffe2',NULL,'{"id": "stm_3c29978ba243419da56147621eb5ffe2", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-24T08:53:26.275Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-24T08:53:26.275Z',NULL,'create','statement','stm_1eafdaaf1f544063ad4beba160dde372',NULL,'{"id": "stm_1eafdaaf1f544063ad4beba160dde372", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-24T08:53:26.275Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-24T08:53:26.276Z',NULL,'create','statement','stm_cbcd3bb665be459d995def2f3401113f',NULL,'{"id": "stm_cbcd3bb665be459d995def2f3401113f", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-24T08:53:26.276Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-24T08:53:26.276Z',NULL,'create','statement','stm_2af375822fc64f2ca52d3e4728b5ac78',NULL,'{"id": "stm_2af375822fc64f2ca52d3e4728b5ac78", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-24T08:53:26.276Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-24T08:53:26.277Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_3c29978ba243419da56147621eb5ffe2", "to_id": "stm_1eafdaaf1f544063ad4beba160dde372", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_cbcd3bb665be459d995def2f3401113f"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
