# media Specification

## Purpose
Store screenshots, GIFs and short recordings that illustrate statements and concepts, keep each one within its own audience label wherever it leaves the server, and let documentation runs place them in the documents they write.

## Requirements

### Requirement: Accepted formats are sniffed from the bytes
The system SHALL accept only PNG, JPEG, WebP and GIF images and MP4 and WebM videos, deciding the type from the file's leading bytes and never from a file name or declared content type, and MUST refuse anything else, including SVG, HTML and PDF, with 415.

#### Scenario: SVG upload
- **WHEN** a writer uploads `<svg/>` as a media file
- **THEN** the upload is refused with 415 and no media item is created

#### Scenario: Misnamed file
- **WHEN** a PNG is uploaded under a declared type of `image/jpeg`
- **THEN** it is stored and served as `image/png`

### Requirement: Capture metadata is stripped
The system SHALL remove capture metadata before storing bytes by walking the file's own structure (PNG text, time and EXIF chunks; JPEG EXIF, XMP, comments and other application segments; GIF comments, plain text and non-looping application extensions; WebP EXIF and XMP chunks), and MUST refuse a file whose structure does not parse rather than store it as sent.

#### Scenario: JPEG with GPS data
- **WHEN** a writer uploads a JPEG photo carrying EXIF GPS coordinates
- **THEN** the stored and served bytes contain no EXIF segment

#### Scenario: Video metadata stripped in place
- **WHEN** a writer uploads an MP4 with a `udta` box or a WebM with tags, title or date
- **THEN** that metadata is overwritten as `free` (MP4) or `Void` (WebM) padding of the same size, so the stored file keeps its length and sample offsets

#### Scenario: Damaged file
- **WHEN** an upload starts with a PNG signature but its chunks do not parse
- **THEN** the upload is refused with 415 saying the file is damaged

### Requirement: Size limits
The system SHALL cap media at the saved media settings `image_max_bytes` (default 5 MB) for images and `video_max_bytes` (default 20 MB) for videos; an upload body larger than the larger of the two caps is refused with 413 as soon as it exceeds it, without reading the rest, and a file over its own kind's cap is refused with 415.

#### Scenario: Oversized body
- **WHEN** an upload body grows past the larger media cap
- **THEN** the request is refused with 413 and nothing is stored

#### Scenario: Image over the image cap
- **WHEN** a 6 MB PNG is uploaded with the defaults
- **THEN** the upload is refused with 415 naming the 5 MB image limit

### Requirement: Media item details
The system SHALL store with each item an id prefixed `med_`, its content type, byte size, `content_version` (starting at 1) and `content_updated_at`, required `alt_text` saying what it shows (up to 1000 characters), optional `caption` (up to 1000), `origin` (`uploaded`, `agent` or `captured`), optional `source_url` (an `http` or `https` URL), `product_version` (up to 100 characters) and `captured_at` (an ISO date or timestamp), and its attachments to statements and concepts.

#### Scenario: Upload without alt text
- **WHEN** a writer uploads an image with empty `alt_text`
- **THEN** the upload is refused

#### Scenario: Invalid source URL
- **WHEN** an upload gives `source_url` `ftp://example.test/invoices`
- **THEN** the upload is refused

### Requirement: Uploading from the web app
The system SHALL let a real writer or admin upload a file through `POST /api/media` with the file as the raw request body and its details, plus an optional `statement_id` and `entity_id` to attach it to, as query parameters; the item's origin is `uploaded`, and attaching to a statement or concept that does not exist refuses the upload.

#### Scenario: Upload attached to a statement
- **WHEN** a writer posts a PNG to `/api/media?alt_text=Export%20dialog&statement_id=<id>`
- **THEN** a media item is created and listed among that statement's media

#### Scenario: Drafter uploads through HTTP
- **WHEN** a drafter posts a file to `/api/media`
- **THEN** the request is refused for lacking a real writer role

### Requirement: Agent upload links
The system SHALL expose `create_media_upload(alt_text, caption?, source_url?, product_version?, captured_at?)`, advertised over MCP and callable by writers, drafters and admins, returning a single-use `upload_url` under `/api/media/uploads/`, its `expires_at` 15 minutes later, `max_bytes` and instructions; the URL is absolute when `MYCELIUM_PUBLIC_URL` is set and a path otherwise.

#### Scenario: Agent asks for an upload link
- **WHEN** a drafter calls `create_media_upload(alt_text="The invoice export dialog with CSV selected")`
- **THEN** it receives an `upload_url` and an `expires_at` 15 minutes ahead

### Requirement: Completing an agent upload
The system SHALL accept the bytes POSTed to an upload link without sign-in, since the link is the credential, creating an item with origin `agent` and the link's details and answering 201 with `media_id` and `content_type`; the link stops working once it accepted a file or expired (404 afterwards), and a refused file leaves the link usable for a corrected one.

#### Scenario: Link reused
- **WHEN** an agent posts a second file to a link that already created a media item
- **THEN** the request is answered 404 as an unknown, used or expired link

#### Scenario: Refused file then a valid one
- **WHEN** an agent posts an SVG to a fresh link and then a PNG
- **THEN** the first post is refused with 415 and the second creates the item

### Requirement: Media as draft evidence
The system SHALL accept a media id as `{"kind": "media", "media_id": ..., "claim": ...}` evidence on a draft operation (see the `drafts-and-review` capability), refusing an id that names no media, showing the reviewer the item's alt text and caption when the evidence quotes nothing, and, when the draft is applied, attaching the item to the statements or concept that operation wrote.

#### Scenario: Applied draft with a screenshot
- **WHEN** a draft whose `upsert_statement` operation cites media evidence is applied
- **THEN** the media item is attached to the statement that operation wrote

### Requirement: Editing, replacing and attaching media
The system SHALL let a real writer or admin edit an item's details through `PATCH /api/media/{id}` (alt text must stay nonblank), replace its bytes through `PUT /api/media/{id}/content`, attach it to a statement or concept through `POST /api/media/{id}/attachments` (the target must exist) and detach it through `DELETE /api/media/{id}/attachments/{kind}/{target_id}`; replacing the bytes keeps the id and URL and increments `content_version`.

#### Scenario: Replacing a screenshot
- **WHEN** a writer replaces the bytes of a media item at `content_version` 1
- **THEN** the item keeps its id and reports `content_version` 2

### Requirement: Deleting media
The system MUST require an admin to delete a media item through `DELETE /api/media/{id}`; deletion removes the item, its bytes and its attachments.

#### Scenario: Writer deletes media
- **WHEN** a writer calls `DELETE /api/media/{id}`
- **THEN** the request is refused and the item remains

### Requirement: Media audience labels
The system SHALL give each item its own audience label, set by a real writer or admin through `PUT /api/media/{id}/audiences` with a list of live audience ids (at most 50) or `null` for unlabelled; an unlabelled item, which every upload starts as, is visible to internal audiences only, and a labelled item is visible to the audiences it grants and those that include them (see the `audiences` capability). There is no AI labeller for media.

#### Scenario: Unknown audience
- **WHEN** a writer labels an item with an audience id that is not live
- **THEN** the label is refused

#### Scenario: New upload
- **WHEN** an agent's upload completes
- **THEN** the item is unlabelled and only internal audiences may see it

### Requirement: Media label is independent of what it illustrates
The system MUST check media only against its own label wherever it reaches a documentation run or a document, so a statement visible to an audience never widens the visibility of media attached to it.

#### Scenario: Internal screenshot on an external statement
- **WHEN** an unlabelled screenshot is attached to a statement labelled for the external `customers` audience
- **THEN** a documentation run for `customers` is not offered the screenshot

### Requirement: Replaced content flags the label
The system SHALL flag a labelled item with `content_changed_at` when its bytes are replaced, keeping the label, and clear the flag when a writer confirms the label through `POST /api/media/{id}/audiences/confirm` or sets a new one.

#### Scenario: Confirming after a replacement
- **WHEN** a writer replaces a labelled item's bytes and then confirms its label
- **THEN** the label is unchanged and `content_changed_at` is cleared

### Requirement: Serving media bytes
The system SHALL serve an item's bytes through `GET /api/media/{id}/content` to authenticated callers as its sniffed content type with `X-Content-Type-Options: nosniff`, `Content-Security-Policy: default-src 'none'; sandbox`, `Content-Disposition: inline; filename="<id>.<ext>"`, `Cache-Control: private, no-cache` and an ETag of its content hash, answering 304 to a matching `If-None-Match`.

#### Scenario: Revalidating a cached image
- **WHEN** a browser requests content with the current ETag in `If-None-Match`
- **THEN** the response is 304 with no body

### Requirement: Listing media for a statement or concept
The system SHALL expose `list_media(statement_id?, entity_id?, media_id?, show="all")`, advertised over MCP, which takes at most one id. With a statement or concept it refuses one that does not exist or the caller may not see and returns the attached items the caller's audience may see; with `media_id` it returns that item; with none it returns the media library filtered by `show`. Each item comes with details, label, attachments, `stale` reasons and `url`.

#### Scenario: Both ids given
- **WHEN** a caller passes both `statement_id` and `entity_id`
- **THEN** the call is refused asking for at most one

#### Scenario: Library over MCP
- **WHEN** an agent calls `list_media` with no id and `show` `unattached`
- **THEN** it gets the same items as `GET /api/media?show=unattached`

### Requirement: Media library
The system SHALL list up to 200 items newest first through `GET /api/media` filtered by `show` of `all`, `unattached`, `no_alt_text`, `unlabelled` or `old`, and return one item through `GET /api/media/{id}`, to any authenticated caller with full access by role.

#### Scenario: Unattached filter
- **WHEN** a curator lists media with `show=unattached`
- **THEN** only items attached to no statement or concept are returned

### Requirement: Old media
The system SHALL report an item as old, with reasons in `stale`, when its capture date (or, without one, its last upload or replacement) is older than `stale_after_days` (default 365) or when it records a `product_version` other than the media setting `product_version` while that setting is nonblank; the knowledge-health counts include how many items are old (see the `knowledge-health` capability).

#### Scenario: Captured against an older version
- **WHEN** the current product version setting is `4.2` and an item records `product_version` `4.1`
- **THEN** the item's `stale` names the version mismatch

### Requirement: Attachments follow merges and deletes
The system SHALL move a statement's or concept's media attachments to the survivor when it is merged, and remove them when it is deleted, leaving the media items themselves in the library.

#### Scenario: Statement deleted
- **WHEN** an admin deletes a statement with an attached screenshot
- **THEN** the screenshot remains in the library, unattached

### Requirement: Media offered to documentation runs
The system SHALL, after each read a documentation run makes, offer the writer the media attached to the statements it just read (and, for the opening read of an anchored run, to the concept) that have alt text and that the run's audience may see, giving id, alt text and caption; the writer places one as `![alt text](media:med_<id>)`.

#### Scenario: Screenshot on a read statement
- **WHEN** a run for an internal audience reads a statement with a labelled screenshot that has alt text
- **THEN** the writer is told the screenshot's id, alt text and caption

### Requirement: Media placement gate
The system MUST refuse a generated document that places media the run was not offered, an image with empty alt text, or a `media:` reference outside image syntax; a manual edit may place any item with alt text that the document's audience may see. The reviewer judges each placed image by its alt text and caption for fit and exposure.

#### Scenario: Unoffered media
- **WHEN** the writer places a media id it was never offered
- **THEN** the emit is refused and the writer is told to place only offered media

### Requirement: Rendering media in documents
The system SHALL render a `media:` image in a document's `body_html` as an image from the media content route, so each reader's own audience check applies, and render any other image in a document as its alt text only.

#### Scenario: External image link
- **WHEN** a document body contains `![Logo](https://example.test/logo.png)`
- **THEN** its `body_html` shows the text `Logo` and loads no external image

### Requirement: Media in published documents
The system SHALL commit each image a published document places beside the Markdown as `<file stem>-media/<id>-v<version>.<ext>`, link it by that relative path, and map those links back to `media:` references when reading the published copy; publishing MUST be refused when a placed item was deleted, or its bytes are missing, or the audience the document was written for may no longer see it.

#### Scenario: Publishing a document with a screenshot
- **WHEN** `docs/exporting-invoices.md` places media `med_0123456789ab` at `content_version` 2
- **THEN** the pull request also adds `docs/exporting-invoices-media/med_0123456789ab-v2.png`

#### Scenario: Image relabelled away
- **WHEN** a placed image is relabelled so the document's external audience may not see it
- **THEN** publishing is refused naming the media

### Requirement: Media changes make documents out of date
The system SHALL mark a document out of date when an image its current revision places was replaced after that revision was written, was deleted, or is no longer visible to the document's audience, and brief an `update_sources` revision with what to do about each image (see the `documentation` capability).

#### Scenario: Screenshot replaced
- **WHEN** a writer replaces the bytes of an image a document places
- **THEN** the document's `stale.media_changes` lists it as `replaced` with its alt text

### Requirement: Media storage
The system SHALL keep media items, bytes, attachments and pending upload links in their own `mycelium-media.db`, apart from the knowledge database, and include media in `mycelium export` unless `--no-media` is given (see the `storage-and-backup` capability).

#### Scenario: Export without media
- **WHEN** an operator runs `mycelium export --no-media`
- **THEN** the archive carries no media items or bytes

### Requirement: Editing media over MCP
The system SHALL advertise `edit_media(request)` to real writers and admins, which changes an item's details (alt text required), sets or clears its audience label, confirms a label after its content changed, attaches it to or detaches it from a statement or concept, or deletes it, which needs a real admin. `replace_content` SHALL return a single-use upload link, valid 15 minutes, whose accepted bytes become the item's new content, as replacing it in the web app does.

#### Scenario: Agent replaces a screenshot
- **WHEN** a writer agent asks for a replacement link and posts a PNG to it
- **THEN** the item keeps its id and its content version goes up by one

#### Scenario: Writer deletes media
- **WHEN** a writer agent asks `edit_media` to delete an item
- **THEN** the call is refused for want of the admin role
