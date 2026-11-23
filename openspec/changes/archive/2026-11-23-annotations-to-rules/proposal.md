## Why

The annotation subsystem was removed, but databases created before the removal kept its tables. Those tables still hold foreign keys to statements, entities and names, so deleting or merging any statement, entity or name that once carried an annotation fails with a foreign-key error. Their knowledge is also invisible: no tool, screen or document reads it.

## What Changes

- Upgrading a database that still holds annotations turns each one into a `rule` statement with the annotation's text, and links every statement it annotated to that rule with `governed-by`.
- The new rule takes the system its annotated statements share, and none when they differ or it annotated only entities.
- New rules get mentions, an embedding and an audience label the way any new statement does.
- The annotation tables are dropped, so deleting or merging a formerly annotated statement, entity or name works again.

## Decisions

- **Everything becomes a `rule`.** Annotations were claims about what they annotated (invariants, defaults, definitions, permissions, notes), which is what a rule is. Annotation `property` texts are sentences, not the noun-phrase slots a `property` statement holds. Curators can reclassify afterwards.
- **`governed-by` from the annotated statement.** It accepts any kind into a rule and is the usual way a statement points at the rule that constrains it.
- **Entity annotations rely on mentions.** No link joins an entity to a statement; the rule's mentions are derived from its text like any statement's. An entity annotation whose text yields no mention of its entity (it never names it, names it only ambiguously, or a longer name wins the match) loses that association; the upgrade logs each one with its ids rather than refusing to start, since the text itself survives as a rule.

## Impact

- Archive import is unchanged: it still skips annotation records from older archives.
