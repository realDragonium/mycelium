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
INSERT INTO "history_events" VALUES(1,'2026-10-24T19:28:11.490Z',NULL,'create','entity','ent_87e7383c9a2249ae925ee98089266c75',NULL,'{"id": "ent_87e7383c9a2249ae925ee98089266c75", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-24T19:28:11.490Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-24T19:28:11.490Z',NULL,'create','name','nam_8cf5f2a2eba4430fb4b4c36e1ff65e9f',NULL,'{"id": "nam_8cf5f2a2eba4430fb4b4c36e1ff65e9f", "text": "Login", "entity_id": "ent_87e7383c9a2249ae925ee98089266c75", "generated_from_name_id": null, "created_at": "2026-10-24T19:28:11.490Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-24T19:28:11.490Z',NULL,'update','entity','ent_87e7383c9a2249ae925ee98089266c75','{"id": "ent_87e7383c9a2249ae925ee98089266c75", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-24T19:28:11.490Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_87e7383c9a2249ae925ee98089266c75", "description": "Signing in.", "preferred_name_id": "nam_8cf5f2a2eba4430fb4b4c36e1ff65e9f", "created_at": "2026-10-24T19:28:11.490Z", "updated_at": "2026-10-24T19:28:11.490Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-24T19:28:11.491Z',NULL,'create','name','nam_2c23476ca75841b689dfa201eb89f255',NULL,'{"id": "nam_2c23476ca75841b689dfa201eb89f255", "text": "Logins", "entity_id": "ent_87e7383c9a2249ae925ee98089266c75", "generated_from_name_id": "nam_8cf5f2a2eba4430fb4b4c36e1ff65e9f", "created_at": "2026-10-24T19:28:11.491Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-24T19:28:11.491Z',NULL,'create','entity','ent_33c69643e28148bdaf7cd294a3c816fa',NULL,'{"id": "ent_33c69643e28148bdaf7cd294a3c816fa", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-24T19:28:11.491Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-24T19:28:11.491Z',NULL,'create','name','nam_121c813fadd049a88eb9bcb1a9076ac4',NULL,'{"id": "nam_121c813fadd049a88eb9bcb1a9076ac4", "text": "Session", "entity_id": "ent_33c69643e28148bdaf7cd294a3c816fa", "generated_from_name_id": null, "created_at": "2026-10-24T19:28:11.491Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-24T19:28:11.491Z',NULL,'update','entity','ent_33c69643e28148bdaf7cd294a3c816fa','{"id": "ent_33c69643e28148bdaf7cd294a3c816fa", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-24T19:28:11.491Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_33c69643e28148bdaf7cd294a3c816fa", "description": "An authenticated visit.", "preferred_name_id": "nam_121c813fadd049a88eb9bcb1a9076ac4", "created_at": "2026-10-24T19:28:11.491Z", "updated_at": "2026-10-24T19:28:11.491Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-24T19:28:11.491Z',NULL,'create','name','nam_18bd1b9302ef44728fd40367d6261da6',NULL,'{"id": "nam_18bd1b9302ef44728fd40367d6261da6", "text": "Sessions", "entity_id": "ent_33c69643e28148bdaf7cd294a3c816fa", "generated_from_name_id": "nam_121c813fadd049a88eb9bcb1a9076ac4", "created_at": "2026-10-24T19:28:11.491Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-24T19:28:11.492Z',NULL,'create','name','nam_0ff4f2a39fc542ccbb976a1e8bfe24da',NULL,'{"id": "nam_0ff4f2a39fc542ccbb976a1e8bfe24da", "text": "Sign-in", "entity_id": "ent_87e7383c9a2249ae925ee98089266c75", "generated_from_name_id": null, "created_at": "2026-10-24T19:28:11.492Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-24T19:28:11.492Z',NULL,'create','name','nam_4b077012f0c844faa1d2bdd53455c971',NULL,'{"id": "nam_4b077012f0c844faa1d2bdd53455c971", "text": "Sign-ins", "entity_id": "ent_87e7383c9a2249ae925ee98089266c75", "generated_from_name_id": "nam_0ff4f2a39fc542ccbb976a1e8bfe24da", "created_at": "2026-10-24T19:28:11.492Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-24T19:28:11.492Z',NULL,'link','entity_link','ent_87e7383c9a2249ae925ee98089266c75|ent_33c69643e28148bdaf7cd294a3c816fa|contains',NULL,'{"from_entity_id": "ent_87e7383c9a2249ae925ee98089266c75", "to_entity_id": "ent_33c69643e28148bdaf7cd294a3c816fa", "link_type": "contains", "created_at": "2026-10-24T19:28:11.492Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-24T19:28:11.493Z',NULL,'create','statement','stm_4ea77e158722465f943303a44988effc',NULL,'{"id": "stm_4ea77e158722465f943303a44988effc", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-24T19:28:11.493Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-24T19:28:11.493Z',NULL,'create','statement','stm_c37667f3f57e425b9e903e4d0425260f',NULL,'{"id": "stm_c37667f3f57e425b9e903e4d0425260f", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-24T19:28:11.493Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-24T19:28:11.494Z',NULL,'create','statement','stm_9b79cbd7ef2c4855b591be4ce7428cda',NULL,'{"id": "stm_9b79cbd7ef2c4855b591be4ce7428cda", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-24T19:28:11.494Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-24T19:28:11.494Z',NULL,'create','statement','stm_09b6516730e348249515e3bbda98e2a5',NULL,'{"id": "stm_09b6516730e348249515e3bbda98e2a5", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-24T19:28:11.494Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-24T19:28:11.495Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_4ea77e158722465f943303a44988effc", "to_id": "stm_c37667f3f57e425b9e903e4d0425260f", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_9b79cbd7ef2c4855b591be4ce7428cda"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
