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
INSERT INTO "history_events" VALUES(1,'2026-10-22T18:23:42.177Z',NULL,'create','entity','ent_91f32927b24341d5be57f7638c55c2ac',NULL,'{"id": "ent_91f32927b24341d5be57f7638c55c2ac", "description": "Signing in.", "created_at": "2026-10-22T18:23:42.177Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-22T18:23:42.178Z',NULL,'create','name','nam_9ad85809d3c3476b9af5804c280903e5',NULL,'{"id": "nam_9ad85809d3c3476b9af5804c280903e5", "text": "Login", "entity_id": "ent_91f32927b24341d5be57f7638c55c2ac", "generated_from_name_id": null, "created_at": "2026-10-22T18:23:42.178Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-22T18:23:42.190Z',NULL,'create','name','nam_c29205e5babb4850a7cb1d42524f1820',NULL,'{"id": "nam_c29205e5babb4850a7cb1d42524f1820", "text": "Logins", "entity_id": "ent_91f32927b24341d5be57f7638c55c2ac", "generated_from_name_id": "nam_9ad85809d3c3476b9af5804c280903e5", "created_at": "2026-10-22T18:23:42.190Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-22T18:23:42.192Z',NULL,'create','entity','ent_c177454377a74895898487a7c2a4d55f',NULL,'{"id": "ent_c177454377a74895898487a7c2a4d55f", "description": "An authenticated visit.", "created_at": "2026-10-22T18:23:42.192Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-22T18:23:42.192Z',NULL,'create','name','nam_986c43cdbd534a83b63a1ab8463970f1',NULL,'{"id": "nam_986c43cdbd534a83b63a1ab8463970f1", "text": "Session", "entity_id": "ent_c177454377a74895898487a7c2a4d55f", "generated_from_name_id": null, "created_at": "2026-10-22T18:23:42.192Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-22T18:23:42.192Z',NULL,'create','name','nam_cf340ae1448346aa95e930619144717c',NULL,'{"id": "nam_cf340ae1448346aa95e930619144717c", "text": "Sessions", "entity_id": "ent_c177454377a74895898487a7c2a4d55f", "generated_from_name_id": "nam_986c43cdbd534a83b63a1ab8463970f1", "created_at": "2026-10-22T18:23:42.192Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-22T18:23:42.194Z',NULL,'create','name','nam_7c690e602c4244f5ba9738e67db922a4',NULL,'{"id": "nam_7c690e602c4244f5ba9738e67db922a4", "text": "Sign-in", "entity_id": "ent_91f32927b24341d5be57f7638c55c2ac", "generated_from_name_id": null, "created_at": "2026-10-22T18:23:42.194Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-22T18:23:42.195Z',NULL,'create','name','nam_e5dfca0692c24aae92c8b3b354a6f5f2',NULL,'{"id": "nam_e5dfca0692c24aae92c8b3b354a6f5f2", "text": "Sign-ins", "entity_id": "ent_91f32927b24341d5be57f7638c55c2ac", "generated_from_name_id": "nam_7c690e602c4244f5ba9738e67db922a4", "created_at": "2026-10-22T18:23:42.195Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-22T18:23:42.196Z',NULL,'link','entity_link','ent_91f32927b24341d5be57f7638c55c2ac|ent_c177454377a74895898487a7c2a4d55f|contains',NULL,'{"from_entity_id": "ent_91f32927b24341d5be57f7638c55c2ac", "to_entity_id": "ent_c177454377a74895898487a7c2a4d55f", "link_type": "contains", "created_at": "2026-10-22T18:23:42.196Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-22T18:23:42.197Z',NULL,'create','statement','stm_679427dbf5224484be29715b95d43430',NULL,'{"id": "stm_679427dbf5224484be29715b95d43430", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-22T18:23:42.197Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-22T18:23:42.199Z',NULL,'create','statement','stm_8864bac2d69c41a2aca64a260f3164df',NULL,'{"id": "stm_8864bac2d69c41a2aca64a260f3164df", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-22T18:23:42.199Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-22T18:23:42.201Z',NULL,'create','statement','stm_065a0ed132bc4bd58d349f748dc38a1c',NULL,'{"id": "stm_065a0ed132bc4bd58d349f748dc38a1c", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-22T18:23:42.201Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-22T18:23:42.203Z',NULL,'create','statement','stm_2058d54014a64c7989a8e69d1c7ae228',NULL,'{"id": "stm_2058d54014a64c7989a8e69d1c7ae228", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-22T18:23:42.203Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-22T18:23:42.205Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_679427dbf5224484be29715b95d43430", "to_id": "stm_8864bac2d69c41a2aca64a260f3164df", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_065a0ed132bc4bd58d349f748dc38a1c"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',14);
COMMIT;
