## Why

The load balancer's only liveness check is `/api/server-info`, and it got 503 until startup finished. A one-off index rebuild can outlast the service's grace period on a small CPU-only task. The task is then killed, its replacement starts the rebuild again from scratch, and rolling back meets the same unfinished rebuild.

## What Changes

- `/api/server-info` answers 200 with the startup state while starting, migrating or indexing, and 503 only once startup failed.
- Every other request still gets 503 until startup is ready, and browsers still get the page that reloads itself.
- The web app shows server banners only from a ready answer.

## Impact

- Clients that took a 200 from `/api/server-info` to mean ready must read `state` instead. The docgen eval script is updated.
