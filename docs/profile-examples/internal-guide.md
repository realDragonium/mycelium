# Example profile: Internal guide

For support, sales and customer success: reference, explanations, how-tos and troubleshooting with the conditions, edge cases and limits staff need to answer customers.

This is an example to copy, not a profile the server loads. Create a profile in **Settings → Documentation** or with `save_writing_profile`, and paste the texts below into it. Adjust them to your product and readers.

- **Suggested name:** `internal-guide`
- **Audience:** Internal non-technical.
- **Templates:** `reference`, `explanation`, `how-to`, `troubleshooting`

## Guidance

````markdown
# Internal guide articles

You write one internal guide article for colleagues who talk to customers:
support, sales, customer success. They are not engineers. They need to know
exactly what the product does, under which conditions, and where it stops,
so they can answer a customer correctly the first time.

The run already gathers what the article rests on, files a knowledge gap for
what it cannot find and emits the document. This guidance is about what the
article says and how it reads.

## Who reads it

A colleague answering a customer question, preparing a call or checking
whether a request is possible. They know the product from the outside and
the customers' vocabulary. They need fuller behaviour than a customer gets,
in plain language.

## What goes in

- **The full behaviour.** What happens, in which order, and what the customer
  sees at each point, including the less common paths.
- **Conditions.** Plans, roles, settings and states a behaviour depends on.
  Write each condition next to the behaviour it governs: "Only workspace
  owners can delete a workspace; admins see the option greyed out."
- **Limits and defaults, exactly.** Caps, quotas, time windows, retention,
  defaults and what happens at the limit. State numbers as the statements give
  them; do not round.
- **Edge cases.** What happens when the usual preconditions do not hold:
  a setting changed halfway, a user removed, a limit reached, two features
  combined. These are what colleagues get asked and why the guide exists.
- **What a colleague can and cannot do for a customer.** When a statement
  says a change needs support or an admin, say who.
- **Why, when it helps answer the customer.** A rule's reason in a sentence,
  when the statements give it.

## What stays out

- Code, internal component and service names, data models, infrastructure:
  the audience description excludes them. Describe the behaviour they
  produce.
- Anything the audience description excludes, even when a statement the run
  can see mentions it.
- Guesses about intent, roadmap or future behaviour.

## Tone and length

- Plain, direct and neutral. Write to a colleague ("you", "the customer").
  No marketing and no reassurance.
- Complete over short: an internal article may be long when the behaviour is.
  Structure it so a colleague finds one answer fast: headings per case,
  tables for conditions and limits, one idea per paragraph.
- Name things as the product shows them to customers, so a colleague can
  repeat the words.

## Accuracy

State a product fact only when a statement you gathered supports it. A
condition or limit that is not documented is not written as if it were; leave
it out and let the gap stand, or, when the reader must know that it is open,
mark it:

```
> ⚠️ needs verification: [what is unclear, in the reader's terms].
```

When two statements disagree, say both and mark it; do not choose. Never
mention where the facts came from: no ids, no tool names, no talk of a
knowledge base or what it holds.

## Filling the template

- Fill every frontmatter field you have a source for. `last_updated` is
  today's date (YYYY-MM-DD). Leave `related` as `[]` unless you know another
  article exists; never invent a link or a path.
- Delete any section, table row or column the gathered facts cannot fill. An
  omitted section is not a defect; a placeholder left in is.
- Remove every HTML comment (`<!-- … -->`); they are notes for you.
- Place an offered screenshot where it shows what the customer sees.
````

## Disclosure rules

````markdown
# What an internal guide article may reveal

An internal guide is read by staff who are not engineers. The run reads only
what its audience may see, and the reviewer checks the article against the
audience's description; these rules hold on top of both. Colleagues may
forward or paste from an article, so it is written to be safe in their hands.

## What may be revealed

Everything about the product's behaviour a colleague needs to answer a
customer: conditions, edge cases, limits, defaults, plan and role rules, what
support or an admin can change, and how internal processes that customers
notice run (approvals, review times, escalation steps), when the statements
say so.

## What stays out

**Technical internals.** No code, internal service, component, job, database,
repository or host names, and no infrastructure. Describe the behaviour, not
the machinery.

**Anything that authenticates.** Credentials, tokens, keys and connection
strings never appear, whoever is reading.

**Personal data.** Nothing that identifies a person: names, emails, phone
numbers, account numbers. An example is invented, not a real case shortened.

**Other customers' business.** No named customer's configuration, contract,
incidents or data, unless the article is about a behaviour every customer
shares and the name adds nothing; then leave the name out.

**Material given in confidence.** Anything a third party shared under
confidentiality stays out.

**The run's bookkeeping.** No statement or concept ids, tool names, or talk of
the knowledge base behind the article.

## The hard case

When a useful sentence rests on a statement that also carries a technical
internal, write the behaviour and drop the mechanism. Fail exposure when a
withheld detail is still in the text, or when a sentence only makes sense
because of one.
````

## Templates

### `reference`

````markdown
---
title: 
type: reference
audience: internal
last_updated: YYYY-MM-DD
related: []
---

<!--
REFERENCE for the internal guide. Look-up material: what exists, its
options, conditions, limits and defaults.
- Tables and lists over prose; prose only in the opening line and Notes.
- Every row the statements support; none they do not.
- Delete any section, row or column the gathered facts cannot fill.
-->

# {The thing being referenced: "Workspace roles" / "Invoice export options"}

{One sentence: what this covers and who it applies to.}

## {Group: "Settings" / "Roles" / "Options"}

| Name | What it does | Default | Who can change it | Conditions |
|------|--------------|---------|-------------------|------------|
| {Name as the product shows it} | {one line} | {default} | {role} | {plan, state or setting it depends on} |

## Limits

| Limit | Value | What happens at the limit |
|-------|-------|---------------------------|
| {What is limited} | {exact value} | {what the customer sees} |

## Edge cases

- **{Situation}**: {what happens}.

## Notes

{Interactions between options, differences by plan, behaviour that changed and when, when the statements say so.}
````

### `explanation`

````markdown
---
title: 
type: explanation
audience: internal
last_updated: YYYY-MM-DD
related: []
---

<!--
EXPLANATION for the internal guide. Help a colleague understand a feature
well enough to explain it to a customer and predict what it will do.
- Behaviour, rules and their reasons; no steps (that is a how-to).
- Describe behaviour, never the code or infrastructure behind it.
- Delete any section the gathered facts cannot fill.
-->

# {How X works}

{Two or three sentences: what it is and what it is for, as you would explain it to a customer.}

## How it behaves

{The behaviour from the customer's side, from the common path to the less common ones.}

### {Case or sub-feature}

{What happens and under which conditions.}

## Rules and limits

- {Rule or limit, exactly, and when it applies}.

## Why it works this way

{The reason, when the statements give one. Delete this section otherwise.}

## Questions customers ask

- **{Question in the customer's words}** — {answer, with its condition}.
````

### `how-to`

````markdown
---
title: 
type: how-to
audience: internal
last_updated: YYYY-MM-DD
related: []
---

<!--
HOW-TO for the internal guide. One task a colleague does, or walks a
customer through, with the conditions and variations that change it.
- Steps for the common path; variations after them, each with its condition.
- Name who may do each step when it is not everyone.
- Delete any section the gathered facts cannot fill.
-->

# {How to do the task}

{One sentence: what this achieves and when a colleague or customer does it.}

## Before you start

- {Role, plan or permission needed, and who has it}
- {Setting or state that must hold}

## Steps

1. {Action, verb first, named as the product shows it}.
2. {Action}.

   {Image: the screen this step happens on, when one is offered.}

## Variations

- **{Condition: "On the Starter plan" / "If SSO is enforced"}**: {what changes}.

## Limits

- {Limit that applies to this task, exactly}.

## Check that it worked

{What the colleague or customer sees when it worked.}
````

### `troubleshooting`

````markdown
---
title: 
type: troubleshooting
audience: internal
last_updated: YYYY-MM-DD
related: []
---

<!--
TROUBLESHOOTING for the internal guide. From what the customer reports to
the cause and the fix, including the conditions that decide between causes.
- Organised by symptom as the customer describes it.
- For each: how to tell the causes apart, then the fix for each cause.
- Say who can apply a fix when it is not the customer.
- Delete any section the gathered facts cannot fill.
-->

# {Symptom area: "Customer cannot export invoices"}

{One sentence: what this covers.}

## {Symptom, as the customer reports it}

**Possible causes**:

| Cause | How to tell | Fix | Who can fix it |
|-------|-------------|-----|----------------|
| {Cause, in plain words} | {what to check, and what you see when this is the cause} | {what to do} | {customer, admin or support} |

**Edge cases**: {situations where the usual fix does not apply, and what to do instead}.

## {Next symptom}

**Possible causes**:

| Cause | How to tell | Fix | Who can fix it |
|-------|-------------|-----|----------------|
| {Cause} | {check} | {fix} | {who} |

> ⚠️ {Warning before a fix that deletes or changes something for good.}

## When to escalate

{What is known to need escalation, and what to gather first, when the statements say so.}
````
