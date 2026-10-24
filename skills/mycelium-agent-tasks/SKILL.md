---
name: mycelium-agent-tasks
description: Do the model work a Mycelium server queues for outside agents when an action is set to External agent instead of a server model. Claims tasks with claim_agent_task, writes documentation from audience-scoped reads (read_for_agent_task), reviews another agent's document, proposes a writing profile's documentation plan, approves or dismisses another agent's plan items, labels statements' audiences, confirms or rejects another labeller's waiting external grants, turns ingested text or unconnected statements into a draft, finds concept aliases, or reviews a submitted draft (approve, approve with corrections, reject or ask a person), submits the result with submit_agent_task, fixes refused submissions from their findings and releases what it cannot finish. Use when asked to work Mycelium's agent task queue, or to write documentation, label audiences, ingest, connect, discover aliases or review drafts for a server that has no provider key. Needs a real writer or admin token.
---

# Working Mycelium's agent task queue

With **External agent** selected for an action in **Settings → Models** (for
draft review, in **Settings → Draft review**), the
server does not call a model for it. It queues a task, and you do the
model's part. The server still decides what the work needs, what you may
read and what is saved: your result passes the same checks its own model's
would, and a refusal comes back as findings for you to fix.

## Connect

Use a token with the **writer** or **admin** role. A drafter or reader token
is refused: what you submit is saved as the server's
own output, not drafted for review. `claim_agent_task` in your tool list means
the token can claim.

## Workflow

1. **Claim one task.** `claim_agent_task(kind, limit=1)`. `kind` is
   `documentation`, `document_review`, `documentation_planning`,
   `plan_review`, `audience_labelling`, `audience_review`, `ingest`,
   `connect`, `alias_discovery` or `draft_review`. An empty `tasks` list means nothing is waiting; `note`
   says when waiting reviews were held back because they are your own work.
   You hold the task for 30 minutes (`expires_at`); calling
   `claim_agent_task(kind, limit=0)` renews it. Each task has:
   - `brief.instructions`: the system prompt the server's model would get.
     Follow it as your instructions for this task: it holds the writing
     profile's guidance, exposure rules and template, or the labelling and
     planning rules.
   - `brief.input`: the first message the model would get, with the request
     and what the server already read for it.
   - `read_tools` (documentation, ingest and connect), `brief.result` and
     `brief.result_schema`: what you may read and what to submit.
   - `findings`: why the last submission was refused, when one was. Fix
     those first.
2. **Read** (documentation, ingest and connect). Call
   `read_for_agent_task(task_id, tool, arguments)` with a tool from
   `read_tools` and its arguments. Only these reads count: do not use other
   Mycelium reads for the task. A documentation task's reads run inside the
   audience the document is for: what that audience may not see is not
   returned, and you may cite only statements a `read_for_agent_task` call or
   the brief's input returned. When knowledge the document needs is missing, call
   `report_knowledge_gap` rather than inventing it.
3. **Submit.** `submit_agent_task(task_id, result)`, with `result` shaped
   as `brief.result_schema`.
   - `accepted`: saved. Done.
   - `refused`: fix every finding and submit again. `retries_left` says how
     many tries remain before the work closes as failed.
   - `in_review`: another agent reviews the document. If the review fails,
     the task returns to the queue with the review's findings.
   - `failed`: the work is closed; the run, plan or labels record why.
4. **Release what you cannot finish.** `release_agent_task(task_id,
   reason)` puts the task back for another agent, sooner than the lease
   running out.

## By kind

**`documentation`.** Write the document `brief.input` asks for, in the
profile's template, for `brief.audience`. Every claim must come from a
statement you read. List those statements in `statement_ids`. A refusal
names the statements the run never read or the audience may not see, and
any internal vocabulary or media the document may not carry.

**`document_review`.** You are never offered a review of your own document.
Judge the document in `brief.input` against `brief.instructions` only:
exposure (does it tell the audience something it must not get) and
conformance (does it follow the template). Fail a check only with a
concrete finding saying where and what is wrong. Your review is recorded
either way; a failed one sends the document back to its writer.

**`documentation_planning`.** Propose the documents the profile's audience
needs from the overview in `brief.input`, most valuable first. Place the
`uncovered_statements` (visible, but cited by no document of the profile)
a reader needs: list one in the `statement_ids` of an `update` of the
existing document it belongs in (`existing_documents` gives each one's
opening), or group it with related ones in a `create`. Cite only the
statements and templates the brief lists. Items that name what the audience
may not see, templates the profile lacks or documents it does not own are
dropped.

**`plan_review`.** Decide every item in `brief.input`: `approve` starts
writing or revising that document, `dismiss` is remembered so it is not
proposed again. You are never offered the review of a plan you made. Approve
what a reader of the audience needs, its statements support and nothing
already covers; dismiss duplicates, documents for another audience and
thinly supported ones. An `out_of_date` item updates a document whose cited
statements changed. Submit `{"decisions": [...]}` with `item_id`, `decision`
and a one- or two-sentence `reason` per item, each item once. A missing,
repeated or unknown item is refused.

**`audience_labelling`.** Label every statement in `brief.input` exactly
once, with audience ids from the brief and a reason. The server applies them
as its own labeller's are applied, and new external grants may wait for a
curator's confirmation.

**`audience_review`.** Another labeller's grants are waiting to show
statements to external audiences. For each `statement_id` and `audience_id`
pair in `brief.input`, `confirm` only when the audience's description allows
the statement, otherwise `reject`; when in doubt, reject. Give every decision
a short reason (at most 500 characters): it is recorded on the label as a
curator's decision would be. Decide every pair exactly once. You are never
given grants you labelled.

**`ingest` and `connect`.** Follow `brief.instructions` as the ingest or
connect model would: reconcile every candidate with reads, search around it,
then submit the `emit_draft` input. Each op's `payload_json` is a JSON string.
A submission before a reconcile read and a later search around it is refused
with a `floor` finding. The server builds the draft from what you submit and
sends it to review; nothing is written live.

**`alias_discovery`.** Propose only aliases the selected statements in
`brief.input` show, each with a quote from its statement. Evidence from
any other statement is refused.

**`draft_review`.** You are the reviewer of the draft in `brief.input`, and
never of one you created. `brief.instructions` is the internal reviewer's
contract; follow it. Trust the producer on what the product does and judge
how the draft fits the existing knowledge the input supplies: duplicates,
contradictions, link type and direction, missing links to live neighbours,
entity variants and the `operation_findings` the server would refuse.
Submit `{"parts": [...]}` with one assessment per part (`brief.parts`; a
multi-part input is headed `=== PART i OF n ===`):

- `good`: the draft fits as submitted. No corrections, questions or
  contradictions.
- `changes_suggested`: it fits once you correct it. Correct rather than
  reject when at most twelve precise corrections (edit, add a link,
  drop a link, drop a statement, strike or append an operation), each changing one thing,
  make it fit. Indices and `@` references name the draft as submitted. List a
  live statement you correct because the draft supersedes it under
  `contradictions`.
- `reject`: it cannot be made to fit with twelve corrections, or it adds
  nothing the knowledge base lacks. Say why in `rationale`; a gap is filed
  with it.
- `needs_context`: only when the supplied knowledge cannot settle the fit and
  a person's answer would, such as whether a new concept is a live one under
  another name. Ask specific `questions`; they become a knowledge gap, and the
  draft is reviewed again with the answer.

When `brief.alias_decisions` is true, also return `alias_decisions` in each
part: for every pending `alias_suggestion` operation in it, `accept` only when
the suggestion's source text establishes that the alias names the concept,
otherwise `reject`, each with a `quote` copied exactly from that source text
and a short `reason`. Every pending suggestion needs one decision unless you
ask a person (`needs_context`). A suggestion whose names or source changed
since stays for a person.

`brief.earlier_review` is the previous review, with its corrections when it
was held for a curator: check them, keep the right ones and drop the wrong
ones. `brief.mode` and `brief.auto_apply` say what your verdict does: in
`review-and-apply` it is applied, rejected or held as the internal
reviewer's would be, and in `review-only` it is advice and a person decides.
A refusal names the label, correction or reference that failed.

## Do not

- Do not copy text from outside the reads into a document; the reviewer
  and the citation check refuse what the knowledge base does not support.
- Do not claim more tasks than you can finish within the lease.
- Do not resubmit unchanged after a refusal; each refusal uses a retry.
