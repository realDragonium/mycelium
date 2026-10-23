"""Run Ask over the evaluation questions and score its answers.

Not part of the pytest run: it calls the model and needs a prepared data
directory. The committed questions live in `tests/ask_eval/cases.toml` and are
answered from the invented knowledge base in `tests/ask_eval/seed.toml`;
scoring rules are in `ask_eval_scoring.py` (pure, unit-tested). A case
directory outside the repo (`--cases-dir`) can be run against any other
prepared data directory, such as a local copy of real data; such cases name
expected facts by statement id instead of seed key.

Environment:
    MYCELIUM_DATA_DIR   a prepared base data directory (see `prepare`); a run
                        answers every question from one fresh copy of it
    ANTHROPIC_API_KEY   for the Ask model and the judge
    OLLAMA_URL          embeddings (nomic-embed-text), default localhost:11434

Usage:
    ask_eval.py prepare [--seed FILE | --backup DIR]
    ask_eval.py run LABEL [--cases-dir DIR] [--cases a,b] [--model M]
                          [--depth standard|quick] [--jobs N]
    ask_eval.py score LABEL               # re-score a finished run

Results go to ~/mycelium-eval/ask-results/LABEL/ (override with
MYCELIUM_EVAL_RESULTS): one raw JSON per case, `results.json`, `summary.md`.

The judge grades each answer against the statements the run retrieved, the
expected facts and the must-not claims. Model and prompt are fixed in
`ask_eval_scoring`; answers are cached by prompt hash, so re-scoring a run is
deterministic and free.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import tomllib
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING

import ask_eval_scoring as scoring
from pydantic import BaseModel, ConfigDict, JsonValue

import ingest_eval

if TYPE_CHECKING:
    from mycelium.ask.substrate import ToolSpec

REPO = Path(__file__).resolve().parents[1]
CASES_DIR = REPO / "tests" / "ask_eval"
SEED_FILE = CASES_DIR / "seed.toml"
RESULTS = Path(
    os.environ.get("MYCELIUM_EVAL_RESULTS")
    or Path.home() / "mycelium-eval" / "ask-results"
)
DEFAULT_MODEL = "claude-haiku-4-5"
JUDGE_MODEL = "claude-sonnet-5-5"


def load_cases(cases_dir: Path, seed_ids: Mapping[str, str]) -> list[scoring.Case]:
    def resolve(ref: str) -> str:
        if ref in seed_ids:
            return seed_ids[ref]
        if ref.startswith("stm_"):
            return ref
        raise ValueError(f"unknown fact {ref!r}: not a seed key or statement id")

    cases: list[scoring.Case] = []
    for path in sorted(cases_dir.glob("*.toml")):
        if path.name != SEED_FILE.name:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            cases.extend(scoring.parse_cases(data, resolve))
    return cases


class RunSpec(BaseModel):
    """What a run was against, kept beside its results so `score` can redo it."""

    cases_dir: Path
    seed_ids: dict[str, str] = {}
    model: str
    depth: str

    @classmethod
    def load(cls, run_dir: Path) -> RunSpec:
        return cls.model_validate_json((run_dir / "run.json").read_text("utf-8"))

    def cases(self) -> dict[str, scoring.Case]:
        return {c.id: c for c in load_cases(self.cases_dir, self.seed_ids)}


# --------------------------------------------------------------------------- #
# Data directory
# --------------------------------------------------------------------------- #


def prepare_seed(seed_file: Path, base: Path) -> None:
    ingest_eval.prepare_seed(seed_file, base)
    # Aliases are attached after their statements exist, so their mentions sit
    # in the recompute queue; Ask resolves aliases through those mentions.
    from mycelium import mention_worker
    from mycelium.server.runtime import _db

    print(f"recomputed mentions for {mention_worker.drain(_db())} statements")


def _init_copy(base: Path, target: Path) -> None:
    shutil.copytree(base, target, ignore=shutil.ignore_patterns("*-wal", "*-shm"))
    ingest_eval._quiet_environment()
    os.environ["MYCELIUM_DISABLE_AUDIENCE_WORKER"] = "1"
    from mycelium import prompt_store
    from mycelium.server import startup

    startup.init(target)
    # Evaluate the instructions shipped in this checkout, not a saved copy.
    prompt_store.connection().execute(
        "UPDATE prompt_texts SET deleted = 1 WHERE type = 'doctrine' AND name = 'ask'"
    )
    prompt_store.connection().commit()


# --------------------------------------------------------------------------- #
# Running
# --------------------------------------------------------------------------- #


def _statements(ids: list[str]) -> dict[str, dict[str, JsonValue]]:
    from mycelium import server

    found: dict[str, dict[str, JsonValue]] = {}
    for start in range(0, len(ids), 50):
        result = server.get_statements(ids=ids[start : start + 50])
        for record in result["statements"]:
            found[str(record["id"])] = dict(record)
    return found


def _evidence(refs: Mapping[str, str]) -> list[dict[str, JsonValue]]:
    """What the run supplied to the model, with links named by ref."""
    records = _statements(list(refs.values()))
    ref_of = {sid: ref for ref, sid in refs.items()}
    texts = {sid: str(r.get("text")) for sid, r in records.items()}

    def label(sid: str) -> str:
        return ref_of.get(sid) or f'"{texts.get(sid, sid)}"'

    out: list[dict[str, JsonValue]] = []
    for ref, sid in sorted(refs.items(), key=lambda item: int(item[0][1:])):
        record = records.get(sid, {})
        links = record.get("links")
        out.append(
            {
                "ref": ref,
                "id": sid,
                "text": f"[{record.get('kind')}] {record.get('text')}",
                "links": list(
                    scoring.render_links(
                        [link for link in links if isinstance(link, dict)]
                        if isinstance(links, list)
                        else [],
                        label,
                    )
                ),
            }
        )
    return out


class _Recording:
    """The in-process substrate, keeping every entity record a read returned:
    entity descriptions are evidence too, though they cannot be cited."""

    def __init__(self) -> None:
        from mycelium.ask.substrate import InProcessSubstrate

        self._inner = InProcessSubstrate()
        self.entities: dict[str, str] = {}

    def tool_specs(self) -> list[ToolSpec]:
        return self._inner.tool_specs()

    def has(self, name: str) -> bool:
        return self._inner.has(name)

    def call(self, name: str, arguments: dict[str, object]) -> object:
        result = self._inner.call(name, arguments)
        self._collect(result)
        return result

    def _collect(self, value: object) -> None:
        if isinstance(value, dict):
            eid, description = value.get("id"), value.get("description")
            if isinstance(eid, str) and eid.startswith("ent_") and description:
                self.entities[eid] = f"[entity] {value.get('name')}: {description}"
            for item in value.values():
                self._collect(item)
        elif isinstance(value, list):
            for item in value:
                self._collect(item)


def run_case(case: scoring.Case, run_dir: Path, model: str, depth: str) -> None:
    from mycelium.ask import AskConfig, run_ask
    from mycelium.ask.config import for_depth

    config = for_depth(
        dataclasses.replace(
            AskConfig.from_env(),
            provider="claude",
            model=model,
            reasoning_effort=None,
            trace_log_path=None,
            trace_dir="",
        ),
        depth,
    )
    started = time.monotonic()
    record: dict[str, JsonValue]
    substrate = _Recording()
    try:
        result = run_ask(case.question, config=config, substrate=substrate)
        data = result.model_dump(mode="json")
        refs = data["trace"].get("evidence_refs") or {}
        entities: list[JsonValue] = [
            {"ref": f"e{i}", "id": eid, "text": text}
            for i, (eid, text) in enumerate(sorted(substrate.entities.items()), 1)
        ]
        record = {"result": data, "evidence": _evidence(refs) + entities}
    except Exception as exc:  # noqa: BLE001 — a failed case is a result
        record = {"error": f"{type(exc).__name__}: {exc}"}
    record |= {
        "case": case.id,
        "model": model,
        "elapsed_s": round(time.monotonic() - started, 1),
        "fact_texts": {
            sid: str(r.get("text")) for sid, r in _statements(list(case.facts)).items()
        },
    }
    (run_dir / f"{case.id}.raw.json").write_text(
        json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    print(f"{case.id}: {record.get('error') or 'done'}", flush=True)


def _run(
    label: str,
    cases_dir: Path,
    case_ids: list[str],
    model: str,
    depth: str,
    jobs: int,
) -> None:
    run_dir = RESULTS / label
    run_dir.mkdir(parents=True, exist_ok=True)
    base = Path(os.environ["MYCELIUM_DATA_DIR"])
    seed_ids = base / ingest_eval.SEED_IDS
    spec = RunSpec(
        cases_dir=cases_dir.resolve(),
        seed_ids=json.loads(seed_ids.read_text("utf-8")) if seed_ids.exists() else {},
        model=model,
        depth=depth,
    )
    (run_dir / "run.json").write_text(spec.model_dump_json(indent=1), "utf-8")
    cases = spec.cases()
    pending = [
        case
        for case_id, case in cases.items()
        if (not case_ids or case_id in case_ids)
        and not (run_dir / f"{case_id}.raw.json").exists()
    ]
    if pending:
        with tempfile.TemporaryDirectory(prefix="ask-eval-") as tmp:
            _init_copy(base, Path(tmp) / "data")
            with ThreadPoolExecutor(max_workers=jobs) as pool:
                list(pool.map(lambda c: run_case(c, run_dir, model, depth), pending))
    results = score_run(label)
    print((run_dir / "summary.md").read_text(encoding="utf-8"))
    print(f"run cost ${results.cost_usd + results.judge_cost_usd:.2f}")


# --------------------------------------------------------------------------- #
# Judge
# --------------------------------------------------------------------------- #


class _Stored(BaseModel):
    judgement: scoring.Judgement
    input_tokens: int
    output_tokens: int


def judge(
    case: scoring.Case, seen: scoring.Observed
) -> tuple[scoring.Judgement, float]:
    """The judge's verdict, and what it cost (0 when cached)."""
    prompt = scoring.judge_prompt(case, seen)
    digest = hashlib.sha256(
        f"{JUDGE_MODEL}\n{scoring.JUDGE_SYSTEM}\n{prompt}".encode()
    ).hexdigest()
    cache = RESULTS / "judge-cache" / f"{digest}.json"
    if cache.exists():
        stored = _Stored.model_validate_json(cache.read_text(encoding="utf-8"))
        return stored.judgement, 0.0
    import anthropic

    response = anthropic.Anthropic().messages.parse(
        model=JUDGE_MODEL,
        max_tokens=8000,
        system=scoring.JUDGE_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_format=scoring.Judgement,
    )
    if response.parsed_output is None:
        raise RuntimeError(f"judge returned no result for {case.id}")
    stored = _Stored(
        judgement=response.parsed_output,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(stored.model_dump_json(indent=1), encoding="utf-8")
    return stored.judgement, _cost(
        JUDGE_MODEL,
        _Tokens(input=stored.input_tokens, output=stored.output_tokens),
    )


# --------------------------------------------------------------------------- #
# Scoring a run
# --------------------------------------------------------------------------- #


class _View(BaseModel):
    """Read-side view of a raw record: only the fields scoring uses."""

    model_config = ConfigDict(extra="ignore")


class _Tokens(_View):
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_creation: int = 0


class _Trace(_View):
    latency_ms: float = 0
    model_turns: int = 0
    op_count: int = 0
    forced_finalize: str | None = None
    tokens: _Tokens = _Tokens()


class _Result(_View):
    outcome: str
    answer: str = ""
    confidence: str | None = None
    gaps: list[str] = []
    provenance: list[str] = []
    trace: _Trace = _Trace()


class _Evidence(_View):
    ref: str
    id: str
    text: str
    links: list[str] = []


class _Record(_View):
    case: str
    model: str
    elapsed_s: float
    error: str | None = None
    result: _Result | None = None
    evidence: list[_Evidence] = []
    fact_texts: dict[str, str] = {}


def _cost(model: str, tokens: _Tokens) -> float:
    from mycelium.ai import Usage, pricing

    price = pricing.price("claude", model)
    if price is None:
        raise SystemExit(f"no list price for {model}")
    return price.cost_usd(
        Usage(
            input_tokens=tokens.input,
            output_tokens=tokens.output,
            cache_read_input_tokens=tokens.cache_read,
            cache_creation_input_tokens=tokens.cache_creation,
        )
    )


def _observed(record: _Record) -> scoring.Observed:
    result = record.result
    assert result is not None
    return scoring.Observed(
        outcome=result.outcome,
        answer=result.answer,
        gaps=tuple(result.gaps),
        provenance=tuple(result.provenance),
        evidence=tuple(
            scoring.EvidenceRecord(e.ref, e.id, e.text, tuple(e.links))
            for e in record.evidence
        ),
        fact_texts=record.fact_texts,
    )


class CaseResult(BaseModel):
    case: str
    categories: list[str]
    outcome: str
    confidence: str | None
    latency_s: float
    model_turns: int
    ops: int
    forced_finalize: str | None
    tokens: _Tokens
    cost_usd: float
    score: dict[str, float | int | bool | None]
    judgement: scoring.Judgement | None


class RunResults(BaseModel):
    label: str
    model: str
    depth: str
    cases: int
    errors: list[str]
    metrics: dict[str, float | None]
    by_category: dict[str, float | None]
    cost_usd: float
    judge_cost_usd: float
    latency_s_median: float | None
    latency_s_max: float | None
    per_case: list[CaseResult]


def score_run(label: str) -> RunResults:
    run_dir = RESULTS / label
    spec = RunSpec.load(run_dir)
    cases = spec.cases()
    per_case: list[CaseResult] = []
    scores: list[scoring.CaseScore] = []
    errors: list[str] = []
    judge_cost = 0.0
    for path in sorted(run_dir.glob("*.raw.json")):
        record = _Record.model_validate_json(path.read_text(encoding="utf-8"))
        case = cases[record.case]
        if record.result is None:
            errors.append(f"{case.id}: {record.error}")
            continue
        seen = _observed(record)
        verdict = None
        if seen.outcome == "answered":
            verdict, spent = judge(case, seen)
            judge_cost += spent
        score = scoring.score_case(case, seen, verdict)
        scores.append(score)
        trace = record.result.trace
        per_case.append(
            CaseResult(
                case=case.id,
                categories=list(case.categories),
                outcome=seen.outcome,
                confidence=record.result.confidence,
                latency_s=round(trace.latency_ms / 1000, 1),
                model_turns=trace.model_turns,
                ops=trace.op_count,
                forced_finalize=trace.forced_finalize,
                tokens=trace.tokens,
                cost_usd=round(_cost(record.model, trace.tokens), 4),
                score=dataclasses.asdict(score),
                judgement=verdict,
            )
        )
    categories = sorted({c for r in per_case for c in r.categories})
    by_category = {
        name: scoring.aggregate(
            [s for s, r in zip(scores, per_case, strict=True) if name in r.categories]
        )["fact_recall"]
        for name in categories
        if name != "unanswerable"
    }
    latencies = sorted(c.latency_s for c in per_case)
    results = RunResults(
        label=label,
        model=spec.model,
        depth=spec.depth,
        cases=len(per_case),
        errors=errors,
        metrics=scoring.aggregate(scores),
        by_category=by_category,
        cost_usd=round(sum(c.cost_usd for c in per_case), 3),
        judge_cost_usd=round(judge_cost, 3),
        latency_s_median=latencies[len(latencies) // 2] if latencies else None,
        latency_s_max=latencies[-1] if latencies else None,
        per_case=per_case,
    )
    (run_dir / "results.json").write_text(
        results.model_dump_json(indent=1), encoding="utf-8"
    )
    (run_dir / "summary.md").write_text(_summary(results), encoding="utf-8")
    return results


def _fmt(value: float | int | bool | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return f"{value:.2f}" if isinstance(value, float) else str(value)


def _summary(results: RunResults) -> str:
    lines = [
        f"# Ask eval: {results.label}",
        "",
        f"{results.cases} cases on {results.model} ({results.depth}), ask "
        f"${results.cost_usd:.2f}, judge ${results.judge_cost_usd:.2f}, latency "
        f"median {results.latency_s_median}s / max {results.latency_s_max}s",
        *(f"- error: {e}" for e in results.errors),
        "",
        "| metric | value |",
        "|---|---|",
        *(f"| {k} | {_fmt(v)} |" for k, v in results.metrics.items()),
        *(f"| fact_recall:{k} | {_fmt(v)} |" for k, v in results.by_category.items()),
        "",
        "| case | outcome | conf | forced | turns | ops | recall | cited "
        "| claims | unsup | cite prec | must-not | refusal | conflict | $ | s |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in results.per_case:
        s = c.score
        refusal = (
            s["correct_refusal"]
            if s["false_refusal"] is None
            else ("false" if s["false_refusal"] else None)
        )
        lines.append(
            f"| {c.case} | {c.outcome} | {c.confidence or ''} | "
            f"{c.forced_finalize or ''} | {c.model_turns} | {c.ops} | "
            f"{_fmt(s['fact_recall'])} | {_fmt(s['cited_recall'])} | "
            f"{s['claims']} | {s['unsupported_claims']} | "
            f"{_fmt(s['citation_precision'])} | {s['must_not_violations']} | "
            f"{_fmt(refusal)} | {_fmt(s['conflict_flagged'])} | "
            f"{c.cost_usd:.3f} | {c.latency_s} |"
        )
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


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
    r.add_argument("--depth", choices=["standard", "quick"], default="standard")
    r.add_argument("--jobs", type=int, default=4)
    s = sub.add_parser("score")
    s.add_argument("label")
    args = parser.parse_args()

    if args.command == "prepare":
        base = Path(os.environ["MYCELIUM_DATA_DIR"])
        if args.backup:
            ingest_eval.prepare_backup(args.backup, base)
        else:
            prepare_seed(args.seed, base)
    elif args.command == "run":
        ids = [c for c in args.cases.split(",") if c]
        _run(args.label, args.cases_dir, ids, args.model, args.depth, args.jobs)
    else:
        results = score_run(args.label)
        print(json.dumps(results.metrics, indent=1))
        sys.stdout.flush()


if __name__ == "__main__":
    main()
