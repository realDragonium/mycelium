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
INSERT INTO "history_events" VALUES(1,'2026-10-23T16:53:02.432Z',NULL,'create','entity','ent_182ae33dc2484e84a0bac2f55d310bb8',NULL,'{"id": "ent_182ae33dc2484e84a0bac2f55d310bb8", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T16:53:02.432Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-23T16:53:02.432Z',NULL,'create','name','nam_bd28b95b0d7243d18550515a0db79b55',NULL,'{"id": "nam_bd28b95b0d7243d18550515a0db79b55", "text": "Login", "entity_id": "ent_182ae33dc2484e84a0bac2f55d310bb8", "generated_from_name_id": null, "created_at": "2026-10-23T16:53:02.432Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-23T16:53:02.432Z',NULL,'update','entity','ent_182ae33dc2484e84a0bac2f55d310bb8','{"id": "ent_182ae33dc2484e84a0bac2f55d310bb8", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T16:53:02.432Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_182ae33dc2484e84a0bac2f55d310bb8", "description": "Signing in.", "preferred_name_id": "nam_bd28b95b0d7243d18550515a0db79b55", "created_at": "2026-10-23T16:53:02.432Z", "updated_at": "2026-10-23T16:53:02.432Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-23T16:53:02.436Z',NULL,'create','name','nam_92326b2a07b541ccb87c66abcc5eb9dc',NULL,'{"id": "nam_92326b2a07b541ccb87c66abcc5eb9dc", "text": "Logins", "entity_id": "ent_182ae33dc2484e84a0bac2f55d310bb8", "generated_from_name_id": "nam_bd28b95b0d7243d18550515a0db79b55", "created_at": "2026-10-23T16:53:02.436Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-23T16:53:02.437Z',NULL,'create','entity','ent_27c103fe7b1340f69cde5441679dd1d9',NULL,'{"id": "ent_27c103fe7b1340f69cde5441679dd1d9", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T16:53:02.437Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-23T16:53:02.437Z',NULL,'create','name','nam_70205fbf63e14abc81ece8daec58f096',NULL,'{"id": "nam_70205fbf63e14abc81ece8daec58f096", "text": "Session", "entity_id": "ent_27c103fe7b1340f69cde5441679dd1d9", "generated_from_name_id": null, "created_at": "2026-10-23T16:53:02.437Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-23T16:53:02.437Z',NULL,'update','entity','ent_27c103fe7b1340f69cde5441679dd1d9','{"id": "ent_27c103fe7b1340f69cde5441679dd1d9", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T16:53:02.437Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_27c103fe7b1340f69cde5441679dd1d9", "description": "An authenticated visit.", "preferred_name_id": "nam_70205fbf63e14abc81ece8daec58f096", "created_at": "2026-10-23T16:53:02.437Z", "updated_at": "2026-10-23T16:53:02.437Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-23T16:53:02.437Z',NULL,'create','name','nam_b019a3d1e21b45cfb5ffca21dd4fe677',NULL,'{"id": "nam_b019a3d1e21b45cfb5ffca21dd4fe677", "text": "Sessions", "entity_id": "ent_27c103fe7b1340f69cde5441679dd1d9", "generated_from_name_id": "nam_70205fbf63e14abc81ece8daec58f096", "created_at": "2026-10-23T16:53:02.437Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-23T16:53:02.437Z',NULL,'create','name','nam_a3bb1224b50e4e208d177ec0bd63e6c6',NULL,'{"id": "nam_a3bb1224b50e4e208d177ec0bd63e6c6", "text": "Sign-in", "entity_id": "ent_182ae33dc2484e84a0bac2f55d310bb8", "generated_from_name_id": null, "created_at": "2026-10-23T16:53:02.437Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-23T16:53:02.437Z',NULL,'create','name','nam_1ea90b0e50dc4298907d6d8b17b9d354',NULL,'{"id": "nam_1ea90b0e50dc4298907d6d8b17b9d354", "text": "Sign-ins", "entity_id": "ent_182ae33dc2484e84a0bac2f55d310bb8", "generated_from_name_id": "nam_a3bb1224b50e4e208d177ec0bd63e6c6", "created_at": "2026-10-23T16:53:02.437Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-23T16:53:02.438Z',NULL,'link','entity_link','ent_182ae33dc2484e84a0bac2f55d310bb8|ent_27c103fe7b1340f69cde5441679dd1d9|contains',NULL,'{"from_entity_id": "ent_182ae33dc2484e84a0bac2f55d310bb8", "to_entity_id": "ent_27c103fe7b1340f69cde5441679dd1d9", "link_type": "contains", "created_at": "2026-10-23T16:53:02.438Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-23T16:53:02.438Z',NULL,'create','statement','stm_d26baa9aa1e84154aeed60b1076d4ab9',NULL,'{"id": "stm_d26baa9aa1e84154aeed60b1076d4ab9", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-23T16:53:02.438Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-23T16:53:02.439Z',NULL,'create','statement','stm_48a952d47fbc4056aac5da8fd2488db4',NULL,'{"id": "stm_48a952d47fbc4056aac5da8fd2488db4", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-23T16:53:02.439Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-23T16:53:02.439Z',NULL,'create','statement','stm_2573b7ad400749eeabb75f769f2ab209',NULL,'{"id": "stm_2573b7ad400749eeabb75f769f2ab209", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-23T16:53:02.439Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-23T16:53:02.439Z',NULL,'create','statement','stm_90454f34285a4f738d15620e6258f3f6',NULL,'{"id": "stm_90454f34285a4f738d15620e6258f3f6", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-23T16:53:02.439Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-23T16:53:02.440Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_d26baa9aa1e84154aeed60b1076d4ab9", "to_id": "stm_48a952d47fbc4056aac5da8fd2488db4", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_2573b7ad400749eeabb75f769f2ab209"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
