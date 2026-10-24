"""Run ingest over the evaluation cases and score the drafts it produces.

Not part of the pytest run: it calls the model and needs a prepared data
directory. The committed cases live in `tests/ingest_eval/*.toml` and run
against the invented knowledge base in `tests/ingest_eval/seed.toml`; scoring
rules are in `ingest_eval_scoring.py` (pure, unit-tested). A case directory
outside the repo (`--cases-dir`) can be run against any other prepared data
directory, such as a local copy of real data; such cases name existing records
by id instead of `seed:<key>`.

Environment:
    MYCELIUM_DATA_DIR   a prepared base data directory (see `prepare`); every
                        case runs against its own fresh copy of it
    ANTHROPIC_API_KEY   for the ingest model and the judge
    OLLAMA_URL          embeddings (nomic-embed-text), default localhost:11434

Usage:
    ingest_eval.py prepare [--seed FILE | --backup DIR]
                          # write the seed (default) or copy a backup into
                          # $MYCELIUM_DATA_DIR, migrate, embed
    ingest_eval.py run LABEL [--cases-dir DIR] [--cases a,b] [--model M]
                          [--effort E] [--jobs N]
                          # --effort: Claude reasoning effort; omitted, the
                          # model's default, as ingest runs unless configured
    ingest_eval.py score LABEL            # re-score a finished run

Results go to ~/mycelium-eval/ingest-results/LABEL/ (override with
MYCELIUM_EVAL_RESULTS): one raw JSON per case, `results.json`, `summary.md`.

The judge maps each statement the draft creates to the expected statement
making the same claim. Model and prompt are fixed below; its answers are
cached by prompt hash, so re-scoring a run is deterministic and free.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar, get_args

import ingest_eval_scoring as scoring
from pydantic import BaseModel, ConfigDict, JsonValue
from typing_extensions import TypeIs

from mycelium.ai.types import CLAUDE_EFFORT, ClaudeEffort

if TYPE_CHECKING:
    from mycelium.server.draft_queue import DraftReceipt

REPO = Path(__file__).resolve().parents[1]
CASES_DIR = REPO / "tests" / "ingest_eval"
SEED_FILE = CASES_DIR / "seed.toml"
SEED_IDS = "seed-ids.json"
RESULTS = Path(
    os.environ.get("MYCELIUM_EVAL_RESULTS")
    or Path.home() / "mycelium-eval" / "ingest-results"
)
DEFAULT_MODEL = "claude-sonnet-4-6"
JUDGE_MODEL = "claude-sonnet-5-5"


def _toml(path: Path) -> dict[str, object]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def load_cases(
    cases_dir: Path, seed_ids: dict[str, str] | None = None
) -> dict[str, scoring.Case]:
    cases = {}
    for path in sorted(cases_dir.glob("*.toml")):
        if path.name == SEED_FILE.name:
            continue
        case = scoring.parse_case(_toml(path), seed_ids or {})
        cases[case.id] = case
    return cases


class RunSpec(BaseModel):
    """What a run was against, kept beside its results so `score` can redo it."""

    cases_dir: Path
    seed_ids: dict[str, str] = {}

    @classmethod
    def load(cls, run_dir: Path) -> RunSpec:
        return cls.model_validate_json((run_dir / "run.json").read_text("utf-8"))

    def cases(self) -> dict[str, scoring.Case]:
        return load_cases(self.cases_dir, self.seed_ids)


# --------------------------------------------------------------------------- #
# Data directory
# --------------------------------------------------------------------------- #


def _quiet_environment() -> None:
    os.environ["MYCELIUM_DISABLE_MENTION_WORKER"] = "1"
    os.environ["MYCELIUM_DISABLE_REVIEW_SWEEP"] = "1"


def _empty(base: Path) -> None:
    if base.exists() and any(base.iterdir()):
        sys.exit(f"{base} is not empty")
    base.mkdir(parents=True, exist_ok=True)


def prepare_backup(backup: Path, base: Path) -> None:
    """Copy a backup's databases into `base`, migrate them and build the vector
    indexes, so each case's copy starts instantly."""
    _empty(base)
    for db in backup.glob("*.db"):
        shutil.copy2(db, base / db.name)
    _quiet_environment()
    from mycelium.server import startup

    startup.init(base)
    print(f"prepared {base}")


T = TypeVar("T")


def _live(result: T | DraftReceipt) -> T:
    """The tool's own result: the seed is written live, never onto a draft."""
    if _is_receipt(result):
        sys.exit(f"seed write was queued on draft {result['draft_id']}")
    return result


def _is_receipt(result: object) -> TypeIs[DraftReceipt]:
    return isinstance(result, dict) and "draft_id" in result and "queued" in result


def prepare_seed(seed_file: Path, base: Path) -> None:
    """Write the seed knowledge base into a fresh `base` and record the id each
    seed record got in `seed-ids.json`."""
    _empty(base)
    seed = scoring.parse_seed(_toml(seed_file))
    _quiet_environment()
    from mycelium import server
    from mycelium.server import startup

    startup.init(base)
    ids: dict[str, str] = {}
    for entity in seed.entities:
        created = _live(server.upsert_entity(entity.name, entity.description))
        ids[entity.key] = created["entity_id"]
        for alias in entity.aliases:
            server.upsert_name(alias, ids[entity.key])
    written = _live(server.upsert_statements(seed.batch))["results"]
    for key, row in zip(seed.statement_keys, written, strict=True):
        if "statement_id" not in row:
            sys.exit(f"seed statement {key!r} was rejected: {row}")
        ids[key] = row["statement_id"]
    (base / SEED_IDS).write_text(json.dumps(ids, indent=1), encoding="utf-8")
    print(f"prepared {base}: {len(seed.entities)} entities, {len(written)} statements")


def _init_copy(base: Path, target: Path) -> None:
    shutil.copytree(base, target, ignore=shutil.ignore_patterns("*-wal", "*-shm"))
    _quiet_environment()
    from mycelium import prompt_store
    from mycelium.server import startup

    startup.init(target)
    # Evaluate the doctrine shipped in this checkout, not a saved copy.
    prompt_store.connection().execute(
        "UPDATE prompt_texts SET deleted = 1 WHERE type = 'doctrine' AND name = 'ingest'"
    )
    prompt_store.connection().commit()


# --------------------------------------------------------------------------- #
# One case (runs in its own process)
# --------------------------------------------------------------------------- #


def _draft_ops(draft_id: str | None) -> list[dict[str, JsonValue]]:
    if not draft_id:
        return []
    from mycelium import drafts_store
    from mycelium.server import _drafts_db

    return [
        {
            "seq": row["seq"],
            "kind": row["kind"],
            "payload": json.loads(row["payload_json"]),
        }
        for row in drafts_store.list_ops(_drafts_db(), draft_id)
    ]


def run_one(
    case_id: str, run_dir: Path, model: str, effort: ClaudeEffort | None
) -> None:
    case = RunSpec.load(run_dir).cases()[case_id]
    out = run_dir / f"{case_id}.raw.json"
    base = Path(os.environ["MYCELIUM_DATA_DIR"])
    with tempfile.TemporaryDirectory(prefix=f"ingest-eval-{case_id}-") as tmp:
        _init_copy(base, Path(tmp) / "data")
        from mycelium.ingest import IngestConfig, run_ingest

        config = dataclasses.replace(
            IngestConfig.from_env(),
            provider="claude",
            model=model,
            reasoning_effort=effort,
            trace_log_path=None,
            trace_dir="",
        )
        started = time.monotonic()
        result = run_ingest(case.prose, config=config)
        elapsed = time.monotonic() - started
        data = result.model_dump(mode="json")
        record = {
            "case": case_id,
            "model": model,
            "reasoning_effort": effort,
            "outcome": result.outcome,
            "elapsed_s": round(elapsed, 1),
            "draft_ops": _draft_ops(data.get("draft_id")),
            "alias_ops": _draft_ops(data.get("alias_draft_id")),
            "result": data,
        }
    out.write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Judge
# --------------------------------------------------------------------------- #

JUDGE_SYSTEM = """\
You compare statements proposed by a knowledge-extraction system with an \
answer key. Each answer-key statement is one atomic claim about a software \
product. For every PROPOSED statement, name the answer-key statement that \
makes the same claim, or null if none does.

Same claim means: same subject, same predicate, same polarity, and the same \
values (numbers, names, durations). Wording, voice and article choice may \
differ ("A reminder is sent" = "The system sends a reminder"). A proposed \
statement does NOT match if it only covers part of the key claim, adds a \
second claim, states a different value, flips polarity, or is about a \
different subject. Prefer the closest key statement when several are related; \
use each key statement for at most one proposed statement unless two proposed \
statements are restatements of each other. Answer for every proposed index."""


class _Match(BaseModel):
    proposed: int
    key: str | None
    reason: str


class _Judgement(BaseModel):
    matches: list[_Match]


def _judge_prompt(case: scoring.Case, graph: scoring.DraftGraph) -> str:
    key = "\n".join(f"- {s.key}: {s.text}" for s in case.statements)
    proposed = "\n".join(f"{i}. {s.text}" for i, s in enumerate(graph.statements))
    return f"ANSWER KEY:\n{key}\n\nPROPOSED:\n{proposed}"


class _Stored(BaseModel):
    matches: list[_Match]
    tokens: _Tokens


def judge(
    case: scoring.Case, graph: scoring.DraftGraph
) -> tuple[dict[int, str | None], int]:
    """The judge's statement mapping, and the tokens it used (0 when cached)."""
    if not graph.statements:
        return {}, 0
    prompt = _judge_prompt(case, graph)
    digest = hashlib.sha256(
        f"{JUDGE_MODEL}\n{JUDGE_SYSTEM}\n{prompt}".encode()
    ).hexdigest()
    cache = RESULTS / "judge-cache" / f"{digest}.json"
    if cache.exists():
        stored = _Stored.model_validate_json(cache.read_text(encoding="utf-8"))
        spent = 0
    else:
        import anthropic

        response = anthropic.Anthropic().messages.parse(
            model=JUDGE_MODEL,
            max_tokens=8000,
            system=JUDGE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_format=_Judgement,
        )
        if response.parsed_output is None:
            raise RuntimeError(f"judge returned no result for {case.id}")
        stored = _Stored(
            matches=response.parsed_output.matches,
            tokens=_Tokens(
                input=response.usage.input_tokens,
                output=response.usage.output_tokens,
            ),
        )
        spent = _used(stored.tokens)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(stored.model_dump_json(indent=1), encoding="utf-8")
    mapping: dict[int, str | None] = {}
    for m in stored.matches:
        mapping.setdefault(m.proposed, m.key)
    return mapping, spent


# --------------------------------------------------------------------------- #
# Scoring a run
# --------------------------------------------------------------------------- #


class _View(BaseModel):
    """Read-side view of a raw record: only the fields scoring uses."""

    model_config = ConfigDict(extra="ignore")


class _Op(_View):
    seq: int
    kind: str
    payload: dict[str, JsonValue]


class _Tokens(_View):
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_creation: int = 0


class _LedgerRow(_View):
    classification: str | None = None
    matched_against: list[str] = []


class _Trace(_View):
    latency_ms: float = 0
    model_turns: int = 0
    tool_calls: list[JsonValue] = []
    forced_finalize: str | None = None
    tokens: _Tokens = _Tokens()
    flagged: list[str] = []
    candidate_ledger: list[_LedgerRow] = []


class _Result(_View):
    draft_id: str | None = None
    alias_draft_id: str | None = None
    trace: _Trace = _Trace()


class _Record(_View):
    case: str
    model: str
    outcome: str
    draft_ops: list[_Op]
    alias_ops: list[_Op]
    result: _Result


def _used(tokens: _Tokens) -> int:
    return tokens.input + tokens.output + tokens.cache_read + tokens.cache_creation


def _graph(record: _Record) -> scoring.DraftGraph:
    # An alias-only run puts its suggestions in the knowledge draft itself.
    separate = record.result.alias_draft_id != record.result.draft_id
    ops = record.draft_ops + (record.alias_ops if separate else [])
    return scoring.extract_draft([(op.seq, op.kind, op.payload) for op in ops])


def _ledger(trace: _Trace) -> scoring.Ledger:
    rows = tuple(
        (str(r.classification), tuple(r.matched_against))
        for r in trace.candidate_ledger
    )
    return scoring.Ledger(flagged=tuple(trace.flagged), rows=rows)


class CaseResult(BaseModel):
    case: str
    categories: list[str]
    outcome: str
    latency_s: float
    model_turns: int
    tool_calls: int
    forced_finalize: str | None
    tokens: _Tokens
    total_tokens: int
    metrics: dict[str, float | None]
    counts: dict[str, int]
    statements: list[dict[str, str]]


class RunResults(BaseModel):
    label: str
    cases: int
    metrics: dict[str, float | None]
    counts: dict[str, int]
    total_tokens: int
    judge_tokens: int
    latency_s_median: float | None
    latency_s_max: float | None
    per_case: list[CaseResult]


def score_run(label: str) -> RunResults:
    run_dir = RESULTS / label
    cases = RunSpec.load(run_dir).cases()
    total = scoring.Counts()
    per_case: list[CaseResult] = []
    judge_tokens = 0
    for path in sorted(run_dir.glob("*.raw.json")):
        record = _Record.model_validate_json(path.read_text(encoding="utf-8"))
        case = cases[record.case]
        graph = _graph(record)
        trace = record.result.trace
        judged, spent = judge(case, graph)
        judge_tokens += spent
        counts, outcomes = scoring.score_case(case, graph, judged, _ledger(trace))
        total.add(counts)
        per_case.append(
            CaseResult(
                case=case.id,
                categories=list(case.categories),
                outcome=record.outcome,
                latency_s=round(trace.latency_ms / 1000, 1),
                model_turns=trace.model_turns,
                tool_calls=len(trace.tool_calls),
                forced_finalize=trace.forced_finalize,
                tokens=trace.tokens,
                total_tokens=_used(trace.tokens),
                metrics=scoring.metrics(counts),
                counts=dataclasses.asdict(counts),
                statements=[
                    {"text": s.text, "kind": s.kind, "outcome": o}
                    for s, o in zip(graph.statements, outcomes, strict=True)
                ],
            )
        )
    latencies = sorted(c.latency_s for c in per_case)
    results = RunResults(
        label=label,
        cases=len(per_case),
        metrics=scoring.metrics(total),
        counts=dataclasses.asdict(total),
        total_tokens=sum(c.total_tokens for c in per_case),
        judge_tokens=judge_tokens,
        latency_s_median=latencies[len(latencies) // 2] if latencies else None,
        latency_s_max=latencies[-1] if latencies else None,
        per_case=per_case,
    )
    (run_dir / "results.json").write_text(
        results.model_dump_json(indent=1), encoding="utf-8"
    )
    (run_dir / "summary.md").write_text(_summary(results), encoding="utf-8")
    return results


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"


def _summary(results: RunResults) -> str:
    lines = [
        f"# Ingest eval: {results.label}",
        "",
        f"{results.cases} cases, ingest {results.total_tokens:,} tokens, judge "
        f"{results.judge_tokens:,}, latency median "
        f"{results.latency_s_median}s / max {results.latency_s_max}s",
        "",
        "| metric | value |",
        "|---|---|",
        *(f"| {k} | {_fmt(v)} |" for k, v in results.metrics.items()),
        "",
        "| case | outcome | forced | turns | recall | precision | reuse "
        "| link typed | dup | extra | tokens | s |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in results.per_case:
        m, n = c.metrics, c.counts
        lines.append(
            f"| {c.case} | {c.outcome} | {c.forced_finalize or ''} | "
            f"{c.model_turns} | {_fmt(m['statement_recall'])} | "
            f"{_fmt(m['statement_precision'])} | {_fmt(m['reuse_accuracy'])} | "
            f"{_fmt(m['link_recall_typed'])} | {n['duplicates_of_existing']} | "
            f"{n['extras']} | {c.total_tokens} | {c.latency_s} |"
        )
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _run(
    label: str,
    cases_dir: Path,
    case_ids: list[str],
    model: str,
    effort: ClaudeEffort | None,
    jobs: int,
) -> None:
    run_dir = RESULTS / label
    run_dir.mkdir(parents=True, exist_ok=True)
    seed_ids = Path(os.environ["MYCELIUM_DATA_DIR"]) / SEED_IDS
    spec = RunSpec(
        cases_dir=cases_dir.resolve(),
        seed_ids=json.loads(seed_ids.read_text("utf-8")) if seed_ids.exists() else {},
    )
    (run_dir / "run.json").write_text(spec.model_dump_json(indent=1), "utf-8")
    case_ids = case_ids or list(spec.cases())
    pending = [c for c in case_ids if not (run_dir / f"{c}.raw.json").exists()]

    def one(case_id: str) -> None:
        log = run_dir / f"{case_id}.log"
        with log.open("w") as handle:
            done = subprocess.run(
                [
                    sys.executable,
                    __file__,
                    "_one",
                    case_id,
                    str(run_dir),
                    model,
                    *([effort] if effort else []),
                ],
                stdout=handle,
                stderr=subprocess.STDOUT,
                check=False,
            )
        print(f"{case_id}: exit {done.returncode}", flush=True)

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        list(pool.map(one, pending))
    results = score_run(label)
    print((run_dir / "summary.md").read_text(encoding="utf-8"))
    print(f"run used {results.total_tokens + results.judge_tokens:,} tokens")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    source = p.add_mutually_exclusive_group()
    source.add_argument("--seed", type=Path, default=SEED_FILE)
    source.add_argument("--backup", type=Path)
    r = sub.add_parser("run")
    r.add_argument("label")
    r.add_argument("--cases-dir", type=Path, default=CASES_DIR)
    r.add_argument("--cases", default="")
    r.add_argument("--model", default=DEFAULT_MODEL)
    r.add_argument("--effort", choices=get_args(ClaudeEffort))
    r.add_argument("--jobs", type=int, default=4)
    s = sub.add_parser("score")
    s.add_argument("label")
    o = sub.add_parser("_one")
    o.add_argument("case")
    o.add_argument("run_dir", type=Path)
    o.add_argument("model")
    o.add_argument("effort", nargs="?")
    args = parser.parse_args()

    if args.command == "prepare":
        base = Path(os.environ["MYCELIUM_DATA_DIR"])
        if args.backup:
            prepare_backup(args.backup, base)
        else:
            prepare_seed(args.seed, base)
    elif args.command == "run":
        ids = [c for c in args.cases.split(",") if c]
        effort = CLAUDE_EFFORT.validate_python(args.effort) if args.effort else None
        _run(args.label, args.cases_dir, ids, args.model, effort, args.jobs)
    elif args.command == "score":
        print(json.dumps(score_run(args.label).metrics, indent=1))
    else:
        effort = CLAUDE_EFFORT.validate_python(args.effort) if args.effort else None
        run_one(args.case, args.run_dir, args.model, effort)


if __name__ == "__main__":
    main()
