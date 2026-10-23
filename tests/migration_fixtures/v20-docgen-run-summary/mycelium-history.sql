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
INSERT INTO "history_events" VALUES(1,'2026-10-23T07:55:05.289Z',NULL,'create','entity','ent_e13d5f277d88406eaaf4816b5abf097c',NULL,'{"id": "ent_e13d5f277d88406eaaf4816b5abf097c", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T07:55:05.289Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-23T07:55:05.289Z',NULL,'create','name','nam_1f9ca2c2df3e47b2b870cd961f4a9a3e',NULL,'{"id": "nam_1f9ca2c2df3e47b2b870cd961f4a9a3e", "text": "Login", "entity_id": "ent_e13d5f277d88406eaaf4816b5abf097c", "generated_from_name_id": null, "created_at": "2026-10-23T07:55:05.289Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-23T07:55:05.290Z',NULL,'update','entity','ent_e13d5f277d88406eaaf4816b5abf097c','{"id": "ent_e13d5f277d88406eaaf4816b5abf097c", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T07:55:05.289Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_e13d5f277d88406eaaf4816b5abf097c", "description": "Signing in.", "preferred_name_id": "nam_1f9ca2c2df3e47b2b870cd961f4a9a3e", "created_at": "2026-10-23T07:55:05.289Z", "updated_at": "2026-10-23T07:55:05.289Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-23T07:55:05.293Z',NULL,'create','name','nam_12797a430efa40fe95b21697e9952928',NULL,'{"id": "nam_12797a430efa40fe95b21697e9952928", "text": "Logins", "entity_id": "ent_e13d5f277d88406eaaf4816b5abf097c", "generated_from_name_id": "nam_1f9ca2c2df3e47b2b870cd961f4a9a3e", "created_at": "2026-10-23T07:55:05.293Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-23T07:55:05.294Z',NULL,'create','entity','ent_924bd41331954442bc66594195ddfe9c',NULL,'{"id": "ent_924bd41331954442bc66594195ddfe9c", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T07:55:05.294Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-23T07:55:05.294Z',NULL,'create','name','nam_3824382e0c4a47ecbbd7a50ff87cc995',NULL,'{"id": "nam_3824382e0c4a47ecbbd7a50ff87cc995", "text": "Session", "entity_id": "ent_924bd41331954442bc66594195ddfe9c", "generated_from_name_id": null, "created_at": "2026-10-23T07:55:05.294Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-23T07:55:05.294Z',NULL,'update','entity','ent_924bd41331954442bc66594195ddfe9c','{"id": "ent_924bd41331954442bc66594195ddfe9c", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T07:55:05.294Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_924bd41331954442bc66594195ddfe9c", "description": "An authenticated visit.", "preferred_name_id": "nam_3824382e0c4a47ecbbd7a50ff87cc995", "created_at": "2026-10-23T07:55:05.294Z", "updated_at": "2026-10-23T07:55:05.294Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-23T07:55:05.294Z',NULL,'create','name','nam_1d838e9c1d194d1fb572eebb17c3fbcd',NULL,'{"id": "nam_1d838e9c1d194d1fb572eebb17c3fbcd", "text": "Sessions", "entity_id": "ent_924bd41331954442bc66594195ddfe9c", "generated_from_name_id": "nam_3824382e0c4a47ecbbd7a50ff87cc995", "created_at": "2026-10-23T07:55:05.294Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-23T07:55:05.294Z',NULL,'create','name','nam_bd313bf2506743b1b68e945eff9a0ef6',NULL,'{"id": "nam_bd313bf2506743b1b68e945eff9a0ef6", "text": "Sign-in", "entity_id": "ent_e13d5f277d88406eaaf4816b5abf097c", "generated_from_name_id": null, "created_at": "2026-10-23T07:55:05.294Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-23T07:55:05.295Z',NULL,'create','name','nam_a00c2add886948f58187aec67ca02cb8',NULL,'{"id": "nam_a00c2add886948f58187aec67ca02cb8", "text": "Sign-ins", "entity_id": "ent_e13d5f277d88406eaaf4816b5abf097c", "generated_from_name_id": "nam_bd313bf2506743b1b68e945eff9a0ef6", "created_at": "2026-10-23T07:55:05.295Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-23T07:55:05.295Z',NULL,'link','entity_link','ent_e13d5f277d88406eaaf4816b5abf097c|ent_924bd41331954442bc66594195ddfe9c|contains',NULL,'{"from_entity_id": "ent_e13d5f277d88406eaaf4816b5abf097c", "to_entity_id": "ent_924bd41331954442bc66594195ddfe9c", "link_type": "contains", "created_at": "2026-10-23T07:55:05.295Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-23T07:55:05.295Z',NULL,'create','statement','stm_0d0a6c1f399846ee93c80123e861b85b',NULL,'{"id": "stm_0d0a6c1f399846ee93c80123e861b85b", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-23T07:55:05.295Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-23T07:55:05.296Z',NULL,'create','statement','stm_9ab6712532e4403993840d538f438c33',NULL,'{"id": "stm_9ab6712532e4403993840d538f438c33", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-23T07:55:05.296Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-23T07:55:05.296Z',NULL,'create','statement','stm_6b787c164b1949b6879ee45be928c764',NULL,'{"id": "stm_6b787c164b1949b6879ee45be928c764", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-23T07:55:05.296Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-23T07:55:05.296Z',NULL,'create','statement','stm_c6989083d40747f186870e084054d7af',NULL,'{"id": "stm_c6989083d40747f186870e084054d7af", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-23T07:55:05.296Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-23T07:55:05.297Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_0d0a6c1f399846ee93c80123e861b85b", "to_id": "stm_9ab6712532e4403993840d538f438c33", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_6b787c164b1949b6879ee45be928c764"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
