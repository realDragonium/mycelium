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
INSERT INTO "history_events" VALUES(1,'2026-10-23T05:44:25.714Z',NULL,'create','entity','ent_7080a7f1736c48a0a7bc7ef5a17764f3',NULL,'{"id": "ent_7080a7f1736c48a0a7bc7ef5a17764f3", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T05:44:25.714Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-23T05:44:25.714Z',NULL,'create','name','nam_e92662b7560847e4b9d0f2e44b97cc6b',NULL,'{"id": "nam_e92662b7560847e4b9d0f2e44b97cc6b", "text": "Login", "entity_id": "ent_7080a7f1736c48a0a7bc7ef5a17764f3", "generated_from_name_id": null, "created_at": "2026-10-23T05:44:25.714Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-23T05:44:25.714Z',NULL,'update','entity','ent_7080a7f1736c48a0a7bc7ef5a17764f3','{"id": "ent_7080a7f1736c48a0a7bc7ef5a17764f3", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T05:44:25.714Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_7080a7f1736c48a0a7bc7ef5a17764f3", "description": "Signing in.", "preferred_name_id": "nam_e92662b7560847e4b9d0f2e44b97cc6b", "created_at": "2026-10-23T05:44:25.714Z", "updated_at": "2026-10-23T05:44:25.714Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-23T05:44:25.717Z',NULL,'create','name','nam_e53168319c0040579e8507af71c2bdda',NULL,'{"id": "nam_e53168319c0040579e8507af71c2bdda", "text": "Logins", "entity_id": "ent_7080a7f1736c48a0a7bc7ef5a17764f3", "generated_from_name_id": "nam_e92662b7560847e4b9d0f2e44b97cc6b", "created_at": "2026-10-23T05:44:25.717Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-23T05:44:25.718Z',NULL,'create','entity','ent_c3e0695a4a774074b5e77f3435e2f0a7',NULL,'{"id": "ent_c3e0695a4a774074b5e77f3435e2f0a7", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T05:44:25.718Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-23T05:44:25.718Z',NULL,'create','name','nam_5c87f204bbd34e8ebaa5ba3ac7837600',NULL,'{"id": "nam_5c87f204bbd34e8ebaa5ba3ac7837600", "text": "Session", "entity_id": "ent_c3e0695a4a774074b5e77f3435e2f0a7", "generated_from_name_id": null, "created_at": "2026-10-23T05:44:25.718Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-23T05:44:25.718Z',NULL,'update','entity','ent_c3e0695a4a774074b5e77f3435e2f0a7','{"id": "ent_c3e0695a4a774074b5e77f3435e2f0a7", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T05:44:25.718Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_c3e0695a4a774074b5e77f3435e2f0a7", "description": "An authenticated visit.", "preferred_name_id": "nam_5c87f204bbd34e8ebaa5ba3ac7837600", "created_at": "2026-10-23T05:44:25.718Z", "updated_at": "2026-10-23T05:44:25.718Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-23T05:44:25.718Z',NULL,'create','name','nam_3cc565f353b643fe83155561fefadba3',NULL,'{"id": "nam_3cc565f353b643fe83155561fefadba3", "text": "Sessions", "entity_id": "ent_c3e0695a4a774074b5e77f3435e2f0a7", "generated_from_name_id": "nam_5c87f204bbd34e8ebaa5ba3ac7837600", "created_at": "2026-10-23T05:44:25.718Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-23T05:44:25.718Z',NULL,'create','name','nam_0294ad916b6e4e1fbc0759b01ccdf1fa',NULL,'{"id": "nam_0294ad916b6e4e1fbc0759b01ccdf1fa", "text": "Sign-in", "entity_id": "ent_7080a7f1736c48a0a7bc7ef5a17764f3", "generated_from_name_id": null, "created_at": "2026-10-23T05:44:25.718Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-23T05:44:25.718Z',NULL,'create','name','nam_12f23c68780443cbb519ddbcd5c923d4',NULL,'{"id": "nam_12f23c68780443cbb519ddbcd5c923d4", "text": "Sign-ins", "entity_id": "ent_7080a7f1736c48a0a7bc7ef5a17764f3", "generated_from_name_id": "nam_0294ad916b6e4e1fbc0759b01ccdf1fa", "created_at": "2026-10-23T05:44:25.718Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-23T05:44:25.719Z',NULL,'link','entity_link','ent_7080a7f1736c48a0a7bc7ef5a17764f3|ent_c3e0695a4a774074b5e77f3435e2f0a7|contains',NULL,'{"from_entity_id": "ent_7080a7f1736c48a0a7bc7ef5a17764f3", "to_entity_id": "ent_c3e0695a4a774074b5e77f3435e2f0a7", "link_type": "contains", "created_at": "2026-10-23T05:44:25.719Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-23T05:44:25.719Z',NULL,'create','statement','stm_9bba531a910243c193a2d28aae021e9f',NULL,'{"id": "stm_9bba531a910243c193a2d28aae021e9f", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-23T05:44:25.719Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-23T05:44:25.719Z',NULL,'create','statement','stm_84972ec0c91d4e039b7c578f6f8109f9',NULL,'{"id": "stm_84972ec0c91d4e039b7c578f6f8109f9", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-23T05:44:25.719Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-23T05:44:25.720Z',NULL,'create','statement','stm_8cb28b0a4ed5469f9882b8dd9a642470',NULL,'{"id": "stm_8cb28b0a4ed5469f9882b8dd9a642470", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-23T05:44:25.720Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-23T05:44:25.720Z',NULL,'create','statement','stm_68aa5d71cfc64ef695deff10b77243f6',NULL,'{"id": "stm_68aa5d71cfc64ef695deff10b77243f6", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-23T05:44:25.720Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-23T05:44:25.721Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_9bba531a910243c193a2d28aae021e9f", "to_id": "stm_84972ec0c91d4e039b7c578f6f8109f9", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_8cb28b0a4ed5469f9882b8dd9a642470"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
