# Code style

A compass, not a rulebook. `ruff` enforces the mechanical parts; everything
else is judgment. When in doubt, match the surrounding code.

## Enforced by ruff (`uv run ruff check` / `uv run ruff format`)

Run over `src tests scripts bench`, by the pre-commit hook and in CI.

- **Line length 88**, double quotes, spaces — ruff format defaults. The
  formatter is the sole authority on layout; don't hand-wrap code.
- **Import order**: stdlib → third-party → first-party (`mycelium`), sorted.
  `from __future__ import annotations` stays first where present.
- **Lint rules**: pyflakes (`F`), pycodestyle errors (`E4`/`E7`/`E9`),
  import sorting (`I`), bugbear (`B`) minus the two ignores documented
  in `pyproject.toml`, pyupgrade (`UP`), and three `RUF` rules: chained
  `and`/`or` without parentheses (`RUF021`), unescaped regex metacharacters
  in `pytest.raises(match=)` (`RUF043`), and unpacked values never used
  (`RUF059`). Deliberately a small set — a rule earns its place by
  catching real bugs, not by generating churn.
- **Complexity ≤ 15** (`C901`, product code only — `scripts/` and `bench/`
  exempt).
  When a function trips it, decompose along its real phase seams
  (validate → normalize → write → respond), never by line count. The
  extracted pieces should be nameable — if you can't name it, it wasn't
  a seam.

### Rules considered and rejected

Evaluated against this tree when the gate was tightened. Each would mostly
rewrite working code to taste, or fight a convention this codebase keeps on
purpose:

- **`SIM` (simplify)**: the hits were merged `with` statements,
  `contextlib.suppress` for `try/except/pass`, ternaries for short
  `if/else`. Readability calls, not bugs.
- **`C4` (comprehensions)**: one hit, a generator inside `set()`. Tidier,
  never wrong.
- **The rest of `RUF`**: `RUF001`–`RUF003` flag the dashes, typographic
  quotes and look-alike letters that phrasing validation and its tests
  handle on purpose; `RUF005` prefers `[*a, b]` to `a + [b]`;
  `RUF022` sorts `__all__`, which is grouped by meaning. `RUF100` would
  strip the `# noqa: BLE001 — reason` markers that document deliberate
  broad excepts, because `BLE` isn't enabled.
- **`TID` (tidy imports)**: `TID252` bans relative imports, which the
  package uses throughout (161 hits).

## Enforced by mypy (`uv run mypy src`)

CI runs mypy as its own job. The pre-commit hook doesn't, to keep commits
quick. mypy, not pyright: the backend gate stays pure Python and
uv-installable, with no Node.

Every module is held to one **baseline**: `check_untyped_defs`,
`no_implicit_optional`, `warn_redundant_casts`, `warn_unused_ignores`,
`warn_unreachable`, `strict_equality`, `extra_checks`, plus the
`ignore-without-code`, `truthy-bool` and `deprecated` error codes. On top
of that sit two lists in `pyproject.toml`:

- **Strict tier**: modules that pass `--strict` (untyped and incomplete
  defs, bare generics, untyped calls and decorators, `Any` returns, implicit
  re-exports). The list names modules explicitly, so add a new module to
  it when you create one. A module that joins doesn't leave.
- **Ratchet**: modules that fail one baseline check. Each entry switches off
  only the error codes that module trips and has a comment saying what
  unblocks it. Fix the blocker, delete the entry. Never add a wildcard or a
  module-wide `ignore_errors`.

When mypy objects, fix the type: narrow with `isinstance`, bind to a typed
local, annotate the variable. Don't reach for `Any` or `cast` to make it
quiet. When a library's typing is the limit, write a specific
`# type: ignore[code]` with the reason on the same line or the one above
(pydantic's `@computed_field` over `@property` is the standard case). An
`assert` is fine for an invariant the code guarantees but mypy can't see,
e.g. a row read back after the INSERT that wrote it.

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
