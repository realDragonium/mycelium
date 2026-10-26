## 1. Root cause

- [x] 1.1 `Index.add` overwrites a held id's own slot and fills a deleted slot only for a new id

## 2. Startup reconciliation

- [x] 2.1 Compact unreachable slots, drop mappings without a vector, prune vectors without a mapping, for both indexes
- [x] 2.2 Tests for each drift direction and an embedding failure during the heal
- [x] 2.3 Deployment guide describes the reconciliation
