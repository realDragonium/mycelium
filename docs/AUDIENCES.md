# Documentation audiences

An audience is who a document is written for. Each writing profile writes for
exactly one audience, and a documentation run reads only the statements that
audience may see. A user or token scoped to an audience reads through the
same boundary; see [Scoped users and tokens](#scoped-users-and-tokens).

## Audiences

Open **Settings → Audiences**. An audience has a name, a scope (internal or
external) and a description of who the reader is, what they need and what they
must not get. Four ship: internal technical, internal non-technical, external
technical and external non-technical. Administrators create, edit, retire and
restore them; every edit keeps history. An audience a profile still writes for
cannot be retired, and the last internal audience can be neither retired nor
made external.

An audience can include other audiences: it may see everything they may see,
directly or through the audiences they include. The seeded audiences start
with external technical including external non-technical, internal
non-technical including external non-technical, and internal technical
including all three others; administrators change this in the audience's
**Includes** field. An external audience can include only external audiences,
and no audience can include itself through others. Instances seeded before
includes existed get the seeded includes once on startup, on seeded audiences
whose saved text predates the field.

A profile without a chosen audience writes for the default: internal technical
while it exists, otherwise the first internal audience. Only an administrator
can change the audience of an existing profile. If a profile's chosen audience
is retired, the profile is not ready and its runs refuse rather than widen.

## Labels

Every statement carries a label: the audiences it grants, who decided (the AI
labeller or a curator), why, and when. A statement is visible to an audience
when its label grants that audience or any audience it includes, so a
statement granted to external non-technical is visible to every seeded
audience. A statement without a label is visible to internal audiences only,
so an unlabelled statement never reaches an external document.

The **audience labelling** action decides labels. It has its own model
(**Settings → Models**), instructions (**Settings → Prompts**) and limits
(**Settings → Limits**: batch size, tokens, timeout, retries, and whether new
statements are labelled automatically). It reads statements in batches, each
with the concepts it mentions and their descriptions, plus every audience's
description and includes, and returns the most restricted audiences each
statement fits and a short reason; the audiences including them see it
without being named. Audience ids it invents grant nothing.

- New statements are queued when they are written; a background worker labels
  them while automatic labelling is on.
- Changing a statement's text drops its AI label and queues it again with the
  previous label; see [Edits keep their audiences](#edits-keep-their-audiences).
- A failed batch is retried with backoff; after five failures the statement
  waits for the next backfill. Its statements stay unlabelled meanwhile.
- **Label unlabelled statements** queues every unlabelled statement and runs
  even with automatic labelling off, until no queued statement has attempts
  left; a failed batch or a budget pause delays it but does not end it. **Relabel AI labels** also queues AI
  labels. Both show progress and the cost so far, also after leaving and
  reopening the page or restarting the server (`backfill` on
  `GET /api/audiences/labelling`). Progress is read from the queue: it counts
  from when the oldest waiting statement was queued, including statements
  queued by edits meanwhile, and is gone once the queue is empty.
- A curator sets a label on the statement page; the AI never replaces it.
  **Hand back to AI** removes the curator label and queues the statement.
- Changing the text of a statement with a curator label keeps the label but
  flags it **Text changed since decision**, on the statement page and as a
  label-state filter in **Settings → Audiences**. **Confirm** keeps the label
  as decided now; **Hand back to AI** removes it and queues the statement.
- Deleting or merging a statement deletes the removed statement's label. A
  merge keeps the surviving statement's text, so its label stands.

### Edits keep their audiences

An edited statement is relabelled with its previous text and the audiences its
previous label granted (waiting grants included). The labeller keeps those
audiences unless the edit changes what may be revealed. When its new label
takes the statement away from an audience that could see the previous one, it
must give a narrowing reason; without one the previous audiences are kept and
the label's reason says so. A narrowed label records the previous audiences,
the audiences that lost the statement and the reason, which the statement page
and the statement list in **Settings → Audiences** show. Several edits before
the relabel keep the label from before the first.

**Settings → Audiences** shows, per audience, how many statements it can see
and how many statements are unlabelled, and lists statements by audience,
visibility and label state (including **Waiting for confirmation**).

## Confirming external grants

Most AI grants to external audiences are right; the costly error is the rest,
an internal detail shown to customers. So while **Confirm external grants**
is on (**Settings → Limits → Audience labelling**, on by default), an AI
grant that would make a statement visible to an external audience that could
not see it before waits for a curator. That covers new statements, changed
text (whose AI label is dropped) and relabelling. Grants to internal
audiences, and external grants the statement already had, apply at once; an
external audience the AI no longer grants is withdrawn at once.

A waiting grant grants nothing: documentation runs, planning, scoped Ask and
MCP, and every visibility count treat the statement as hidden from that
audience, and from external audiences that see it only by including it, until
a curator confirms. Confirmation applies per granted audience: confirming
external non-technical shows the statement to external technical too. So that
internal readers do not lose it meanwhile, the label grants the narrowest
internal audiences that include the waiting one (and keeps any audience that
already saw the statement). The label stores the waiting grant beside the
granted audiences, with the AI's reason.

**Settings → Audiences → Waiting for confirmation** lists, per external
audience, the waiting grants grouped by the concept each statement names (the
one with most waiting statements), with the statement, the AI's reason and its
concepts. The count shows on the card and on the Audiences link. A curator,
who needs a real writer role like any label override, can:

- **Confirm** a grant: the statement becomes visible to the audience, and the
  label records who confirmed it and when. The label stays an AI label, so a
  later text change withdraws the grant until it is confirmed again.
- **Reject** a grant: the label becomes a curator label without that audience,
  so the AI does not grant it again. **Hand back to AI** undoes that.
- **Confirm all** or **Reject all** for a concept group.
- **Review a sample**: draw a random sample of the audience's waiting grants
  (50 by default), stratified by concept group in proportion to its size.
  Deciding each sampled grant shows the sample's precision, the share
  confirmed. **Accept the rest** confirms every grant still waiting, and
  records on each that it was accepted after a sample of that size and
  precision. Rejections in the sample stay rejected. Below the warning
  threshold (90% by default) the card warns and suggests improving the
  audience description or labelling instructions and relabelling instead.

The statement page shows a waiting grant as **Waiting for confirmation**, with
Confirm and Reject. The label-state filter finds every statement with a
waiting grant.

Changing a statement's text withdraws its waiting grants. Deleting or merging
a statement removes its label, waiting grants included, and backups carry
them. A confirmation counts as newly visible for documentation planning. A
document citing a statement whose grant was withdrawn is out of date, but
automatic maintenance leaves it while the grant waits for a curator, so an
edit to a confirmed statement is not read as the statement being hidden; a
rejection lets maintenance act.

Turning the switch off applies the AI's external grants at once again. Grants
already waiting stay waiting until a curator decides them.

## Media

Screenshots and recordings carry their own label, decided by a curator, with
the same rules: unlabelled media is internal only, and replacing a labelled
item's file flags the label to confirm. An image is shown to a reader, token or
run only when its own label allows that audience, whatever the label of the
statement it is attached to. See [Media](MEDIA.md#audience-labels).

## What a documentation run sees

The boundary is enforced in the substrate reads, not in the prompt. While a
run's read tool executes, the run's connection sees only:

- statements the audience may see;
- statement links whose ends, and every statement in their condition, it may
  see;
- concepts that a visible statement mentions.

The writer is offered only media attached to what it read whose own label
allows the audience, and publishing refuses a document placing media the
audience may not see.

Concept descriptions and concept links are curator prose without labels, so
they fail closed like an unlabelled statement: internal audiences see them,
external audiences do not. External audiences also see only the names visible
statements were matched through, so an internal alias or codename of a
visible concept stays hidden.

Semantic search ranks only visible statements. The visible set is fixed when
the run starts, and a document citing anything outside it is refused. The
writer and the reviewer are given the audience description, and the reviewer
fails exposure when the document gives the audience something its description
excludes; the profile's disclosure rules still apply as a second line of
defence.

Each run records its audience with the profile snapshot. The document library,
the document view and the generate form show it. When a statement a document
cites is relabelled so that this audience may no longer see it, the document
is out of date with the reason "no longer visible to this audience", and its
revision is briefed to drop what rested on it, so an external document does
not keep knowledge that has become internal. The same holds for an image the
document places.

## Scoped users and tokens

An admin can scope a user, an MCP token or an OAuth connection to an audience
(see [Managing users](USERS.md#scoping-to-an-audience)). Without an audience a
principal has its role's full access. A scoped principal reads exactly what a
documentation run for that audience reads, and nothing else:

- Its role is clamped to reader. Writes, drafts, gap reports and admin actions
  are refused whatever its role.
- It may call only the read tools (the ones Ask and documentation runs use,
  plus `ask`, `list_generated_documents`, `get_generated_document` and
  `list_media`) and a short list of read routes: `/api/me` and its own tokens,
  `/api/data`, `/api/substrate-counts`, `/api/entity-positions`, `/api/history`,
  the document library and media content (`/api/media/<id>/content`, 404 for
  media its audience may not see). Every other route and tool answers 403, including any
  added later until it is added to the allowlist in `principal_audience`.
- Each read runs inside the boundary above. Ask runs its whole loop inside it,
  so it neither reads nor cites a statement the audience may not see.
- It may read a generated document written for its audience, or for an
  audience at least as restricted: an external reader never gets a document
  written for an internal audience, and every statement the writing audience
  may see must be visible to it. Every statement the document cites must also
  still be visible. The out-of-date reasons, which quote changed statements,
  are left out.
- History lists only events on statements, concepts and names it may see now,
  without their before and after values.

A principal scoped to an audience that is later retired reads nothing until an
admin rescopes it.
