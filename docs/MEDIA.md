# Media

Screenshots, GIFs and short recordings attach to statements and concepts, and
documentation runs place them in the documents they write. Each item has its
own audience label, so an image never reaches a reader, token or document run
whose audience may not see it, even when the statement it illustrates is
visible.

## Items

A media item is one PNG, JPEG, WebP or GIF image, or one MP4 or WebM video. It
carries:

- **Alt text**, required: what the media shows. It is the description readers
  who cannot see the image get, and the only thing the AI knows about it: the
  documentation writer chooses images by it and the reviewer checks them
  against it. Mycelium does not look at the pixels.
- A **caption**, optional.
- Its **origin**: `uploaded` by a curator in the web app, `agent` when an agent
  uploaded it for a draft, or `captured` (reserved for automated capture; see
  [Out of scope](#out-of-scope)).
- Where it came from: **source URL** (the page it shows), **product version**
  or commit it was captured against, and **capture date**.
- Its **attachments**: any number of statements and concepts.

Size caps are in **Settings → Limits → Screenshots and recordings**: 5 MB for
images and 20 MB for video by default. A body larger than the larger of the
two caps is refused with 413 before the rest of it is read. A file within that
but over its own kind's cap, such as an 8 MB image under the defaults, is
refused with 415 once its type is known.

### What is accepted

The type comes from the bytes, never from the file name or the declared type.
Only the six formats above have a signature Mycelium recognises, so SVG, HTML,
PDF and anything else that can carry script is refused with 415.

Capture metadata is removed before the bytes are stored, by walking the file's
own structure:

| Format | Kept | Removed |
| --- | --- | --- |
| PNG | Chunks that draw the picture (header, palette, data, transparency, colour and animation chunks) | Text, time and EXIF chunks |
| JPEG | JFIF, ICC colour profile, Adobe colour transform, image segments | EXIF (with GPS), XMP, comments, other application segments |
| GIF | Frames, frame timing, the looping extension | Comments, plain text, other application extensions |
| WebP | Image chunks | EXIF and XMP chunks, and their flags |
| MP4 | Everything else, at the same offsets | `udta`, `meta` and `uuid` boxes, overwritten as `free` space of the same size |
| WebM | Everything else, at the same offsets | Tags, attachments, title and date, overwritten as `Void` of the same size |

Video is stripped in place so the sample offsets the container records stay
valid. A file whose structure does not parse is refused rather than stored as
sent.

### How the bytes are served

`GET /api/media/<id>/content` serves only the sniffed type, with
`X-Content-Type-Options: nosniff`, `Content-Security-Policy: default-src 'none';
sandbox`, `Content-Disposition: inline; filename="<id>.<ext>"`, and an ETag.
The browser therefore never treats the bytes as a page from the app's origin.
A caller scoped to an audience gets 404 for media that audience may not see,
so it learns nothing about internal media.

## Audience labels

An item's label is the set of audiences that may see it, decided by a curator
in the web app (`PUT /api/media/<id>/audiences`). It follows the statement
rules in [Audiences](AUDIENCES.md#labels):

- An unlabelled item is visible to internal audiences only. Uploads start
  unlabelled.
- A labelled item is visible to the audiences it grants and to every audience
  that includes one of them.
- Replacing the file of a labelled item keeps the label but flags it **content
  changed since decision**; **Confirm** keeps it as decided now.
- Only real writers and admins label; there is no AI labeller for media, so
  no media grant waits for confirmation.

The label of the statement an image is attached to does not widen the image's
own: an image is visible only to the audiences its own label allows, however
visible the statement is. A documentation run is offered an image only through
a statement or concept it could read, and only when the image's label allows
the run's audience. The check lives in `store.audience_labels.grants`, beside the statement
`visibility_clause`, so a change to how audiences nest changes both together.

## Storage

Items, their bytes, attachments and pending upload links live in
`mycelium-media.db`, apart from the substrate, so the knowledge database stays
small and a backup can leave media out. The bytes sit behind the `Blobs`
interface in `media_store`; moving them to object storage replaces
`SqliteBlobs` and nothing else.

Attachments name statements and concepts by id. Merging a statement or concept
moves its attachments to the survivor, and deleting one removes them; the item
itself stays in the library.

`mycelium export` includes media unless run with `--no-media`. A restore of an
archive without media leaves the instance's existing media untouched, and a
fresh restore from one starts without media. See
[Deployment](DEPLOYMENT.md#data-and-backups).

## Web app

The statement and concept pages list their media with alt text, caption,
origin, label and whether it is old. Writers upload there (the item is
attached to that page), edit alt text, caption and source details, replace the
file, label it, and detach it. **Curate → Media** is the library, filtered by
unattached, no alt text, unlabelled and old; there a writer also attaches an
item to a statement or concept by id, and an admin deletes it. Readers see
what their audience allows.

## Agents (MCP)

- `list_media` lists what is attached to one statement or concept, filtered by
  the caller's audience.
- `create_media_upload` returns a single-use upload link for an image or
  recording the agent captured. The agent POSTs the bytes there and cites the
  returned `media_id` as `{"kind": "media", "media_id": …, "claim": …}` evidence
  on the draft operation it illustrates (`set_operation_evidence`). The
  reviewer sees its alt text and caption. Applying the draft attaches the item
  to the statements or concept that operation wrote.

Why a link rather than base64 in the tool call is in
[MCP tools](MCP_TOOLS.md#uploading-media).

## In documents

After each read a documentation run makes, the writer is told which media is
attached to the statements (and, for the first message, the concept) it just
read and is visible to the run's audience: id, alt text and caption. Items
without alt text are not offered. The writer places one as

```markdown
![What the image shows](media:med_0123456789ab)
```

and the harness refuses a document that places media it was not offered, an
image with empty alt text, or a `media:` reference outside an image. A manual
edit may place any item the document's audience may see. A template can mark
an image slot as `{Image: what it should show}`; the shipped how-to template
has one in its steps.

The reviewer is shown what each placed image shows and fails conformance for
alt text that does not say what the image shows or an image that does not fit
its text, and exposure for alt text or a caption that reveals what the
audience must not get.

The document view renders a `media:` image from Mycelium's content route, so
each reader's own audience check applies; any other image in a document is
shown as its alt text. Publishing to GitHub commits each image beside the
Markdown as `<file stem>-media/<id>-v<version>.<ext>` and links it by that
relative path; reading the published copy maps the links back. Publishing
refuses a document placing media that was deleted or that its audience may no
longer see.

## Out of date

An item is **old** when it was captured (or, without a capture date, uploaded
or replaced) longer ago than **Flag media older than (days)** (365 by
default), or when it records a product version other than **Current product
version**, if that is set. The library's **Old** filter and the
[knowledge health](KNOWLEDGE_HEALTH.md) count list them.

A document is out of date when an image it places was replaced after the
revision was written, was deleted, or is no longer visible to its audience.
Its revision brief names the image and what to do.

## Out of scope

Automated capture through a browser (the `captured` origin is its seam),
automatic GIF recording, AI labelling or description of images, and object
storage are not built.
