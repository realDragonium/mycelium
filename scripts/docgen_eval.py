"""Run documentation-generation cases against a copy of a real data directory.

For evaluating docgen quality and token use after a change, by hand. It is not a
test and never runs in the test suite: it calls a live model and spends money.

    MYCELIUM_DATA_DIR=/path/to/data ANTHROPIC_API_KEY=... \
        uv run python scripts/docgen_eval.py cases.json OUT_DIR [--model ID]

`MYCELIUM_DATA_DIR` is only read: its databases are copied into OUT_DIR/data
and a private `mycelium-http` is started on that copy, so anchored cases never
revise a document from an earlier evaluation. Credentials, `OLLAMA_URL` and
the rest of the environment pass through to that server unchanged. Nothing is
delivered anywhere.

`cases.json` is a list of objects:

    {"name": "sso-explanation",                  # file name for the output
     "prompt": "Explain how ...",
     "guideline_set": "kb-authoring",             # optional
     "document_type": "explanation",              # optional
     "anchor": "Single Sign-On"}                  # optional entity name or alias

Per case it writes `<name>.md` (the document, or the refused draft) and
`<name>.json` (run row plus the run's full trace), then `summary.md` with
outcome, latency and tokens for every case.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import TypedDict

import httpx

POLL_S = 5.0
STARTUP_TIMEOUT_S = 900.0
RUN_TIMEOUT_S = 1800.0


class Case(TypedDict, total=False):
    name: str
    prompt: str
    guideline_set: str
    document_type: str
    anchor: str


def copy_data(source: Path, target: Path) -> None:
    target.mkdir(parents=True)
    for db in sorted(source.glob("*.db")):
        # The backup API gives a consistent copy even with a WAL beside it.
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as src:
            with sqlite3.connect(target / db.name) as dst:
                src.backup(dst)
    # Derived files; copying them skips a re-embed of the whole substrate.
    for name in ("*.vec", "entity-positions.json"):
        for path in source.glob(name):
            shutil.copy2(path, target / path.name)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


def start_server(data: Path, out: Path, port: int) -> subprocess.Popen[bytes]:
    env = {
        **os.environ,
        "MYCELIUM_DATA_DIR": str(data),
        "MYCELIUM_HTTP_HOST": "127.0.0.1",
        "MYCELIUM_HTTP_PORT": str(port),
        "MYCELIUM_AUTH": "off",
        "MYCELIUM_DOCGEN_TRACE_LOG": str(out / "trace.jsonl"),
    }
    log = (out / "server.log").open("wb")
    return subprocess.Popen(
        [sys.executable, "-c", "from mycelium.http import main; main()"],
        env=env,
        stdout=log,
        stderr=log,
    )


def wait_ready(client: httpx.Client, server: subprocess.Popen[bytes]) -> float:
    started = time.monotonic()
    while time.monotonic() - started < STARTUP_TIMEOUT_S:
        if server.poll() is not None:
            raise SystemExit("server exited during startup; see server.log")
        try:
            if client.get("/api/server-info").json().get("state") == "ready":
                return time.monotonic() - started
        except httpx.TransportError:
            pass
        time.sleep(1)
    raise SystemExit("server did not become ready; see server.log")


def select_model(client: httpx.Client, model: str) -> None:
    settings = client.get("/api/model-settings").raise_for_status().json()
    actions = settings["actions"] if "actions" in settings else settings
    docgen = next(a for a in actions if a["action"] == "docgen")
    client.patch(
        "/api/model-settings/docgen",
        json={
            "provider": "claude",
            "claude_model": model,
            "openai_model": docgen.get("openai_model") or "",
            "revision": docgen["revision"],
        },
    ).raise_for_status()


def entity_ids(client: httpx.Client) -> dict[str, str]:
    data = client.get("/api/data").raise_for_status().json()
    by_name = {e["name"].casefold(): e["id"] for e in data["entities"]}
    for name in data["names"]:
        if name.get("entity"):
            by_name.setdefault(name["text"].casefold(), name["entity"])
    return by_name


def run_case(
    client: httpx.Client, case: Case, entities: dict[str, str]
) -> dict[str, object]:
    anchor = case.get("anchor")
    anchor_id = entities[anchor.casefold()] if anchor else None
    run = (
        client.post(
            "/api/documentation/runs",
            json={
                "prompt": case["prompt"],
                "guideline_set": case.get("guideline_set"),
                "document_type": case.get("document_type"),
                "anchor_entity_id": anchor_id,
            },
        )
        .raise_for_status()
        .json()
    )
    started = time.monotonic()
    while run["finished_at"] is None:
        if time.monotonic() - started > RUN_TIMEOUT_S:
            raise SystemExit(f"{case['name']}: run {run['id']} did not finish")
        time.sleep(POLL_S)
        run = client.get(f"/api/documentation/runs/{run['id']}").raise_for_status()
        run = run.json()
    document = None
    if run["document_id"]:
        document = (
            client.get(f"/api/documentation/documents/{run['document_id']}")
            .raise_for_status()
            .json()
        )
    return {"run": run, "document": document}


def trace_for(out: Path, run_id: str) -> dict[str, object]:
    for line in (out / "trace.jsonl").read_text().splitlines():
        record: dict[str, object] = json.loads(line)
        if record.get("run_id") == run_id:
            return record
    raise SystemExit(f"no trace record for run {run_id}")


def summary_row(name: str, result: dict[str, object]) -> list[str]:
    run = result["run"]
    trace = result["trace"]
    assert isinstance(run, dict) and isinstance(trace, dict)
    tokens = trace["tokens"]
    grounding = trace.get("grounding") or {}
    return [
        name,
        str(run["document_type"]),
        str(run["status"]),
        f"{float(trace['latency_ms']) / 1000:.0f}",
        str(trace["model_turns"]),
        str(trace["op_count"]),
        str(tokens["input"]),
        str(tokens["cache_read"]),
        str(tokens["cache_creation"]),
        str(tokens["output"]),
        f"{grounding.get('cited_ids', 0)}/{grounding.get('retrieved_ids', 0)}",
        str(len(trace.get("declared_gaps") or [])),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("cases", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--model", help="Claude model for documentation runs")
    args = parser.parse_args()

    source = os.environ.get("MYCELIUM_DATA_DIR")
    if not source:
        raise SystemExit("set MYCELIUM_DATA_DIR to the data directory to evaluate")
    cases: list[Case] = json.loads(args.cases.read_text())
    out: Path = args.out
    if out.exists():
        raise SystemExit(f"{out} exists; choose a new output directory")
    out.mkdir(parents=True)
    copy_data(Path(source), out / "data")

    port = free_port()
    server = start_server(out / "data", out, port)
    rows: list[list[str]] = []
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=60) as client:
            print(f"server ready after {wait_ready(client, server):.0f}s")
            if args.model:
                select_model(client, args.model)
            entities = entity_ids(client)
            for case in cases:
                print(f"{case['name']}: running", flush=True)
                result = run_case(client, case, entities)
                run = result["run"]
                document = result["document"]
                assert isinstance(run, dict)
                result["trace"] = trace_for(out, str(run["id"]))
                body = (
                    document["body"]
                    if isinstance(document, dict)
                    else run.get("draft_body") or f"(no document)\n\n{run['error']}\n"
                )
                (out / f"{case['name']}.md").write_text(body)
                (out / f"{case['name']}.json").write_text(
                    json.dumps(result, indent=2) + "\n"
                )
                rows.append(summary_row(case["name"], result))
                print(" | ".join(rows[-1]), flush=True)
    finally:
        server.terminate()
        server.wait(timeout=60)

    header = [
        "case",
        "type",
        "status",
        "seconds",
        "turns",
        "ops",
        "input",
        "cache read",
        "cache write",
        "output",
        "cited/retrieved",
        "gaps",
    ]
    table = [header, ["---"] * len(header), *rows]
    (out / "summary.md").write_text(
        "\n".join("| " + " | ".join(row) + " |" for row in table) + "\n"
    )
    print(f"wrote {out / 'summary.md'}")


if __name__ == "__main__":
    main()
