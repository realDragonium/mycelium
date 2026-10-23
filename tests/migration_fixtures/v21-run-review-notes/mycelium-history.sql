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
INSERT INTO "history_events" VALUES(1,'2026-10-23T12:59:04.960Z',NULL,'create','entity','ent_577f1769c1a247dfae70fe5bb7ffb218',NULL,'{"id": "ent_577f1769c1a247dfae70fe5bb7ffb218", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T12:59:04.960Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-23T12:59:04.960Z',NULL,'create','name','nam_181b295b13bc4c238984e641a1e853e9',NULL,'{"id": "nam_181b295b13bc4c238984e641a1e853e9", "text": "Login", "entity_id": "ent_577f1769c1a247dfae70fe5bb7ffb218", "generated_from_name_id": null, "created_at": "2026-10-23T12:59:04.960Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-23T12:59:04.960Z',NULL,'update','entity','ent_577f1769c1a247dfae70fe5bb7ffb218','{"id": "ent_577f1769c1a247dfae70fe5bb7ffb218", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T12:59:04.960Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_577f1769c1a247dfae70fe5bb7ffb218", "description": "Signing in.", "preferred_name_id": "nam_181b295b13bc4c238984e641a1e853e9", "created_at": "2026-10-23T12:59:04.960Z", "updated_at": "2026-10-23T12:59:04.960Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-23T12:59:04.964Z',NULL,'create','name','nam_61173ad515314b9dbd1fe45b0f6d0a16',NULL,'{"id": "nam_61173ad515314b9dbd1fe45b0f6d0a16", "text": "Logins", "entity_id": "ent_577f1769c1a247dfae70fe5bb7ffb218", "generated_from_name_id": "nam_181b295b13bc4c238984e641a1e853e9", "created_at": "2026-10-23T12:59:04.964Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-23T12:59:04.964Z',NULL,'create','entity','ent_d091ab448b5b4a7ab919947b3894dd19',NULL,'{"id": "ent_d091ab448b5b4a7ab919947b3894dd19", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T12:59:04.964Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-23T12:59:04.964Z',NULL,'create','name','nam_fb8cdb4d88064e20afc6ea1d75beb847',NULL,'{"id": "nam_fb8cdb4d88064e20afc6ea1d75beb847", "text": "Session", "entity_id": "ent_d091ab448b5b4a7ab919947b3894dd19", "generated_from_name_id": null, "created_at": "2026-10-23T12:59:04.964Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-23T12:59:04.964Z',NULL,'update','entity','ent_d091ab448b5b4a7ab919947b3894dd19','{"id": "ent_d091ab448b5b4a7ab919947b3894dd19", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T12:59:04.964Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_d091ab448b5b4a7ab919947b3894dd19", "description": "An authenticated visit.", "preferred_name_id": "nam_fb8cdb4d88064e20afc6ea1d75beb847", "created_at": "2026-10-23T12:59:04.964Z", "updated_at": "2026-10-23T12:59:04.964Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-23T12:59:04.964Z',NULL,'create','name','nam_78f3d0729fea454d8d4b77ecac7f4a16',NULL,'{"id": "nam_78f3d0729fea454d8d4b77ecac7f4a16", "text": "Sessions", "entity_id": "ent_d091ab448b5b4a7ab919947b3894dd19", "generated_from_name_id": "nam_fb8cdb4d88064e20afc6ea1d75beb847", "created_at": "2026-10-23T12:59:04.964Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-23T12:59:04.965Z',NULL,'create','name','nam_8343b0e7c6824062a8fe39002dcbf6cb',NULL,'{"id": "nam_8343b0e7c6824062a8fe39002dcbf6cb", "text": "Sign-in", "entity_id": "ent_577f1769c1a247dfae70fe5bb7ffb218", "generated_from_name_id": null, "created_at": "2026-10-23T12:59:04.965Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-23T12:59:04.965Z',NULL,'create','name','nam_274625904f5b46e99fe95a39f04f14ff',NULL,'{"id": "nam_274625904f5b46e99fe95a39f04f14ff", "text": "Sign-ins", "entity_id": "ent_577f1769c1a247dfae70fe5bb7ffb218", "generated_from_name_id": "nam_8343b0e7c6824062a8fe39002dcbf6cb", "created_at": "2026-10-23T12:59:04.965Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-23T12:59:04.965Z',NULL,'link','entity_link','ent_577f1769c1a247dfae70fe5bb7ffb218|ent_d091ab448b5b4a7ab919947b3894dd19|contains',NULL,'{"from_entity_id": "ent_577f1769c1a247dfae70fe5bb7ffb218", "to_entity_id": "ent_d091ab448b5b4a7ab919947b3894dd19", "link_type": "contains", "created_at": "2026-10-23T12:59:04.965Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-23T12:59:04.965Z',NULL,'create','statement','stm_97144a1b070749d78126c1293cb7aae1',NULL,'{"id": "stm_97144a1b070749d78126c1293cb7aae1", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-23T12:59:04.965Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-23T12:59:04.966Z',NULL,'create','statement','stm_44ef0afe144d408f91d3b8127dfa998b',NULL,'{"id": "stm_44ef0afe144d408f91d3b8127dfa998b", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-23T12:59:04.966Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-23T12:59:04.966Z',NULL,'create','statement','stm_696b04da48df467bb5acb8e70b26b94e',NULL,'{"id": "stm_696b04da48df467bb5acb8e70b26b94e", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-23T12:59:04.966Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-23T12:59:04.967Z',NULL,'create','statement','stm_10c5555d940641099ca012115fe0e9be',NULL,'{"id": "stm_10c5555d940641099ca012115fe0e9be", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-23T12:59:04.967Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-23T12:59:04.967Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_97144a1b070749d78126c1293cb7aae1", "to_id": "stm_44ef0afe144d408f91d3b8127dfa998b", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_696b04da48df467bb5acb8e70b26b94e"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
