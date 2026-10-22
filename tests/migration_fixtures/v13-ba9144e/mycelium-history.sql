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
INSERT INTO "history_events" VALUES(1,'2026-10-22T18:23:58.379Z',NULL,'create','entity','ent_09760a44a79241d0ada790e0abec8f33',NULL,'{"id": "ent_09760a44a79241d0ada790e0abec8f33", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-22T18:23:58.379Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-22T18:23:58.379Z',NULL,'create','name','nam_25be5ef68771459e9d38a7a1db628f5b',NULL,'{"id": "nam_25be5ef68771459e9d38a7a1db628f5b", "text": "Login", "entity_id": "ent_09760a44a79241d0ada790e0abec8f33", "generated_from_name_id": null, "created_at": "2026-10-22T18:23:58.379Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-22T18:23:58.379Z',NULL,'update','entity','ent_09760a44a79241d0ada790e0abec8f33','{"id": "ent_09760a44a79241d0ada790e0abec8f33", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-22T18:23:58.379Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_09760a44a79241d0ada790e0abec8f33", "description": "Signing in.", "preferred_name_id": "nam_25be5ef68771459e9d38a7a1db628f5b", "created_at": "2026-10-22T18:23:58.379Z", "updated_at": "2026-10-22T18:23:58.379Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-22T18:23:58.388Z',NULL,'create','name','nam_f7ad4e8dcf484b1c935a71a1b16e8750',NULL,'{"id": "nam_f7ad4e8dcf484b1c935a71a1b16e8750", "text": "Logins", "entity_id": "ent_09760a44a79241d0ada790e0abec8f33", "generated_from_name_id": "nam_25be5ef68771459e9d38a7a1db628f5b", "created_at": "2026-10-22T18:23:58.388Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-22T18:23:58.390Z',NULL,'create','entity','ent_67f0585a491d4610926a839b3da78872',NULL,'{"id": "ent_67f0585a491d4610926a839b3da78872", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-22T18:23:58.390Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-22T18:23:58.390Z',NULL,'create','name','nam_791eb3d05e5b4762b4cf011b13e87cf6',NULL,'{"id": "nam_791eb3d05e5b4762b4cf011b13e87cf6", "text": "Session", "entity_id": "ent_67f0585a491d4610926a839b3da78872", "generated_from_name_id": null, "created_at": "2026-10-22T18:23:58.390Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-22T18:23:58.390Z',NULL,'update','entity','ent_67f0585a491d4610926a839b3da78872','{"id": "ent_67f0585a491d4610926a839b3da78872", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-22T18:23:58.390Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_67f0585a491d4610926a839b3da78872", "description": "An authenticated visit.", "preferred_name_id": "nam_791eb3d05e5b4762b4cf011b13e87cf6", "created_at": "2026-10-22T18:23:58.390Z", "updated_at": "2026-10-22T18:23:58.390Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-22T18:23:58.390Z',NULL,'create','name','nam_18e5bcf7d14f4b6a8dfe446644920af1',NULL,'{"id": "nam_18e5bcf7d14f4b6a8dfe446644920af1", "text": "Sessions", "entity_id": "ent_67f0585a491d4610926a839b3da78872", "generated_from_name_id": "nam_791eb3d05e5b4762b4cf011b13e87cf6", "created_at": "2026-10-22T18:23:58.390Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-22T18:23:58.392Z',NULL,'create','name','nam_321fec7ece2648f9a18221b8d0c868b7',NULL,'{"id": "nam_321fec7ece2648f9a18221b8d0c868b7", "text": "Sign-in", "entity_id": "ent_09760a44a79241d0ada790e0abec8f33", "generated_from_name_id": null, "created_at": "2026-10-22T18:23:58.392Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-22T18:23:58.392Z',NULL,'create','name','nam_138c46266f0d4870bcdd289121d4feee',NULL,'{"id": "nam_138c46266f0d4870bcdd289121d4feee", "text": "Sign-ins", "entity_id": "ent_09760a44a79241d0ada790e0abec8f33", "generated_from_name_id": "nam_321fec7ece2648f9a18221b8d0c868b7", "created_at": "2026-10-22T18:23:58.392Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-22T18:23:58.393Z',NULL,'link','entity_link','ent_09760a44a79241d0ada790e0abec8f33|ent_67f0585a491d4610926a839b3da78872|contains',NULL,'{"from_entity_id": "ent_09760a44a79241d0ada790e0abec8f33", "to_entity_id": "ent_67f0585a491d4610926a839b3da78872", "link_type": "contains", "created_at": "2026-10-22T18:23:58.393Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-22T18:23:58.395Z',NULL,'create','statement','stm_ec8118f1521e48b399a33ca19db667f1',NULL,'{"id": "stm_ec8118f1521e48b399a33ca19db667f1", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-22T18:23:58.395Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-22T18:23:58.396Z',NULL,'create','statement','stm_a1f652fe78f1468cad84f60fdea81388',NULL,'{"id": "stm_a1f652fe78f1468cad84f60fdea81388", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-22T18:23:58.396Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-22T18:23:58.398Z',NULL,'create','statement','stm_21d453bf69b9491a8e62140aa110d0db',NULL,'{"id": "stm_21d453bf69b9491a8e62140aa110d0db", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-22T18:23:58.398Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-22T18:23:58.399Z',NULL,'create','statement','stm_628bee877d104ec6b9d445695a0c38ab',NULL,'{"id": "stm_628bee877d104ec6b9d445695a0c38ab", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-22T18:23:58.399Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-22T18:23:58.401Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_ec8118f1521e48b399a33ca19db667f1", "to_id": "stm_a1f652fe78f1468cad84f60fdea81388", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_21d453bf69b9491a8e62140aa110d0db"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
