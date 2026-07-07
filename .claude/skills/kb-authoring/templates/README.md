# Knowledge base templates

Five templates, aligned with [Diátaxis](https://diataxis.fr/) plus a pragmatic Troubleshooting type.

## Pick a type

| You want to... | Use |
|---|---|
| Walk someone through their first successful experience | **Tutorial** |
| Help someone accomplish a specific task (incl. configuration/setup) | **How-to** |
| Provide lookup material: settings, fields, params, limits | **Reference** |
| Explain how something works, why it works that way | **Explanation** |
| Help someone fix a problem they're hitting right now | **Troubleshooting** |

If you can't decide between two, the question is usually: *what does the reader want right now?*

- Learning → Tutorial
- Doing → How-to
- Looking up → Reference
- Understanding → Explanation
- Fixing → Troubleshooting

Don't mix types in one doc. Split and link.

## Audience

Every template has an `audience` field:

- `external` — customers and end users see this
- `internal` — only the team sees this
- `both` — visible everywhere, but written for the most cautious audience (external)

Internal-only docs (Troubleshooting runbooks, infra Reference) tend to be terser; the warm tone matters most for `external` and `both`.

## Tone

Warm, friendly, clear. Like a knowledgeable colleague — not a manual, not a marketing email.

- Second person ("you"), active voice
- Short sentences. Plain words.
- Acknowledge effort where natural ("This one's fiddly — here's the shortcut")
- No fake enthusiasm, no "simply", no "just"
- In external docs, define jargon on first use or skip it

Reference is the exception — it's allowed to be dry. Warmth lives in the intro and section preambles, not the tables.

## Frontmatter

```yaml
---
title: 
type: tutorial | how-to | reference | explanation | troubleshooting
audience: external | internal | both
last_updated: YYYY-MM-DD
owner: 
related: []
---
```

`related` holds slugs/paths to docs that pair well with this one (a How-to and its Explanation, a Reference and its Troubleshooting, etc.).
