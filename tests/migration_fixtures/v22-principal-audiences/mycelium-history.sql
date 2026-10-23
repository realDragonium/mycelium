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
INSERT INTO "history_events" VALUES(1,'2026-10-23T16:23:36.872Z',NULL,'create','entity','ent_f3c4a02866a848f7b9e84cf06571add4',NULL,'{"id": "ent_f3c4a02866a848f7b9e84cf06571add4", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T16:23:36.871Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-23T16:23:36.872Z',NULL,'create','name','nam_67efb4f94ffa4c3d8458f61b08fa9992',NULL,'{"id": "nam_67efb4f94ffa4c3d8458f61b08fa9992", "text": "Login", "entity_id": "ent_f3c4a02866a848f7b9e84cf06571add4", "generated_from_name_id": null, "created_at": "2026-10-23T16:23:36.872Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-23T16:23:36.872Z',NULL,'update','entity','ent_f3c4a02866a848f7b9e84cf06571add4','{"id": "ent_f3c4a02866a848f7b9e84cf06571add4", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T16:23:36.871Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_f3c4a02866a848f7b9e84cf06571add4", "description": "Signing in.", "preferred_name_id": "nam_67efb4f94ffa4c3d8458f61b08fa9992", "created_at": "2026-10-23T16:23:36.871Z", "updated_at": "2026-10-23T16:23:36.872Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-23T16:23:36.876Z',NULL,'create','name','nam_fd7f3b6e561442b789b136979baaaa03',NULL,'{"id": "nam_fd7f3b6e561442b789b136979baaaa03", "text": "Logins", "entity_id": "ent_f3c4a02866a848f7b9e84cf06571add4", "generated_from_name_id": "nam_67efb4f94ffa4c3d8458f61b08fa9992", "created_at": "2026-10-23T16:23:36.876Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-23T16:23:36.876Z',NULL,'create','entity','ent_7af0aac50cd84eb5aa28b345d5fde933',NULL,'{"id": "ent_7af0aac50cd84eb5aa28b345d5fde933", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T16:23:36.876Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-23T16:23:36.876Z',NULL,'create','name','nam_f1caf73124b3447fb206ab0efb0232ee',NULL,'{"id": "nam_f1caf73124b3447fb206ab0efb0232ee", "text": "Session", "entity_id": "ent_7af0aac50cd84eb5aa28b345d5fde933", "generated_from_name_id": null, "created_at": "2026-10-23T16:23:36.876Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-23T16:23:36.876Z',NULL,'update','entity','ent_7af0aac50cd84eb5aa28b345d5fde933','{"id": "ent_7af0aac50cd84eb5aa28b345d5fde933", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T16:23:36.876Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_7af0aac50cd84eb5aa28b345d5fde933", "description": "An authenticated visit.", "preferred_name_id": "nam_f1caf73124b3447fb206ab0efb0232ee", "created_at": "2026-10-23T16:23:36.876Z", "updated_at": "2026-10-23T16:23:36.876Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-23T16:23:36.876Z',NULL,'create','name','nam_6d44f8be57764a41acb445aed30c2576',NULL,'{"id": "nam_6d44f8be57764a41acb445aed30c2576", "text": "Sessions", "entity_id": "ent_7af0aac50cd84eb5aa28b345d5fde933", "generated_from_name_id": "nam_f1caf73124b3447fb206ab0efb0232ee", "created_at": "2026-10-23T16:23:36.876Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-23T16:23:36.877Z',NULL,'create','name','nam_ab6cd6724b034870b843281a5fbd8403',NULL,'{"id": "nam_ab6cd6724b034870b843281a5fbd8403", "text": "Sign-in", "entity_id": "ent_f3c4a02866a848f7b9e84cf06571add4", "generated_from_name_id": null, "created_at": "2026-10-23T16:23:36.877Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-23T16:23:36.877Z',NULL,'create','name','nam_2951af0ae2424b1583abfd17a5a37d94',NULL,'{"id": "nam_2951af0ae2424b1583abfd17a5a37d94", "text": "Sign-ins", "entity_id": "ent_f3c4a02866a848f7b9e84cf06571add4", "generated_from_name_id": "nam_ab6cd6724b034870b843281a5fbd8403", "created_at": "2026-10-23T16:23:36.877Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-23T16:23:36.877Z',NULL,'link','entity_link','ent_f3c4a02866a848f7b9e84cf06571add4|ent_7af0aac50cd84eb5aa28b345d5fde933|contains',NULL,'{"from_entity_id": "ent_f3c4a02866a848f7b9e84cf06571add4", "to_entity_id": "ent_7af0aac50cd84eb5aa28b345d5fde933", "link_type": "contains", "created_at": "2026-10-23T16:23:36.877Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-23T16:23:36.878Z',NULL,'create','statement','stm_10b7043e1fc9404f983c40a4fc594cb7',NULL,'{"id": "stm_10b7043e1fc9404f983c40a4fc594cb7", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-23T16:23:36.878Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-23T16:23:36.878Z',NULL,'create','statement','stm_f307765e058d4ae8a29083a161714e9c',NULL,'{"id": "stm_f307765e058d4ae8a29083a161714e9c", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-23T16:23:36.878Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-23T16:23:36.879Z',NULL,'create','statement','stm_058c1f74cc054dd39b39dd22dd34b3c8',NULL,'{"id": "stm_058c1f74cc054dd39b39dd22dd34b3c8", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-23T16:23:36.879Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-23T16:23:36.879Z',NULL,'create','statement','stm_cfb05695b9134f078070a8fb34e1eb9c',NULL,'{"id": "stm_cfb05695b9134f078070a8fb34e1eb9c", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-23T16:23:36.879Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-23T16:23:36.879Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_10b7043e1fc9404f983c40a4fc594cb7", "to_id": "stm_f307765e058d4ae8a29083a161714e9c", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_058c1f74cc054dd39b39dd22dd34b3c8"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
