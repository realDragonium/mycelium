## 1. Principals
- [x] 1.1 Remove the audience from users, tokens and OAuth grants, and the scoped allowlists and reads
- [x] 1.2 Drop the `audience_id` columns in the auth store, logging scoped principals, and capture a migration fixture
- [x] 1.3 Restore older backups that carry the columns

## 2. Web app and docs
- [x] 2.1 Remove the audience selects, the scoped shell and the scoped document workspace
- [x] 2.2 Update the docs and skills that described scoped principals
