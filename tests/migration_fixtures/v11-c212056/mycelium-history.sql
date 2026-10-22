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
INSERT INTO "history_events" VALUES(1,'2026-10-22T18:23:51.617Z',NULL,'create','entity','ent_df273c18e7064819acd61f6136a45e09',NULL,'{"id": "ent_df273c18e7064819acd61f6136a45e09", "description": "Signing in.", "created_at": "2026-10-22T18:23:51.617Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-22T18:23:51.617Z',NULL,'create','name','nam_89f1a0a6509d4f71b7745ebd07aeb477',NULL,'{"id": "nam_89f1a0a6509d4f71b7745ebd07aeb477", "text": "Login", "entity_id": "ent_df273c18e7064819acd61f6136a45e09", "generated_from_name_id": null, "created_at": "2026-10-22T18:23:51.617Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-22T18:23:51.626Z',NULL,'create','name','nam_f2b2de30d833422faa20e8c083cf0178',NULL,'{"id": "nam_f2b2de30d833422faa20e8c083cf0178", "text": "Logins", "entity_id": "ent_df273c18e7064819acd61f6136a45e09", "generated_from_name_id": "nam_89f1a0a6509d4f71b7745ebd07aeb477", "created_at": "2026-10-22T18:23:51.626Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-22T18:23:51.628Z',NULL,'create','entity','ent_4bc2fef394004de49b87043ef472d443',NULL,'{"id": "ent_4bc2fef394004de49b87043ef472d443", "description": "An authenticated visit.", "created_at": "2026-10-22T18:23:51.628Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-22T18:23:51.628Z',NULL,'create','name','nam_c316bfc1bda343919c56c077f284f112',NULL,'{"id": "nam_c316bfc1bda343919c56c077f284f112", "text": "Session", "entity_id": "ent_4bc2fef394004de49b87043ef472d443", "generated_from_name_id": null, "created_at": "2026-10-22T18:23:51.628Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-22T18:23:51.628Z',NULL,'create','name','nam_f3d83fe71b6d41128baf19ec17fcbc6c',NULL,'{"id": "nam_f3d83fe71b6d41128baf19ec17fcbc6c", "text": "Sessions", "entity_id": "ent_4bc2fef394004de49b87043ef472d443", "generated_from_name_id": "nam_c316bfc1bda343919c56c077f284f112", "created_at": "2026-10-22T18:23:51.628Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-22T18:23:51.629Z',NULL,'create','name','nam_663162e28a154dc1b6ac2535e9d112f2',NULL,'{"id": "nam_663162e28a154dc1b6ac2535e9d112f2", "text": "Sign-in", "entity_id": "ent_df273c18e7064819acd61f6136a45e09", "generated_from_name_id": null, "created_at": "2026-10-22T18:23:51.629Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-22T18:23:51.630Z',NULL,'create','name','nam_d5b6cd64da1c445fabae9fe7af3db2df',NULL,'{"id": "nam_d5b6cd64da1c445fabae9fe7af3db2df", "text": "Sign-ins", "entity_id": "ent_df273c18e7064819acd61f6136a45e09", "generated_from_name_id": "nam_663162e28a154dc1b6ac2535e9d112f2", "created_at": "2026-10-22T18:23:51.630Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-22T18:23:51.631Z',NULL,'link','entity_link','ent_df273c18e7064819acd61f6136a45e09|ent_4bc2fef394004de49b87043ef472d443|contains',NULL,'{"from_entity_id": "ent_df273c18e7064819acd61f6136a45e09", "to_entity_id": "ent_4bc2fef394004de49b87043ef472d443", "link_type": "contains", "created_at": "2026-10-22T18:23:51.631Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-22T18:23:51.632Z',NULL,'create','statement','stm_bc5e7ce5211d4d139729b4b895cfc712',NULL,'{"id": "stm_bc5e7ce5211d4d139729b4b895cfc712", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-22T18:23:51.632Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-22T18:23:51.634Z',NULL,'create','statement','stm_300a41dd586d4c2c9233a4c15135d3c2',NULL,'{"id": "stm_300a41dd586d4c2c9233a4c15135d3c2", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-22T18:23:51.634Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-22T18:23:51.635Z',NULL,'create','statement','stm_5fb8eb1b0c3140699955d237ea4dba09',NULL,'{"id": "stm_5fb8eb1b0c3140699955d237ea4dba09", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-22T18:23:51.635Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-22T18:23:51.637Z',NULL,'create','statement','stm_9c730f9286d448118e1a5a541340ef81',NULL,'{"id": "stm_9c730f9286d448118e1a5a541340ef81", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-22T18:23:51.637Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-22T18:23:51.639Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_bc5e7ce5211d4d139729b4b895cfc712", "to_id": "stm_300a41dd586d4c2c9233a4c15135d3c2", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_5fb8eb1b0c3140699955d237ea4dba09"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',14);
COMMIT;
