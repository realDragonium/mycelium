#!/usr/bin/env python
"""Clean up code-leaky behaviors in Mycelium.

Walks the substrate, flags behaviors whose text leaks implementation
detail (service/exception class names, internal verbs, SQL fragments),
and hands each suspect to a local Ollama model. The agent has the full
read+write MCP surface and may compose any cleanup it deems necessary —
rewrite, mention/link delta, split into atomic behaviors, annotation
extraction, delete, merge — by calling write tools whose effects are
queued as a plan. The operator reviews the planned actions per suspect
and approves, skips, or types feedback to revise.

Dry-run by default; pass `--apply` to flush approved plans against MCP.

Usage:
    uv run python scripts/cleanup_leaky_behaviors.py [flags]

Flags:
    --mcp-url URL       Mycelium HTTP endpoint (default: http://localhost:8765)
    --model MODEL       Ollama model with tool-calling support
                        (default: gemma4:e4b)
    --sample N          Investigate at most N suspects (0 = all). Default 20.
    --apply             Persist approved plans. Default is dry-run.
    --log FILE          JSONL log + checkpoint file (default: cleanup_log.jsonl)
    --dedup-threshold F Cosine threshold for the post-rewrite duplicate check.
                        Default 0.85.
    --max-revisions N   Max revision rounds per suspect when giving feedback.
                        Default 5.
    --verbose           Mirror log events to stderr.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Allow sibling-module imports when run as `python scripts/cleanup_leaky_behaviors.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent import investigate
from detector import find_candidates, is_leaky
from logger import Logger
from mcp_client import MyceliumClient
from plan import PlanRecorder
from state import CheckpointState


def _short(value: Any, n: int = 60) -> str:
    s = json.dumps(value, default=str) if not isinstance(value, str) else value
    s = s.replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def _format_action(idx: int, action: dict[str, Any]) -> str:
    """Render one queued action as a human-readable line."""
    name = action["name"]
    args = action["args"]
    syn = action.get("synthetic")
    head = f"  {idx}. {name}"
    if syn:
        head += f"  (→ {syn})"

    body_lines: list[str] = []
    if name == "replace_text":
        body_lines.append(f"     id:   {args.get('id')}")
        body_lines.append(f"     text: {_short(args.get('text', ''), 100)}")
    elif name == "upsert_behavior":
        body_lines.append(f"     id:   {args.get('id') or '(new)'}")
        body_lines.append(f"     text: {_short(args.get('text', ''), 100)}")
        if args.get("mentions"):
            body_lines.append(f"     mentions: {args['mentions']}")
        if args.get("links"):
            body_lines.append(f"     links: {args['links']}")
        if args.get("incoming_links"):
            body_lines.append(f"     incoming: {args['incoming_links']}")
    elif name in ("add_mentions", "remove_mentions"):
        body_lines.append(f"     id: {args.get('id')}  mentions: {args.get('mentions')}")
    elif name in ("add_links", "remove_links"):
        for link in args.get("links", []) or []:
            arrow = "→" if name == "add_links" else "↛"
            line = (
                f"     {link.get('from_behavior_id')} {arrow} "
                f"{link.get('to_behavior_id')}  [{link.get('link_type')}]"
            )
            if "when" in link:
                line += f"  when={json.dumps(link['when'], default=str)}"
            body_lines.append(line)
    elif name == "delete_behavior":
        body_lines.append(f"     id: {args.get('id')}")
    elif name == "merge_behaviors":
        body_lines.append(
            f"     {args.get('from_behavior_id')} → {args.get('into_behavior_id')}"
        )
    elif name == "upsert_entity":
        body_lines.append(f"     name: {args.get('name')}  desc: {_short(args.get('description', ''), 60)}")
    elif name == "upsert_annotation":
        body_lines.append(f"     kind: {args.get('kind')}  text: {_short(args.get('text', ''), 80)}")
        if args.get("behavior_ids"):
            body_lines.append(f"     attached behaviors: {args['behavior_ids']}")
        if args.get("entity_ids"):
            body_lines.append(f"     attached entities: {args['entity_ids']}")
    else:
        body_lines.append(f"     args: {_short(args, 100)}")
    return "\n".join([head, *body_lines])


def _texts_in_plan(actions: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Return (action_label, text) pairs for any planned action that
    introduces or rewrites a behavior's text. Used to drive the dedup check."""
    out: list[tuple[str, str]] = []
    for a in actions:
        if a["name"] == "replace_text":
            out.append((f"replace_text({a['args'].get('id')})", a["args"].get("text", "")))
        elif a["name"] == "upsert_behavior":
            label = f"upsert_behavior({a.get('synthetic') or a['args'].get('id')})"
            out.append((label, a["args"].get("text", "")))
    return out


def _dedup_hit(
    mcp: MyceliumClient, text: str, exclude_ids: set[str], threshold: float
) -> dict | None:
    if not text.strip():
        return None
    hits = mcp.search_behaviors(text, limit=3, min_score=threshold)
    for hit in hits:
        if hit["id"] not in exclude_ids:
            return hit
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--mcp-url", default="http://localhost:8765")
    parser.add_argument("--model", default="gemma4:e4b")
    parser.add_argument("--sample", type=int, default=20)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--log", default="cleanup_log.jsonl")
    parser.add_argument("--dedup-threshold", type=float, default=0.85)
    parser.add_argument("--max-revisions", type=int, default=5)
    parser.add_argument(
        "--detect-only",
        action="store_true",
        help=(
            "Run the heuristic detector and print suspect ids + text, "
            "then exit. No agent, no plan, no writes. Useful as a "
            "complement to grep_behaviors during maintenance audits."
        ),
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    mcp = MyceliumClient(args.mcp_url)
    logger = Logger(args.log, verbose=args.verbose)
    checkpoint = CheckpointState(args.log)

    logger.log(
        "session_start",
        mcp_url=args.mcp_url,
        model=args.model,
        sample=args.sample,
        apply=args.apply,
        already_settled=len(checkpoint._done),
    )

    print(f"Scanning substrate for leaky behaviors via {args.mcp_url}…")
    candidates = find_candidates(
        mcp, sample=args.sample if args.sample > 0 else None
    )
    print(f"Found {len(candidates)} suspect(s).")
    logger.log("detection_complete", count=len(candidates))

    if args.detect_only:
        # Print machine-readable id\ttext lines so this can be piped to
        # other audits (e.g. `| awk -F\\t '{print $1}'` for ids only).
        # No further agent work, no checkpoint mutation.
        for c in candidates:
            print(f"{c['id']}\t{c['text']}")
        return

    counts = {"applied": 0, "skipped": 0, "errors": 0}

    for i, candidate in enumerate(candidates, 1):
        bid = candidate["id"]
        text = candidate["text"]

        if checkpoint.is_done(bid):
            print(f"[{i}/{len(candidates)}] {bid} — already settled, skipping.")
            continue

        print(f"\n[{i}/{len(candidates)}] {bid}")
        print(f"  text: {text}")
        logger.log("investigating", behavior_id=bid, text=text)

        # Per-suspect state machine. A fresh PlanRecorder is created on
        # each investigate() call so revisions naturally discard the
        # previous plan.
        followup: str | None = None
        revisions = 0
        terminal: str | None = None

        while terminal is None and revisions <= args.max_revisions:
            recorder = PlanRecorder(mcp)
            try:
                decision = investigate(
                    bid,
                    text,
                    mcp=recorder,
                    model=args.model,
                    logger=logger,
                    user_followup=followup,
                )
            except Exception as e:
                logger.log(
                    "error_terminal",
                    behavior_id=bid,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                print(f"  ERROR: {type(e).__name__}: {e}", file=sys.stderr)
                terminal = "error"
                break
            followup = None

            status = decision.get("status")

            if status == "skip":
                reason = decision.get("reason", "")
                print(f"  → skip: {reason}")
                logger.log("skipped", behavior_id=bid, reason=reason)
                terminal = "skip"
                break

            if status == "needs-input":
                question = decision.get("question", "(no question)")
                print(f"\n  Model needs clarification:")
                print(f"  Q: {question}")
                answer = input("  Your answer (blank to skip suspect): ").strip()
                if not answer:
                    logger.log(
                        "skipped",
                        behavior_id=bid,
                        reason="user declined to answer",
                    )
                    terminal = "skip"
                    break
                logger.log(
                    "user_clarification",
                    behavior_id=bid,
                    question=question,
                    answer=answer,
                )
                followup = answer
                revisions += 1
                continue

            if status != "done":
                print(f"  → unexpected status {status!r}; skipping.")
                logger.log("skipped", behavior_id=bid, reason=f"status={status}")
                terminal = "skip"
                break

            # status == "done"
            summary = decision.get("summary", "(no summary)")
            actions = recorder.actions

            if not actions:
                # The agent declared "done" but enacted nothing. Usually
                # the summary describes a recommendation it forgot to
                # execute (e.g. "Deleted X" without calling
                # delete_behavior). Send it back with a corrective
                # prompt instead of silently skipping.
                print(f"  → agent reported done but recorded no actions.")
                print(f"     summary: {summary}")
                logger.log(
                    "done_with_empty_plan", behavior_id=bid, summary=summary
                )
                revisions += 1
                if revisions > args.max_revisions:
                    print(
                        f"  Max revisions ({args.max_revisions}) reached "
                        f"without enactment; skipping."
                    )
                    logger.log(
                        "skipped",
                        behavior_id=bid,
                        reason="empty plan after max revisions",
                        summary=summary,
                    )
                    terminal = "skip"
                    break
                print(f"  → asking agent to reconcile (round {revisions}/{args.max_revisions})…")
                followup = (
                    f"You returned status=\"done\" with this summary:\n"
                    f"  {summary}\n\n"
                    "But you did NOT make any tool calls in this round. "
                    "The summary is supposed to describe what you DID, "
                    "not what you recommend.\n\n"
                    "You must do ONE of the following:\n"
                    "  (a) If the change you summarised is correct, "
                    "actually enact it now by calling the appropriate "
                    "write tools (delete_behavior, replace_text, "
                    "upsert_behavior, add_links, etc.), then return "
                    "status=\"done\" with a summary that matches.\n"
                    "  (b) If the suspect should not be changed, return "
                    "status=\"skip\" with a reason.\n"
                    "  (c) If you're uncertain, return "
                    "status=\"needs-input\" with a specific question.\n\n"
                    "Returning status=\"done\" with no tool calls is invalid."
                )
                continue

            print(f"\n  Agent summary: {summary}")
            print(f"  Planned actions ({len(actions)}):")
            for idx, action in enumerate(actions, 1):
                print(_format_action(idx, action))

            plan_warnings = recorder.validate()
            if plan_warnings:
                print("\n  Plan warnings:")
                for w in plan_warnings:
                    print(f"    ⚠ {w}")
                logger.log(
                    "plan_warnings", behavior_id=bid, warnings=plan_warnings
                )

            # Dedup check on any new or rewritten text in the plan.
            text_actions = _texts_in_plan(actions)
            exclude = {bid}
            warnings: list[str] = []
            for label, t in text_actions:
                hit = _dedup_hit(
                    mcp, t, exclude, args.dedup_threshold
                )
                if hit:
                    warnings.append(
                        f"{label} → near-duplicate of {hit['id']} "
                        f"(score={hit['score']:.3f}): {_short(hit['text'], 80)}"
                    )
                    logger.log(
                        "dedup_hit",
                        behavior_id=bid,
                        action_label=label,
                        candidate_id=hit["id"],
                        score=hit["score"],
                    )
            if warnings:
                print("\n  Possible duplicates:")
                for w in warnings:
                    print(f"    - {w}")

            # Heuristic warning if any rewrite text still looks leaky.
            for label, t in text_actions:
                if is_leaky(t):
                    print(f"  WARN: {label} text still looks leaky.")
                    logger.log(
                        "rewrite_still_leaky",
                        behavior_id=bid,
                        action_label=label,
                        text=t,
                    )

            # Prompt loop: y/n/f must be entered explicitly. Anything else
            # re-prompts rather than silently triggering a costly revision.
            choice: str = ""
            feedback_text: str = ""
            while True:
                print("\n  [y]apply  [n]skip  [f]give feedback to revise")
                raw = input("  > ").strip().lower()
                if raw in ("y", "yes", "apply"):
                    choice = "apply"
                    break
                if raw in ("n", "no", "skip"):
                    choice = "skip"
                    break
                if raw in ("f", "feedback"):
                    feedback_text = input("  Feedback: ").strip()
                    if not feedback_text:
                        print("  Empty feedback. Choose y, n, or f.")
                        continue
                    choice = "feedback"
                    break
                print(f"  Unrecognized {raw!r}. Press y, n, or f.")

            if choice == "apply":
                logger.log(
                    "plan_approved",
                    behavior_id=bid,
                    summary=summary,
                    actions=actions,
                    applied=args.apply,
                )
                if args.apply:
                    results = recorder.flush()
                    # Two failure shapes: the call raised (caught in flush
                    # → "error" key) OR the substrate returned a soft
                    # rejection like {"rejected": True, "violations": [...]}
                    # (HTTP 200, no exception). Both must be surfaced or
                    # the operator may end up with a half-applied plan.
                    failed: list[dict] = []
                    for r in results:
                        if "error" in r:
                            failed.append(r)
                        elif isinstance(r.get("result"), dict) and r["result"].get("rejected"):
                            failed.append(
                                {
                                    "action": r["action"],
                                    "error": "rejected by substrate: "
                                    + json.dumps(r["result"].get("violations", []))[:300],
                                }
                            )
                    succeeded = len(results) - len(failed)
                    logger.log(
                        "applied",
                        behavior_id=bid,
                        results=results,
                        failed=len(failed),
                        succeeded=succeeded,
                    )
                    if failed:
                        print(
                            f"  ⚠ partial apply: {succeeded} succeeded, "
                            f"{len(failed)} failed"
                        )
                        for r in failed:
                            print(f"      {r['action']}: {r['error']}")
                        print(
                            "  This plan is now half-applied. Inspect the "
                            "substrate manually before continuing — "
                            "earlier actions in the plan (e.g. delete_behavior) "
                            "may have succeeded while the replacement was rejected."
                        )
                    else:
                        print(f"  ✓ applied {len(results)} action(s)")
                else:
                    print(f"  (dry-run) would apply {len(actions)} action(s)")
                    logger.log("proposed", behavior_id=bid, actions=actions)
                terminal = "applied"
                break

            if choice == "skip":
                logger.log(
                    "skipped", behavior_id=bid, reason="user rejected plan"
                )
                terminal = "skip"
                break

            # choice == "feedback": send back to agent for revision.
            revisions += 1
            if revisions > args.max_revisions:
                print(
                    f"  Max revisions ({args.max_revisions}) reached; skipping."
                )
                logger.log(
                    "skipped",
                    behavior_id=bid,
                    reason="max revisions reached",
                )
                terminal = "skip"
                break

            logger.log(
                "user_feedback",
                behavior_id=bid,
                prior_summary=summary,
                prior_actions=actions,
                feedback=feedback_text,
                revision=revisions,
            )
            print(f"  → revising (round {revisions}/{args.max_revisions})…")
            # Deliberately do NOT pass the prior action list to the agent.
            # Small models tend to re-emit listed tool calls verbatim
            # instead of treating them as discarded, producing duplicate
            # writes and references to pending ids that no longer exist
            # in the freshly-reset recorder. The summary alone gives the
            # agent enough memory of "what I tried" without that
            # template-copy hazard.
            followup = (
                f"On a previous attempt at this suspect you concluded:\n"
                f"  {summary}\n\n"
                f"The operator was not satisfied. Their feedback:\n"
                f"  {feedback_text}\n\n"
                "Start over from scratch. The previous plan is fully "
                "discarded — do NOT call any tool just because you called "
                "it last round; the only writes that count are the new "
                "ones you make now. Re-investigate the graph as needed "
                "and produce a fresh plan that addresses the feedback."
            )

        if terminal == "applied":
            counts["applied"] += 1
        elif terminal == "error":
            counts["errors"] += 1
        else:
            counts["skipped"] += 1
        checkpoint.mark_done(bid)

    print("\n" + "=" * 60)
    print(
        f"summary: {counts['applied']} applied, "
        f"{counts['skipped']} skipped, {counts['errors']} errors"
    )
    if not args.apply:
        print("(dry-run — pass --apply to persist)")
    logger.log("session_end", **counts, apply=args.apply)


if __name__ == "__main__":
    main()
