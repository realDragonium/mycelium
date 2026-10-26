## 1. Root cause

- [x] 1.1 `Index.add` overwrites a held id's own slot and fills a deleted slot only for a new id

## 2. One-off repair

- [x] 2.1 Record index format 2 in the sidecar and rebuild an index of an earlier format once
- [x] 2.2 Deployment guide describes the format
