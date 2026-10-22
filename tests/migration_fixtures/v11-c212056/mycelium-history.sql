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
INSERT INTO "history_events" VALUES(1,'2026-10-22T18:38:52.700Z',NULL,'create','entity','ent_87833d85c23b44eeb309156d069c9911',NULL,'{"id": "ent_87833d85c23b44eeb309156d069c9911", "description": "Signing in.", "created_at": "2026-10-22T18:38:52.700Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(2,'2026-10-22T18:38:52.700Z',NULL,'create','name','nam_6844003539e74b94b81827c6d23ed217',NULL,'{"id": "nam_6844003539e74b94b81827c6d23ed217", "text": "Login", "entity_id": "ent_87833d85c23b44eeb309156d069c9911", "generated_from_name_id": null, "created_at": "2026-10-22T18:38:52.700Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(3,'2026-10-22T18:38:52.709Z',NULL,'create','name','nam_6fe6679014434233b08e9a702dbaaec4',NULL,'{"id": "nam_6fe6679014434233b08e9a702dbaaec4", "text": "Logins", "entity_id": "ent_87833d85c23b44eeb309156d069c9911", "generated_from_name_id": "nam_6844003539e74b94b81827c6d23ed217", "created_at": "2026-10-22T18:38:52.709Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(4,'2026-10-22T18:38:52.711Z',NULL,'create','entity','ent_84f2da7e6d3f4fa2bcf9150e92673350',NULL,'{"id": "ent_84f2da7e6d3f4fa2bcf9150e92673350", "description": "An authenticated visit.", "created_at": "2026-10-22T18:38:52.711Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(5,'2026-10-22T18:38:52.711Z',NULL,'create','name','nam_58c86ee0187b42e8953e7b5b4f9f26b5',NULL,'{"id": "nam_58c86ee0187b42e8953e7b5b4f9f26b5", "text": "Session", "entity_id": "ent_84f2da7e6d3f4fa2bcf9150e92673350", "generated_from_name_id": null, "created_at": "2026-10-22T18:38:52.711Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(6,'2026-10-22T18:38:52.711Z',NULL,'create','name','nam_3702dd4a31794e66b994647c749da9c7',NULL,'{"id": "nam_3702dd4a31794e66b994647c749da9c7", "text": "Sessions", "entity_id": "ent_84f2da7e6d3f4fa2bcf9150e92673350", "generated_from_name_id": "nam_58c86ee0187b42e8953e7b5b4f9f26b5", "created_at": "2026-10-22T18:38:52.711Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(7,'2026-10-22T18:38:52.712Z',NULL,'create','name','nam_422066aea56a4593b78340ffc7b46aa9',NULL,'{"id": "nam_422066aea56a4593b78340ffc7b46aa9", "text": "Sign-in", "entity_id": "ent_87833d85c23b44eeb309156d069c9911", "generated_from_name_id": null, "created_at": "2026-10-22T18:38:52.712Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(8,'2026-10-22T18:38:52.713Z',NULL,'create','name','nam_d77461af16ec4443bb29a6708c3f615a',NULL,'{"id": "nam_d77461af16ec4443bb29a6708c3f615a", "text": "Sign-ins", "entity_id": "ent_87833d85c23b44eeb309156d069c9911", "generated_from_name_id": "nam_422066aea56a4593b78340ffc7b46aa9", "created_at": "2026-10-22T18:38:52.713Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(9,'2026-10-22T18:38:52.714Z',NULL,'link','entity_link','ent_87833d85c23b44eeb309156d069c9911|ent_84f2da7e6d3f4fa2bcf9150e92673350|contains',NULL,'{"from_entity_id": "ent_87833d85c23b44eeb309156d069c9911", "to_entity_id": "ent_84f2da7e6d3f4fa2bcf9150e92673350", "link_type": "contains", "created_at": "2026-10-22T18:38:52.714Z", "created_by": null}',NULL);
INSERT INTO "history_events" VALUES(10,'2026-10-22T18:38:52.715Z',NULL,'create','statement','stm_0fe58b7ba3824c4e85567db6d44e4e37',NULL,'{"id": "stm_0fe58b7ba3824c4e85567db6d44e4e37", "kind": "event", "text": "A user submits the Login form.", "created_at": "2026-10-22T18:38:52.715Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(11,'2026-10-22T18:38:52.716Z',NULL,'create','statement','stm_b7cf407f1fa2443d8057ecc80ef72193',NULL,'{"id": "stm_b7cf407f1fa2443d8057ecc80ef72193", "kind": "event", "text": "The server issues a Session token.", "created_at": "2026-10-22T18:38:52.716Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(12,'2026-10-22T18:38:52.717Z',NULL,'create','statement','stm_d778506100ad480f852df8a43959759e',NULL,'{"id": "stm_d778506100ad480f852df8a43959759e", "kind": "state", "text": "The account is locked.", "created_at": "2026-10-22T18:38:52.717Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(13,'2026-10-22T18:38:52.718Z',NULL,'create','statement','stm_a3fe128d74f44e1f9c553ed6559a07ca',NULL,'{"id": "stm_a3fe128d74f44e1f9c553ed6559a07ca", "kind": "rule", "text": "A Session token expires after twelve hours.", "created_at": "2026-10-22T18:38:52.718Z", "updated_at": null, "created_by": null, "updated_by": null}',NULL);
INSERT INTO "history_events" VALUES(14,'2026-10-22T18:38:52.720Z',NULL,'link','statement_link','1',NULL,'{"link_id": 1, "from_id": "stm_0fe58b7ba3824c4e85567db6d44e4e37", "to_id": "stm_b7cf407f1fa2443d8057ecc80ef72193", "link_type": "triggers", "when": {"op": "not", "of": [{"statement_id": "stm_d778506100ad480f852df8a43959759e"}]}}',NULL);
CREATE INDEX history_target
    ON history_events (target_kind, target_id, event_id);
CREATE INDEX history_at
    ON history_events (at);
CREATE INDEX history_actor
    ON history_events (actor);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('history_events',14);
COMMIT;
