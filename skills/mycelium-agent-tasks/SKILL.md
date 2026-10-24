---
name: mycelium-agent-tasks
description: Do the model work a Mycelium server queues for outside agents when an action is set to External agent instead of a server model. Claims tasks with claim_agent_task, writes documentation from audience-scoped reads (read_for_agent_task), reviews another agent's document, proposes a writing profile's documentation plan, labels statements' audiences, turns ingested text or unconnected statements into a draft, or finds concept aliases, submits the result with submit_agent_task, fixes refused submissions from their findings and releases what it cannot finish. Use when asked to work Mycelium's agent task queue, or to write documentation, label audiences, ingest, connect or discover aliases for a server that has no provider key. Needs a real writer or admin token.
---

# Working Mycelium's agent task queue

With **External agent** selected for an action in **Settings → Models**, the
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
   `audience_labelling`, `ingest`, `connect` or `alias_discovery`. An empty `tasks` list means nothing is waiting.
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
needs from the overview in `brief.input`, most valuable first. Cite only the
statements and templates the overview lists. Items that name what the
audience may not see, templates the profile lacks or documents it does not
own are dropped.

**`audience_labelling`.** Label every statement in `brief.input` exactly
once, with audience ids from the brief and a reason. The server applies them
as its own labeller's are applied, and new external grants may wait for a
curator's confirmation.

**`ingest` and `connect`.** Follow `brief.instructions` as the ingest or
connect model would: reconcile every candidate with reads, search around it,
then submit the `emit_draft` input. Each op's `payload_json` is a JSON string.
A submission before a reconcile read and a later search around it is refused
with a `floor` finding. The server builds the draft from what you submit and
sends it to review; nothing is written live.

**`alias_discovery`.** Propose only aliases the selected statements in
`brief.input` show, each with a quote from its statement. Evidence from
any other statement is refused.

## Do not

- Do not copy text from outside the reads into a document; the reviewer
  and the citation check refuse what the knowledge base does not support.
- Do not claim more tasks than you can finish within the lease.
- Do not resubmit unchanged after a refusal; each refusal uses a retry.
