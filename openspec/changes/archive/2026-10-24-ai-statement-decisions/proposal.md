## Why

Some decisions about statements, concepts, links, aliases and audience labels
still wait for a person: duplicate candidates, concepts without a
description or without statements, curator labels whose statement changed,
confirmed grants an edit kept, the reviewer's questions while review runs on
a server model, rejected drafts and resolved contradictions filed as gaps,
server refusals under an external reviewer, and alias suggestions whose
names or source changed. AI, the server's model or an outside agent, should
be able to make each of them through the queues and review paths that
already exist. People keep the definitions that bound the agents: audiences,
writing profiles, prompts and admin operations. Every new automation is off
by default.

## What Changes

- The curation queue gets `duplicate` (a statement or concept pair),
  `undescribed` and `unused` (concepts) items. A duplicate is merged through
  the agent's draft, or released `not_applicable`, which for concepts
  records the names workspace's dismissal as the agent's. Gap and rephrase
  items carry the draft their gap is about.
- An AI curation pass on the Connecting statements model works those lists
  as an in-process curation agent, behind settings that are off by default:
  `connect_automatically`, `decide_duplicates`, `describe_concepts` and
  `act_on_gaps`. Its proposals are ordinary submitted drafts; what it cannot
  ground stays for outside agents and people.
- Draft review settings `answer_questions` (the draft-review model tries a
  grounded answer from the knowledge base and the draft's evidence) and
  `reject_refused` (under an external reviewer a server refusal rejects the
  draft with its reason). While the reviewer decides alias suggestions, a
  suggestion whose source changed is rejected and one whose names changed is
  refreshed and reviewed again.
- Audience labelling setting `ai_label_decisions`: the grant reviewer also
  keeps or hands back curator labels whose statement changed, and confirms
  or narrows confirmed grants an edit kept.
- Evidence can cite a knowledge-base statement or a draft's review evidence.

## Impact

- Specs: knowledge-health, drafts-and-review, audiences, agent-tasks.
- Code: curation queue and the new curation pass, draft review runs, answer
  attempts and alias suggestions, audience review, evidence, settings, the
  knowledge health, draft and settings screens. No schema change.
- Docs: knowledge health, draft review, audiences, agent tasks, names and
  aliases, alias suggestions, MCP tools, web app; the curation, code
  curation and agent-tasks skills.
