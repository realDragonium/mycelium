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
