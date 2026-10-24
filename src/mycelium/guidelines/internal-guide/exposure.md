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
