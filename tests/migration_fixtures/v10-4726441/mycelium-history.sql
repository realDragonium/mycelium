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
INSERT INTO "history_events" VALUES(1,'2026-10-22T18:38:50.263Z',NULL,'create','entity','ent_3fbcfa831cf5488398fe951e470f9f18',NULL,'{"id": "ent_3fbcfa831cf5488398fe951e470f9f18", "description": "Signing in.", "created_at": "2026-10-22T18:38:50.263Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-22T18:38:50.264Z',NULL,'create','name','nam_898a632c3373437a869f5c85cd13b5cb',NULL,'{"id": "nam_898a632c3373437a869f5c85cd13b5cb", "text": "Login", "entity_id": "ent_3fbcfa831cf5488398fe951e470f9f18", "generated_from_name_id": null, "created_at": "2026-10-22T18:38:50.264Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-22T18:38:50.273Z',NULL,'create','name','nam_d962ba27633d47a89900d0524e5bd856',NULL,'{"id": "nam_d962ba27633d47a89900d0524e5bd856", "text": "Logins", "entity_id": "ent_3fbcfa831cf5488398fe951e470f9f18", "generated_from_name_id": "nam_898a632c3373437a869f5c85cd13b5cb", "created_at": "2026-10-22T18:38:50.273Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-22T18:38:50.274Z',NULL,'create','entity','ent_04e8ac3c08054ee6b5b2215cb5aad523',NULL,'{"id": "ent_04e8ac3c08054ee6b5b2215cb5aad523", "description": "An authenticated visit.", "created_at": "2026-10-22T18:38:50.274Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-22T18:38:50.274Z',NULL,'create','name','nam_de567376472a4cf5839e7b671808c7cb',NULL,'{"id": "nam_de567376472a4cf5839e7b671808c7cb", "text": "Session", "entity_id": "ent_04e8ac3c08054ee6b5b2215cb5aad523", "generated_from_name_id": null, "created_at": "2026-10-22T18:38:50.274Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-22T18:38:50.275Z',NULL,'create','name','nam_c653a1658db24d57a13a6f7c68d9220f',NULL,'{"id": "nam_c653a1658db24d57a13a6f7c68d9220f", "text": "Sessions", "entity_id": "ent_04e8ac3c08054ee6b5b2215cb5aad523", "generated_from_name_id": "nam_de567376472a4cf5839e7b671808c7cb", "created_at": "2026-10-22T18:38:50.275Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-22T18:38:50.276Z',NULL,'create','name','nam_24745d5f803b442faebcb906bedc11f9',NULL,'{"id": "nam_24745d5f803b442faebcb906bedc11f9", "text": "Sign-in", "entity_id": "ent_3fbcfa831cf5488398fe951e470f9f18", "generated_from_name_id": null, "created_at": "2026-10-22T18:38:50.276Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-22T18:38:50.276Z',NULL,'create','name','nam_2e20ac0b1bc24d529d60577cc74c9947',NULL,'{"id": "nam_2e20ac0b1bc24d529d60577cc74c9947", "text": "Sign-ins", "entity_id": "ent_3fbcfa831cf5488398fe951e470f9f18", "generated_from_name_id": "nam_24745d5f803b442faebcb906bedc11f9", "created_at": "2026-10-22T18:38:50.276Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-22T18:38:50.278Z',NULL,'link','entity_link','ent_3fbcfa831cf5488398fe951e470f9f18|ent_04e8ac3c08054ee6b5b2215cb5aad523|contains',NULL,'{"from_entity_id": "ent_3fbcfa831cf5488398fe951e470f9f18", "to_entity_id": "ent_04e8ac3c08054ee6b5b2215cb5aad523", "link_type": "contains", "created_at": "2026-10-22T18:38:50.277Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-22T18:38:50.279Z',NULL,'create','statement','stm_a623b93814284a4f9c37775c1ea83054',NULL,'{"id": "stm_a623b93814284a4f9c37775c1ea83054", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-22T18:38:50.279Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-22T18:38:50.280Z',NULL,'create','statement','stm_073ecb83ee8b4bb7836deec77e2f9de2',NULL,'{"id": "stm_073ecb83ee8b4bb7836deec77e2f9de2", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-22T18:38:50.280Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-22T18:38:50.282Z',NULL,'create','statement','stm_f293326272de49bf8534de6823cf2527',NULL,'{"id": "stm_f293326272de49bf8534de6823cf2527", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-22T18:38:50.282Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-22T18:38:50.283Z',NULL,'create','statement','stm_7da09b7d648b4de6b083adbfabe1f9ac',NULL,'{"id": "stm_7da09b7d648b4de6b083adbfabe1f9ac", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-22T18:38:50.283Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-22T18:38:50.285Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_a623b93814284a4f9c37775c1ea83054", "to_id": "stm_073ecb83ee8b4bb7836deec77e2f9de2", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_f293326272de49bf8534de6823cf2527"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',14);
COMMIT;
