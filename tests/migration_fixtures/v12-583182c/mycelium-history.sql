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
INSERT INTO "history_events" VALUES(1,'2026-10-22T18:23:55.032Z',NULL,'create','entity','ent_c50755305bda484bbc3363c3bcc20b35',NULL,'{"id": "ent_c50755305bda484bbc3363c3bcc20b35", "description": "Signing in.", "created_at": "2026-10-22T18:23:55.032Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-22T18:23:55.032Z',NULL,'create','name','nam_dcefb449f1144892b0362794e3514075',NULL,'{"id": "nam_dcefb449f1144892b0362794e3514075", "text": "Login", "entity_id": "ent_c50755305bda484bbc3363c3bcc20b35", "generated_from_name_id": null, "created_at": "2026-10-22T18:23:55.032Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-22T18:23:55.042Z',NULL,'create','name','nam_9a73e5dbad5549fcb0e9e2a60bb993a4',NULL,'{"id": "nam_9a73e5dbad5549fcb0e9e2a60bb993a4", "text": "Logins", "entity_id": "ent_c50755305bda484bbc3363c3bcc20b35", "generated_from_name_id": "nam_dcefb449f1144892b0362794e3514075", "created_at": "2026-10-22T18:23:55.042Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-22T18:23:55.044Z',NULL,'create','entity','ent_9c7fd1cdb83a48b98e65dfce207d39ca',NULL,'{"id": "ent_9c7fd1cdb83a48b98e65dfce207d39ca", "description": "An authenticated visit.", "created_at": "2026-10-22T18:23:55.043Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-22T18:23:55.044Z',NULL,'create','name','nam_5232a59362d84467b32fd6a89a406af1',NULL,'{"id": "nam_5232a59362d84467b32fd6a89a406af1", "text": "Session", "entity_id": "ent_9c7fd1cdb83a48b98e65dfce207d39ca", "generated_from_name_id": null, "created_at": "2026-10-22T18:23:55.044Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-22T18:23:55.044Z',NULL,'create','name','nam_a4ec8f7296f34a0887915ad49a86bbc4',NULL,'{"id": "nam_a4ec8f7296f34a0887915ad49a86bbc4", "text": "Sessions", "entity_id": "ent_9c7fd1cdb83a48b98e65dfce207d39ca", "generated_from_name_id": "nam_5232a59362d84467b32fd6a89a406af1", "created_at": "2026-10-22T18:23:55.044Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-22T18:23:55.045Z',NULL,'create','name','nam_2cfe0827c39a4040b293023a2e48ecef',NULL,'{"id": "nam_2cfe0827c39a4040b293023a2e48ecef", "text": "Sign-in", "entity_id": "ent_c50755305bda484bbc3363c3bcc20b35", "generated_from_name_id": null, "created_at": "2026-10-22T18:23:55.045Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-22T18:23:55.045Z',NULL,'create','name','nam_f3140cfa7eda4d44b3ad3bba437086e3',NULL,'{"id": "nam_f3140cfa7eda4d44b3ad3bba437086e3", "text": "Sign-ins", "entity_id": "ent_c50755305bda484bbc3363c3bcc20b35", "generated_from_name_id": "nam_2cfe0827c39a4040b293023a2e48ecef", "created_at": "2026-10-22T18:23:55.045Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-22T18:23:55.047Z',NULL,'link','entity_link','ent_c50755305bda484bbc3363c3bcc20b35|ent_9c7fd1cdb83a48b98e65dfce207d39ca|contains',NULL,'{"from_entity_id": "ent_c50755305bda484bbc3363c3bcc20b35", "to_entity_id": "ent_9c7fd1cdb83a48b98e65dfce207d39ca", "link_type": "contains", "created_at": "2026-10-22T18:23:55.047Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-22T18:23:55.048Z',NULL,'create','statement','stm_dd7e71ca6ad74852a3a20772553b9a56',NULL,'{"id": "stm_dd7e71ca6ad74852a3a20772553b9a56", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-22T18:23:55.048Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-22T18:23:55.050Z',NULL,'create','statement','stm_28501fff307b4d478ba2138c2e4abd0f',NULL,'{"id": "stm_28501fff307b4d478ba2138c2e4abd0f", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-22T18:23:55.050Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-22T18:23:55.051Z',NULL,'create','statement','stm_4b1c52eb39b34237ab3b55c426f5e3d8',NULL,'{"id": "stm_4b1c52eb39b34237ab3b55c426f5e3d8", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-22T18:23:55.051Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-22T18:23:55.052Z',NULL,'create','statement','stm_28812a786f114b6382e380f7f3ea191d',NULL,'{"id": "stm_28812a786f114b6382e380f7f3ea191d", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-22T18:23:55.052Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-22T18:23:55.054Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_dd7e71ca6ad74852a3a20772553b9a56", "to_id": "stm_28501fff307b4d478ba2138c2e4abd0f", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_4b1c52eb39b34237ab3b55c426f5e3d8"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',14);
COMMIT;
