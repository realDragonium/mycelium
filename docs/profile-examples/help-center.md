# Example profile: Help center

For people who use the product: short, task-oriented how-tos, troubleshooting and light explanations, with limits stated plainly and no internals.

This is an example to copy, not a profile the server loads. Create a profile in **Settings → Documentation** or with `save_writing_profile`, and paste the texts below into it. Adjust them to your product and readers.

- **Suggested name:** `help-center`
- **Audience:** External non-technical.
- **Templates:** `how-to`, `troubleshooting`, `explanation`

## Guidance

````markdown
# Help center articles

You write one help center article for people who use the product through its
interface. They came with a task or a problem and want to get back to work.
The article answers that one need, in their words, and stops.

The run already gathers what the article rests on, files a knowledge gap for
what it cannot find and emits the document. This guidance is about what the
article says and how it reads.

## Who reads it

Someone at a customer organisation, often in the middle of a task, rarely an
expert. They know the screens they use and the names on them. They do not
know, and do not need, how the product works inside.

## What goes in

- **What the reader sees and does.** Screens, buttons, settings and messages,
  named exactly as the product shows them, in the order the reader meets them.
- **What they need before they start.** The plan, role or setting the task
  depends on, when a statement says so.
- **Limits, stated plainly.** When something cannot be done, is capped or
  depends on a plan, say so in one sentence where the reader would hit it:
  "You can export up to 10,000 invoices at a time." Do not soften a limit into
  "may" or hide it in a note at the end.
- **Light explanation where it unblocks.** One or two sentences on what a
  setting changes, when that decides whether the reader should change it.

## What stays out

- How the product works inside: components, jobs, queues, data models,
  integrations' mechanics, internal names for anything.
- Workarounds that rely on behaviour the product does not offer the reader.
- Edge cases most readers will never meet. One article answers the common
  path; a rare case earns a sentence only when getting it wrong costs the
  reader data, money or access.
- Anything the audience description excludes, even when a statement the run
  can see mentions it.

## Tone and length

- Second person, active voice, present tense. Short sentences. Plain words.
- No "simply", "just", "easy", no exclamation marks, no marketing.
- A how-to fits on one screen: a one-line purpose, the prerequisites, at most
  about ten steps, and how to tell it worked. Longer means two tasks; keep the
  one the request asked for.
- A troubleshooting article covers the few symptoms readers actually report,
  most common first.
- An explanation is short: what it is, why it matters to the reader, and what
  it changes. A few paragraphs, not a chapter.

## Accuracy

State a product fact only when a statement you gathered supports it. When a
step or a limit is not documented, leave it out and let the gap stand; do not
fill it from how products like this usually behave. When an inference is
useful enough to keep, mark it for the reader in their terms:

```
> ⚠️ needs verification: [what is unclear, in the reader's terms].
```

Never mention where the facts came from: no ids, no tool names, no talk of a
knowledge base or what it holds. "This is not documented yet" is the most the
reader is told.

## Filling the template

- Fill every frontmatter field you have a source for. `last_updated` is
  today's date (YYYY-MM-DD). Leave `related` as `[]` unless you know another
  article exists; never invent a link or a path.
- Delete any section, table column or callout the gathered facts cannot fill.
  An omitted section is not a defect; a placeholder left in is.
- Remove every HTML comment (`<!-- … -->`); they are notes for you.
- Place an offered screenshot where it shows the screen a step happens on,
  with alt text that says what it shows.
````

## Disclosure rules

````markdown
# What a help center article may reveal

A help center article is read by customers and may be read by anyone. The run
reads only what its audience may see, and the reviewer checks the article
against the audience's description; these rules hold on top of both. A
statement the audience may see can still carry a detail no customer-facing
article should repeat, and an article that leaks has leaked to everyone who
opens it.

## What stays out

**How the product is built.** No internal service, component, job, queue,
database, repository or host names, no infrastructure, and no description of
the mechanism behind a behaviour. Describe what the reader sees, not what
produces it.

**Who else uses it.** No customer, tenant or company names, no account or
workspace identifiers, and nothing that identifies a person: names, emails,
phone numbers. An example is invented, not a real case shortened.

**Anything that authenticates.** Credentials, tokens, keys and connection
strings never appear, not even partially. A placeholder is obviously a
placeholder.

**Work that has not shipped.** Roadmap and unreleased behaviour is not
written as something the reader has today. No release dates, ticket ids or
staff names.

**Commercial and internal process.** Pricing negotiations, contract terms,
internal escalation paths, support tooling and team names stay out. Point the
reader to the product's own support entry point when they need help, not to a
person or an internal channel.

**How to defeat a control.** Explain a security setting to the depth the
reader needs to use it: how to turn it on, what it refuses, how to recover.
Stop before anything that helps bypass or weaken it.

**The run's bookkeeping.** No statement or concept ids, tool names, or talk of
the knowledge base behind the article.

## What may be revealed

Behaviour the reader can see and use, settings they control and what they
change, limits and defaults stated exactly, plan or role requirements, and
error messages quoted as the reader sees them.

## The hard case

When the only statement behind a useful sentence also carries an internal
detail, write the reader-visible effect and drop the mechanism. If the effect
alone is no longer supported or no longer useful, leave the sentence out.
Fail exposure when a withheld detail is still in the text, or when a sentence
only makes sense because of one.
````

## Templates

### `how-to`

````markdown
---
title: 
type: how-to
audience: external
last_updated: YYYY-MM-DD
related: []
---

<!--
HOW-TO for the help center. One task, the common path, on one screen.
- Title: "How to {task}" or "{Task verb} {object}", the words a reader would search for.
- No background beyond one sentence; no internals; no alternatives.
- Delete any section the gathered facts cannot fill.
-->

# {How to do the task}

{One sentence: what this does and when you would do it.}

## Before you start

- {Plan, role or permission the task needs}
- {Setting that must be on, or what must exist first}

> {Limit the reader will hit, stated plainly: "You can invite up to 50 people at once."}

## Steps

1. {Where to go: the menu or page, named as the product shows it}.
2. {One action per step, verb first: "Select **Export**"}.

   {Image: the screen this step happens on, when one is offered.}

3. {Action}.

## Check that it worked

{What the reader sees when it worked: a message, a status, a new item in a list.}

## If it did not work

{The one or two things that most often go wrong, each with its fix. Link a troubleshooting article only if one exists.}
````

### `troubleshooting`

````markdown
---
title: 
type: troubleshooting
audience: external
last_updated: YYYY-MM-DD
related: []
---

<!--
TROUBLESHOOTING for the help center. Organised by what the reader sees.
- Most common symptom first; three to five symptoms, not every possible one.
- Each cause in plain words, never the internal mechanism.
- Fixes are things the reader can do. When only support can fix it, say so.
- Delete any section the gathered facts cannot fill.
-->

# {Symptom area: "Exports do not arrive" / "I cannot sign in with SSO"}

{One sentence: what this covers.}

## {Symptom, in the reader's words: "I see 'Invite failed'"}

**Why it happens**: {plain cause, as the reader experiences it}.

**What to do**:

1. {Step the reader can take}.
2. {Step}.

## {Next symptom}

**Why it happens**: {cause}.

> ⚠️ {Warning before a step that deletes or changes something for good.}

**What to do**:

1. {Step}.

## Still not working

{What to have ready and where in the product to ask for help. No names of people or internal channels.}
````

### `explanation`

````markdown
---
title: 
type: explanation
audience: external
last_updated: YYYY-MM-DD
related: []
---

<!--
EXPLANATION for the help center. Short and practical: what it is, why it
matters to the reader, what it changes for them.
- A few paragraphs. No steps (that is a how-to), no full list of settings.
- Describe behaviour the reader sees, never how it is built.
- Delete any section the gathered facts cannot fill.
-->

# {What X is / How X works}

{One or two sentences: what it is, in plain words.}

## What it means for you

{What changes for the reader because of it: what they can do, what they see, what happens to their data.}

## What to know before you rely on it

- {Limit, default or plan requirement, stated plainly}.
- {Condition under which it behaves differently}.
````
