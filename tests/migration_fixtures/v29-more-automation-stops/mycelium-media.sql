PRAGMA user_version = 0;
BEGIN TRANSACTION;
CREATE TABLE media_attachments (
    media_id    TEXT NOT NULL REFERENCES media_items(id) ON DELETE CASCADE,
    target_kind TEXT NOT NULL CHECK (target_kind IN ('statement', 'entity')),
    target_id   TEXT NOT NULL,
    attached_at TEXT NOT NULL,
    attached_by TEXT,
    PRIMARY KEY (media_id, target_kind, target_id)
);
INSERT INTO "media_attachments" VALUES('med_9bd0e87efc70','statement','stm_2f88336cbac44a1d83592c6cfdf4c937','2026-10-25T10:00:28.299Z','curator');
CREATE TABLE media_blobs (
    media_id TEXT PRIMARY KEY REFERENCES media_items(id) ON DELETE CASCADE,
    data     BLOB NOT NULL
);
INSERT INTO "media_blobs" VALUES('med_9bd0e87efc70',X'89504E470D0A1A0A0000000D49484452000000010000000108000000003A7E9B550000000A49444154789C636000000002000148AFA4710000000049454E44AE426082');
CREATE TABLE media_items (
    id                  TEXT PRIMARY KEY,
    content_type        TEXT NOT NULL,
    byte_size           INTEGER NOT NULL,
    sha256              TEXT NOT NULL,
    content_version     INTEGER NOT NULL DEFAULT 1,
    content_updated_at  TEXT NOT NULL,
    alt_text            TEXT NOT NULL DEFAULT '',
    caption             TEXT NOT NULL DEFAULT '',
    origin              TEXT NOT NULL CHECK (origin IN ('uploaded', 'agent', 'captured')),
    source_url          TEXT,
    product_version     TEXT,
    captured_at         TEXT,
    audiences           TEXT,
    labelled_by         TEXT,
    labelled_at         TEXT,
    content_changed_at  TEXT,
    created_at          TEXT NOT NULL,
    created_by          TEXT,
    updated_at          TEXT NOT NULL,
    updated_by          TEXT
);
INSERT INTO "media_items" VALUES('med_9bd0e87efc70','image/png',67,'eaa4a94ea300e0d2c775968cbe42f0b5b51ceafdeb73d64e9efddf6d4e880865',1,'2026-10-25T10:00:28.299Z','The sign-in form','Signing in','uploaded',NULL,NULL,NULL,'["external-technical"]','curator','2026-10-25T10:00:28.299Z',NULL,'2026-10-25T10:00:28.299Z','curator','2026-10-25T10:00:28.299Z','curator');
CREATE TABLE media_uploads (
    token_hash    TEXT PRIMARY KEY,
    metadata_json TEXT NOT NULL,
    created_by    TEXT,
    created_at    TEXT NOT NULL,
    expires_at    TEXT NOT NULL
);
CREATE INDEX media_attachments_target
    ON media_attachments (target_kind, target_id);
COMMIT;
