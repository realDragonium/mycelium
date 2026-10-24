---
name: mycelium-code-curation
description: Work the Mycelium curation queue from inside a product's repository. Claims a small batch of knowledge-health work (isolated statements, statements naming no concept, rephrase requests, knowledge gaps), checks each item against the product's code, proposes links, concept names, rephrases or corrections through a drafter's draft with per-operation code evidence, submits the draft and releases every item with its outcome. Use when an agent with code access (Claude Code in the product repo, or a CI job) is asked to curate, connect or check Mycelium knowledge against the code, or to work the curation queue. Needs a drafter token. Content rules come from mycelium-authoring.
---

# Curating Mycelium from the product's code

The connect pass sees only the knowledge base; you also see the code. The
server hands you claimable items (`claim_curation_work`), you check each one
where the product implements it, and you propose what the code supports
through your draft, with the code as evidence on each operation. The
server's draft reviewer weighs that evidence; nothing lands without review.

Content decisions (kinds, phrasing, link types, direction, `when`) follow
`mycelium-authoring` §5 and §6. This skill adds the queue, the evidence and
the decision rules for an item.

## Connect

Use a token with the **drafter** role (**Settings → Account & tokens**),
never a writer's: a drafter's writes go to its draft, a writer's land live.

- Claude Code in the product repo: `claude mcp add --transport http mycelium
  https://<host>/mcp --header "Authorization: Bearer myc_…"`.
- A CI job: every tool is also an HTTP route taking its arguments as JSON
  (`GET` for a tool without arguments, such as `list_my_drafts`):

  ```sh
  curl -sX POST "$MYCELIUM_URL/claim-curation-work" \
    -H "Authorization: Bearer $MYCELIUM_TOKEN" -H "Content-Type: application/json" \
    -d '{"kind": "isolated", "limit": 3}'
  ```

Check the tool list: `claim_curation_work` present and `list_drafts` absent
means drafter. `list_drafts` present means writer or admin: stop and ask for
a drafter token.

Then `list_my_drafts()`. Every write joins your one open draft (per account,
or per MCP session when the client keeps one). If an open draft already
holds unrelated operations, stop and ask the operator whether to submit it
first. Run one job per drafter account at a time.

## Workflow

1. **Claim a small batch.** `claim_curation_work(kind, limit=3)`. `kind` is
   `isolated`, `unnamed`, `rephrase` or `gap`. Keep the batch small enough to
   finish within the 30-minute lease. Each item has `id`, `text`, the
   `statement` it is about (with the concepts it names) and five
   `neighbours`; the batch has `link_types` (each type's `description`, and
   a `direction` on types limited to certain statement kinds) and
   `expires_at`. Read `link_types`: it is the menu, and its directions are
   enforced.
2. **Find the behaviour in the code.** Search the repository for the
   statement's terms, the UI copy, the setting name or the event. Read the
   handler, the job or the check that implements it, and what runs before and
   after it. Read the neighbours (and other candidates from
   `search_statements`, `grep_statements` and `search_entities`) with
   `get_statements` to see their links.
3. **Decide** (rules below), and write at most what the code supports.
4. **Attach evidence to each write.** Each write returns a receipt with
   `draft_id`, `operation_ref` and `revision`. Call
   `set_operation_evidence(draft_id, operation_ref, evidence,
   expected_revision)` with the latest revision you were given (each write
   and each evidence call raises it).
5. **Submit** once the batch is done: `submit_draft(draft_id)`.
6. **Release every claimed item**:
   `release_curation_work(item_ids, outcome, draft_id, reason)` with
   - `proposed` and the `draft_id`, for items the draft proposes something
     for, including an item at the other end of a link you proposed;
   - `no_link` and a `reason` (at most 300 characters) naming what you
     checked;
   - `skipped`, for items you did not get to. They are offered again.

   Group items by outcome; one call per outcome.

**Leases.** `claim_curation_work(kind, limit=0)` renews every item of that
kind you hold without claiming more; do it when `expires_at` is near. If
you must stop early, release what you hold as `skipped` rather than letting
the lease run out. An item whose lease ran out can still be released
until any agent's next claim clears expired leases (or an admin frees your
claims); after that its release is refused as not held by you, and it may
be someone else's. `renewed` in a `limit=0` claim lists what you still
hold.

## Deciding an item

| Kind | Look for | Propose |
|---|---|---|
| `isolated` | The code that runs before, after, around or because of it | `add_links` to the statements that code connects it to |
| `unnamed` | The concept the code and UI call it | `upsert_name(text, entity_id)` for wording of an existing concept; `upsert_entity(name, description)` when no concept fits and the name appears word for word in the statement |
| `rephrase` | What the code actually does, to state one claim in the right kind | `patch_statement(id, text=...)` on the item's `statement` (the item id is the gap's) |
| `gap` | The missing fact | The statements, links or concepts that close it (`mycelium-authoring` §8) |

Rules:

- **One look covers the whole statement.** A release settles the statement
  for every list, not only the kind you claimed. If an `isolated` item's
  `statement.concepts` is empty, decide its concept too; if an `unnamed`
  item has no links (`get_statements`), decide its links too.
- **Link only what the code connects.** A call, an enqueued job, a guard, a
  shared setting or a branch is evidence; similar wording is not. When in
  doubt, `no_link`.
- **One link per `add_links` call**, so each link carries its own evidence.
- **Direction follows the type**, as `link_types` and `mycelium-authoring` §6
  describe it: read the edge aloud as "source `link_type` target" and flip it
  if it reads backwards. A type with kinds only goes between those kinds.
- **A condition is a `when` on the link**, naming an existing `state`, never
  words added to a statement.
- **`no_link` is a result.** Say what you checked: "export email is sent by
  the billing job; no neighbour describes that job".

## Evidence

Each operation takes up to five items:

```json
{"kind": "code", "path": "app/billing/exports.py", "lines": "88-97",
 "commit": "4e1c2a9", "excerpt": "…", "claim": "Finishing the export job enqueues the download email"}
```

- `path` relative to the repository root, `lines`, and the `commit` you read
  (`git rev-parse --short HEAD`); a `url` instead for a UI page or doc.
- `excerpt`: the fewest lines that show the claim, at most 1,500 characters.
  Never secrets, tokens, credentials, connection strings, environment
  values, customer data or personal data; cut them out or pick other lines.
  Do not paste whole files or code the claim does not need.
- `claim`: one line saying what the excerpt shows about this operation.

A link with a concrete excerpt can be accepted on that basis; a link without
evidence is judged more strictly.

## When the code contradicts the knowledge base

The code wins, but say how you know.

- **A statement says something the code does not do** (a different limit, a
  role that cannot do it, a step that no longer exists): propose the
  correction with `patch_statement(id, text=...)` and evidence of the actual
  behaviour. Do not link anything to the wrong version. Phrase it by
  `mycelium-authoring` §5: the phrasing check runs when the draft is
  applied, and one refused statement stops the whole draft.
- **You cannot settle it from the code** (a feature flag, a plan or edition
  difference, behaviour outside this repository), or the fix is more than a
  rephrase: `report_knowledge_gap(text, statement_id=...)`, with the file and
  line in the text, and release the item as `no_link` with the gap id in the
  reason.

## Worked example

Claim `claim_curation_work("isolated", limit=2)`. Items (invented):

- `stm_mail`: event "The server emails the member a link to download the
  invoice export.", naming the concept *invoice export*; neighbours include
  `stm_done` event "The invoice export job finishes." and `stm_ttl` rule
  "An invoice export link is valid for 24 hours."
- `stm_sso`: state "The workspace enforces single sign-on.", naming
  *single sign-on*.

**`stm_mail`.** `app/billing/exports.py:88-97` shows `finish_export()`
calling `send_export_ready_email.delay(...)` after the file is stored, a
separate job on its own queue. `link_types` says `triggers` is a separate
downstream process; "the export job finishes triggers the email" reads
right. `add_links(links=[{"from_id": "stm_done", "to_id": "stm_mail",
"link_type": "triggers"}])`, then `set_operation_evidence` with that excerpt
and the claim "Finishing the export enqueues the download email".

Line 91 also reads `EXPORT_LINK_TTL = timedelta(hours=72)`: `stm_ttl` is
wrong. `patch_statement("stm_ttl", text="An invoice export link is valid
for 72 hours.")` with that line as evidence.

**`stm_sso`.** `auth/sso.py` checks it at sign-in, but no statement
describes that sign-in check yet, and its neighbours only share the words.
Nothing to link to: `no_link`.

Then `submit_draft(draft_id)`,
`release_curation_work(["stm_mail"], "proposed", draft_id)`, and
`release_curation_work(["stm_sso"], "no_link", reason="Enforced in
auth/sso.py at sign-in; no statement describes that check yet")`.

## Report

End with the draft id, what it proposes per item, the `no_link` reasons, the
gaps you reported and anything you released as `skipped`.
