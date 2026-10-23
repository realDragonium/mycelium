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
INSERT INTO "history_events" VALUES(1,'2026-10-23T14:13:04.400Z',NULL,'create','entity','ent_b312d5b2fad44bbc9bdc80c5f2b732cc',NULL,'{"id": "ent_b312d5b2fad44bbc9bdc80c5f2b732cc", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T14:13:04.400Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-23T14:13:04.400Z',NULL,'create','name','nam_0c6d80b264f04fb9a9555062e7e26250',NULL,'{"id": "nam_0c6d80b264f04fb9a9555062e7e26250", "text": "Login", "entity_id": "ent_b312d5b2fad44bbc9bdc80c5f2b732cc", "generated_from_name_id": null, "created_at": "2026-10-23T14:13:04.400Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-23T14:13:04.400Z',NULL,'update','entity','ent_b312d5b2fad44bbc9bdc80c5f2b732cc','{"id": "ent_b312d5b2fad44bbc9bdc80c5f2b732cc", "description": "Signing in.", "preferred_name_id": null, "created_at": "2026-10-23T14:13:04.400Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_b312d5b2fad44bbc9bdc80c5f2b732cc", "description": "Signing in.", "preferred_name_id": "nam_0c6d80b264f04fb9a9555062e7e26250", "created_at": "2026-10-23T14:13:04.400Z", "updated_at": "2026-10-23T14:13:04.400Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-23T14:13:04.404Z',NULL,'create','name','nam_2c4c908db3014d12a0a22689b4b29102',NULL,'{"id": "nam_2c4c908db3014d12a0a22689b4b29102", "text": "Logins", "entity_id": "ent_b312d5b2fad44bbc9bdc80c5f2b732cc", "generated_from_name_id": "nam_0c6d80b264f04fb9a9555062e7e26250", "created_at": "2026-10-23T14:13:04.404Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-23T14:13:04.404Z',NULL,'create','entity','ent_e2634f427fab4d2493ea446580abb196',NULL,'{"id": "ent_e2634f427fab4d2493ea446580abb196", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T14:13:04.404Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-23T14:13:04.404Z',NULL,'create','name','nam_7ec4a6e430d14185b666443b60d21604',NULL,'{"id": "nam_7ec4a6e430d14185b666443b60d21604", "text": "Session", "entity_id": "ent_e2634f427fab4d2493ea446580abb196", "generated_from_name_id": null, "created_at": "2026-10-23T14:13:04.404Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-23T14:13:04.404Z',NULL,'update','entity','ent_e2634f427fab4d2493ea446580abb196','{"id": "ent_e2634f427fab4d2493ea446580abb196", "description": "An authenticated visit.", "preferred_name_id": null, "created_at": "2026-10-23T14:13:04.404Z", "updated_at": null, "created_by": null, "updated_by": null}','{"id": "ent_e2634f427fab4d2493ea446580abb196", "description": "An authenticated visit.", "preferred_name_id": "nam_7ec4a6e430d14185b666443b60d21604", "created_at": "2026-10-23T14:13:04.404Z", "updated_at": "2026-10-23T14:13:04.404Z", "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-23T14:13:04.405Z',NULL,'create','name','nam_5331e5b72d50497e915acf2ede076844',NULL,'{"id": "nam_5331e5b72d50497e915acf2ede076844", "text": "Sessions", "entity_id": "ent_e2634f427fab4d2493ea446580abb196", "generated_from_name_id": "nam_7ec4a6e430d14185b666443b60d21604", "created_at": "2026-10-23T14:13:04.405Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-23T14:13:04.405Z',NULL,'create','name','nam_7bd68cd8d2da4be48c5ddbe832afb54b',NULL,'{"id": "nam_7bd68cd8d2da4be48c5ddbe832afb54b", "text": "Sign-in", "entity_id": "ent_b312d5b2fad44bbc9bdc80c5f2b732cc", "generated_from_name_id": null, "created_at": "2026-10-23T14:13:04.405Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-23T14:13:04.405Z',NULL,'create','name','nam_66ec0a3144a44caf9322e2252d5ce5c6',NULL,'{"id": "nam_66ec0a3144a44caf9322e2252d5ce5c6", "text": "Sign-ins", "entity_id": "ent_b312d5b2fad44bbc9bdc80c5f2b732cc", "generated_from_name_id": "nam_7bd68cd8d2da4be48c5ddbe832afb54b", "created_at": "2026-10-23T14:13:04.405Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-23T14:13:04.405Z',NULL,'link','entity_link','ent_b312d5b2fad44bbc9bdc80c5f2b732cc|ent_e2634f427fab4d2493ea446580abb196|contains',NULL,'{"from_entity_id": "ent_b312d5b2fad44bbc9bdc80c5f2b732cc", "to_entity_id": "ent_e2634f427fab4d2493ea446580abb196", "link_type": "contains", "created_at": "2026-10-23T14:13:04.405Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-23T14:13:04.406Z',NULL,'create','statement','stm_0923a5aa20e8402093c4b36b23518dc8',NULL,'{"id": "stm_0923a5aa20e8402093c4b36b23518dc8", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-23T14:13:04.406Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-23T14:13:04.406Z',NULL,'create','statement','stm_58a5ba5ceca0494782b6adf172ee2027',NULL,'{"id": "stm_58a5ba5ceca0494782b6adf172ee2027", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-23T14:13:04.406Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-23T14:13:04.407Z',NULL,'create','statement','stm_becdbede9e48467f8d39f6a6faee4a8b',NULL,'{"id": "stm_becdbede9e48467f8d39f6a6faee4a8b", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-23T14:13:04.407Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(15,'2026-10-23T14:13:04.407Z',NULL,'create','statement','stm_ffe56aa66c0c46d9ba568c3b6cd5333a',NULL,'{"id": "stm_ffe56aa66c0c46d9ba568c3b6cd5333a", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-23T14:13:04.407Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(16,'2026-10-23T14:13:04.407Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_0923a5aa20e8402093c4b36b23518dc8", "to_id": "stm_58a5ba5ceca0494782b6adf172ee2027", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_becdbede9e48467f8d39f6a6faee4a8b"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',16);
COMMIT;
