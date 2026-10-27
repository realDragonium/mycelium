## 1. Consistent snapshot

- [x] 1.1 Index writes and `mycelium snapshot-indexes` share a file lock; the snapshot copies nothing when an index is missing or dirty
- [x] 1.2 A snapshot sidecar records the database fingerprint: the mapped vector ids and their texts

## 2. Validate on load

- [x] 2.1 Startup loads a snapshot only when the database fingerprint matches, and rebuilds with a logged reason otherwise
- [x] 2.2 Deployment guide describes index durability on ephemeral storage
