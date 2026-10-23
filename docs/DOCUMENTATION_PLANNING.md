# Documentation planning

Open **Documents → Plan**, choose a writing profile and select **Plan
documentation**. The planner proposes which documents the profile's audience
needs; nothing is written until you approve an item.

## What the planner reads

One model call per plan, through the **documentation planning** action. It has
its own model (**Settings → Models**), instructions (**Settings → Prompts**) and
limits (**Settings → Limits**: tokens, timeout, retries, how many concepts and
key statements the overview carries, how many items a plan keeps, the coverage
and re-plan thresholds, and how many items one batch approval starts).

The call gets the profile's audience description, its templates, its existing
documents (type, concept, out-of-date or not) and an overview of what the
audience may see: concepts with their counts of visible statements by kind and,
for internal audiences, their parent concept and description, plus the most
connected capability and procedure statements. The overview is read through
the same boundary as a documentation run ([Audiences](AUDIENCES.md)), so the
planner never sees a statement, name, description or concept link the audience
may not. External audiences therefore get no concept hierarchy or
descriptions.

## What a plan keeps

Each item is `create` or `update` (a document whose scope should change), with
a title, template, concept, rationale, priority and the statements it would
mainly draw on. The model proposes; Mycelium keeps an item only when:

- its template belongs to the profile and its concept is in the overview;
- an update names one of the profile's documents;
- it draws on at least one statement the audience may see (ids it may not see
  are removed, and an item about a concept is topped up from that concept's
  statements);
- it is not a document the profile already has, another item of the same plan,
  or a proposal dismissed before.

A `create` about a concept that already has a document of that template becomes
an update of it. The plan shows how many proposals were set aside and why.

Two lists need no model and are always current: **Out-of-date documents**
(approve to start a revision briefed with the changed statements) and
**Concepts without a document**, concepts with many visible statements and no
document of the profile about them.

## Reviewing

**Approve** starts the same run as **Generate** (`request_documentation` with
the concept), or a revision for an update; the item then shows its run's
status and links the document when it is written. When that run wrote
nothing, **Retry** starts it again and the item follows the new run; when the
review refused it, **Retry with these notes** also briefs the writer with the
review's findings (see [Documentation models](DOCUMENTATION_MODELS.md)). Select several items to
approve them together, up to the batch limit (2 by default); each is its own
documentation run and counts against the active-run limit. **Dismiss** is
remembered per profile, so a later plan drops the same proposal. A dismissed
out-of-date document comes back after its next revision.

Re-planning is manual. When enough statements have become visible to the
audience since the last plan (written after it, or for an external audience
labelled after it), the page says so.
Plans, items and dismissals live with documentation runs in
`mycelium-drafts.db` and are included in instance backups. A plan running
when the server restarts is marked failed.
