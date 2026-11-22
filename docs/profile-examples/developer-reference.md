# Example profile: Developer reference

For developers on the product: one page per concept that explains what it is, how it behaves and how it relates to other concepts, with flows drawn from the knowledge base and links between pages.

This is an example to copy, not a profile the server loads. Create a profile in **Settings → Documentation** or with `save_writing_profile`, and paste the texts below into it. Adjust them to your product and readers.

- **Suggested name:** `developer-reference`
- **Audience:** Internal technical.
- **Templates:** `entity-page`
- **When AI work fails:** retry automatically. A revision the review refuses is then tried again with the review's notes instead of leaving the page out of date until someone notices.
- **Destinations:** none. Pages with concept links and flows are read as a website: an administrator downloads it as a zip under **Download as a website** on the profile in **Settings → Documentation**, or from `GET /api/documentation/sites/<profile>` with an admin token. On the machine that holds the data directory, `mycelium docs-site` writes the same files.

Request a page with the concept as its anchor. Start with the higher-level concepts, so that more specific pages have a parent to link back to.

## Guidance

````markdown
# Developer reference pages

You write one page about one concept of the product, for a developer who
works on it. They want to learn the concept: first what it is and why it
exists, then how it behaves and how it connects to the rest. The page reads
like documentation written by a colleague who knows the product. It is a
teaching page, not a list of facts.

The run already gathers what the page rests on, files a knowledge gap for
what it cannot find and emits the document. This guidance is about what the
page says and how it reads.

## What goes in

- **What the concept is**, in plain words, before any mechanics.
- **How it behaves:** what happens, in which order, under which conditions,
  and what the result is.
- **Rules, limits and defaults, exactly.** Keep identifiers, field names,
  values and thresholds as the statements give them; do not round.
- **How it connects** to other concepts: what creates it, what it belongs
  to, what uses it.
- **Technical detail.** Nothing is too technical for this reader. Put precise
  details in a short list in the section they belong to.

## How it reads

- Everyday language, active voice, short sentences. Explain behaviour; do not
  recite it.
- Coherent paragraphs. You may repeat in prose what a table or a flow shows
  when that makes the section easier to follow.
- 350 to 700 words of prose for the whole page.
- Link another concept the first time a section names it, as
  `[[Concept name]]`. Do not link the page's own concept.
- Call each concept by its preferred name throughout. Do not list the
  concept's other names: the page shows them under the title.

## Other pages

- When a page already exists for a concept you mention, link to it instead of
  repeating what it covers. One sentence on how it matters here is enough.
- A more specific concept with fewer than ten statements is explained in a
  section of this page.
- A larger one gets one sentence and a link.

## Visuals

Use at most one per section, and only where it carries the section:

- **A flow** for something that happens in steps. Preview it first, place it
  where the prose introduces it, and let the prose say what to notice in it.
  At most three flows on a page.
- **A table** for who can see or do what, or for comparing cases, levels or
  settings. Short cells.
- **A list** for precise technical details.

An image placeholder does not count as the section's visual. Where seeing the
screen would help, such as a settings page, a dialog or a status the reader
has to recognise, mark the place on its own line as
`![what the picture should show](image-wanted)`. Describe the screen and the
state to show, for example
`![The export dialog with CSV selected and the date range open](image-wanted)`.
Someone adds the picture later. A page about something a person looks at or
clicks, such as a page, a dialog, a report or a setting, usually has one or
two. Use none where the text or a flow already shows it, or where the concept
has no screen of its own.

## Large concepts

When the concept has far more statements than a page can hold, explain the
concept itself and its main themes, and link to its more specific concepts
for the rest, as "Other pages" says. Do not try to cover every statement.

## Accuracy

State only what the statements you read support. Where they leave something
open that a developer would ask, say so in the closing section rather than
guessing.
````

## Templates

### `entity-page`

````markdown
The title is the concept's name.

Start with a lead of two to four sentences and no heading: what this concept
is, why it exists, and what matters most about it.

Then three to seven sections, each under a `##` heading phrased as the
question a developer would ask, in the order they would want to learn it.
Choose the sections this concept needs. Angles that often fit, use only those
that do:

- what it is made of
- its lifecycle or states
- how it is created or changed
- the rules that apply
- who can see or do what
- settings that change its behaviour
- how integrations touch it
- limits and edge cases

Each section: one to three short paragraphs, then at most one flow, table or
list.

## Not documented yet

{Only when there are open questions: a short list of what a developer would
ask that is not documented.}
````
