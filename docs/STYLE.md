# Code style

A compass, not a rulebook. `ruff` enforces the mechanical parts; everything
else is judgment. When in doubt, match the surrounding code.

## Enforced by ruff (`uv run ruff check` / `uv run ruff format`)

- **Line length 88**, double quotes, spaces — ruff format defaults. The
  formatter is the sole authority on layout; don't hand-wrap code.
- **Import order**: stdlib → third-party → first-party (`mycelium`), sorted.
  `from __future__ import annotations` stays first where present.
- **Lint rules**: pyflakes (`F`), pycodestyle errors (`E4`/`E7`/`E9`),
  import sorting (`I`), and bugbear (`B`) minus the two ignores documented
  in `pyproject.toml`. Deliberately a small set — a rule earns its place by
  catching real bugs, not by generating churn.

## Local (in-function) imports are intentional

Do **not** hoist an in-function import to module top without checking why
it's there. Two legitimate reasons in this codebase:

1. **Lazy optional/heavy deps** — e.g. `anthropic` is imported inside the
   functions that use it so the package stays importable without the SDK or
   an API key. Same idea for `spacy`, `pyinstrument`, `matplotlib`.
2. **Cycle breaking** — the `server.py` ↔ `http.py` ↔ stores seam has
   import cycles that local imports resolve.

When an import must stay local, say why in a trailing comment:
`import anthropic  # local import: keeps the package importable without the key`.
Rules that fight this pattern (e.g. `PLC0415`) stay disabled.

## Docstrings and comments

- Module docstring: what the module is and the one non-obvious thing about
  it (see `server.py`, `http.py` for the house style).
- Function docstrings: one imperative summary line; add detail only when the
  signature doesn't tell the story. No param-by-param boilerplate.
- Comments state constraints the code can't express — not what the next
  line does.

## Shape

- Pure functions for core logic; I/O and side effects at the boundaries.
- No inheritance in our own code unless a framework forces it.
- Naming: say what it is; drop `Manager`/`Helper`/`Utils` suffixes.
- Simplicity is the default — complexity must justify itself with a concrete
  problem it solves.
