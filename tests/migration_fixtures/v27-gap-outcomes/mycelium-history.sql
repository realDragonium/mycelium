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
INSERT INTO "history_events" VALUES(1,'2026-10-24T17:39:17.490Z',NULL,'create','entity','ent_5beb3681151847da9bca7284a5c9b122',NULL,'{"id": "ent_5beb3681151847da9bca7284a5c9b122", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-24T17:39:17.490Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-24T17:39:17.490Z',NULL,'create','name','nam_49b25a3a57564460afb9232190265c49',NULL,'{"id": "nam_49b25a3a57564460afb9232190265c49", "text": "Login", "entity_id": "ent_5beb3681151847da9bca7284a5c9b122", "generated_from_name_id": null, "created_at": "2026-10-24T17:39:17.490Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-24T17:39:17.490Z',NULL,'update','entity','ent_5beb3681151847da9bca7284a5c9b122','{"id": "ent_5beb3681151847da9bca7284a5c9b122", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-24T17:39:17.490Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_5beb3681151847da9bca7284a5c9b122", "description": "Signing in.", "preferred_name_id": "nam_49b25a3a57564460afb9232190265c49", "created_at": "2026-10-24T17:39:17.490Z", "updated_at": "2026-10-24T17:39:17.490Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-24T17:39:17.490Z',NULL,'create','name','nam_dfa4cacc43b0488994b1524500950886',NULL,'{"id": "nam_dfa4cacc43b0488994b1524500950886", "text": "Logins", "entity_id": "ent_5beb3681151847da9bca7284a5c9b122", "generated_from_name_id": "nam_49b25a3a57564460afb9232190265c49", "created_at": "2026-10-24T17:39:17.490Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-24T17:39:17.491Z',NULL,'create','entity','ent_dbd07f40438c4287a1e854a6291b794d',NULL,'{"id": "ent_dbd07f40438c4287a1e854a6291b794d", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-24T17:39:17.491Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-24T17:39:17.491Z',NULL,'create','name','nam_9ca77ac8e2c24e3f9dbf0779bdb492f3',NULL,'{"id": "nam_9ca77ac8e2c24e3f9dbf0779bdb492f3", "text": "Session", "entity_id": "ent_dbd07f40438c4287a1e854a6291b794d", "generated_from_name_id": null, "created_at": "2026-10-24T17:39:17.491Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-24T17:39:17.491Z',NULL,'update','entity','ent_dbd07f40438c4287a1e854a6291b794d','{"id": "ent_dbd07f40438c4287a1e854a6291b794d", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-24T17:39:17.491Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_dbd07f40438c4287a1e854a6291b794d", "description": "An authenticated visit.", "preferred_name_id": "nam_9ca77ac8e2c24e3f9dbf0779bdb492f3", "created_at": "2026-10-24T17:39:17.491Z", "updated_at": "2026-10-24T17:39:17.491Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-24T17:39:17.491Z',NULL,'create','name','nam_132a73ceecc64740ad6bffbdaeb12eb5',NULL,'{"id": "nam_132a73ceecc64740ad6bffbdaeb12eb5", "text": "Sessions", "entity_id": "ent_dbd07f40438c4287a1e854a6291b794d", "generated_from_name_id": "nam_9ca77ac8e2c24e3f9dbf0779bdb492f3", "created_at": "2026-10-24T17:39:17.491Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-24T17:39:17.491Z',NULL,'create','name','nam_62324ccf0940463ca6a38cab89bda8d5',NULL,'{"id": "nam_62324ccf0940463ca6a38cab89bda8d5", "text": "Sign-in", "entity_id": "ent_5beb3681151847da9bca7284a5c9b122", "generated_from_name_id": null, "created_at": "2026-10-24T17:39:17.491Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-24T17:39:17.492Z',NULL,'create','name','nam_2a1cae20be304379a450acebcd853d2a',NULL,'{"id": "nam_2a1cae20be304379a450acebcd853d2a", "text": "Sign-ins", "entity_id": "ent_5beb3681151847da9bca7284a5c9b122", "generated_from_name_id": "nam_62324ccf0940463ca6a38cab89bda8d5", "created_at": "2026-10-24T17:39:17.492Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-24T17:39:17.492Z',NULL,'link','entity_link','ent_5beb3681151847da9bca7284a5c9b122|ent_dbd07f40438c4287a1e854a6291b794d|contains',NULL,'{"from_entity_id": "ent_5beb3681151847da9bca7284a5c9b122", "to_entity_id": "ent_dbd07f40438c4287a1e854a6291b794d", "link_type": "contains", "created_at": "2026-10-24T17:39:17.492Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-24T17:39:17.492Z',NULL,'create','statement','stm_27d8cd8605344e8585ccf547734e63f5',NULL,'{"id": "stm_27d8cd8605344e8585ccf547734e63f5", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-24T17:39:17.492Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-24T17:39:17.493Z',NULL,'create','statement','stm_9da36db51d7e4c0cac9e2553ef8df122',NULL,'{"id": "stm_9da36db51d7e4c0cac9e2553ef8df122", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-24T17:39:17.493Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-24T17:39:17.493Z',NULL,'create','statement','stm_5fc6f6d77ecf414d82d12017d9c0a047',NULL,'{"id": "stm_5fc6f6d77ecf414d82d12017d9c0a047", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-24T17:39:17.493Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-24T17:39:17.494Z',NULL,'create','statement','stm_6178d0ea1b9041b9b577ce6adf8b3596',NULL,'{"id": "stm_6178d0ea1b9041b9b577ce6adf8b3596", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-24T17:39:17.494Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-24T17:39:17.494Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_27d8cd8605344e8585ccf547734e63f5", "to_id": "stm_9da36db51d7e4c0cac9e2553ef8df122", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_5fc6f6d77ecf414d82d12017d9c0a047"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
