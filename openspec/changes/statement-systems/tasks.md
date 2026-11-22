## 1. Store a statement's system

- [x] 1.1 Migration: nullable, indexed statement system referencing entities; existing rows stay empty
- [x] 1.2 Archive export and import carry it; older archives import with no system

## 2. Write it

- [x] 2.1 `system` (entity id or exact name) on `upsert_statement`, `upsert_statements` (batch default, per-item override), `patch_statement` and `ingest`; omitted keeps, `null` clears, an unknown name fails before writing
- [x] 2.2 Draft operations carry the system; corrections and apply keep it
- [x] 2.3 History records system changes

## 3. Read and filter it

- [x] 3.1 `system: {entity_id, name}` on unscoped hydrated statements, list rows and grep rows
- [x] 3.2 Audience-scoped reads leave it out
- [x] 3.3 `system` filter (`"main"` for none) on `search_statements`, `list_statements`, `grep_statements` and statement-backed `claim_curation_work` kinds
- [x] 3.4 Statements per system in knowledge health

## 4. Keep it consistent

- [x] 4.1 `merge_statements` refuses differing systems
- [x] 4.2 `merge_entities` moves system references; `delete_entity` refuses a referenced system; a referenced system is not `unused`

## 5. Web app

- [x] 5.1 Show and edit the system on the statement page; filter the statement list by system

## 6. Guidance and data

- [x] 6.1 Document the field in the data model, MCP manifest and authoring skills (what a system is, splitting cross-app behaviour, procedure roots and steps); point the guide-authoring third-party action note at the system
- [ ] 6.2 One reviewed draft assigning existing integration statements
