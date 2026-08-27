"""Deterministically label funnel candidate pairs with NLI.

The ``nli`` extra is optional, and this module imports without it. The first
classification downloads the checkpoint to the Hugging Face cache. This module
never writes to the substrate, so no label ever auto-applies anything.
"""

from __future__ import annotations

import importlib.util
import math
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from mycelium.connect.funnel import BatchStatement, Candidate

LABELS = ("contradiction", "entailment", "neutral")
DEFAULT_MODEL = "cross-encoder/nli-deberta-v3-base"
DEFAULT_CONFIDENCE = 0.7
DEFAULT_MAX_PAIRS = 400


@dataclass(frozen=True)
class NliLabel:
    label: str
    confidence: float


class NliModel(Protocol):
    """Classify ordered premise and hypothesis pairs."""

    def classify(self, pairs: list[tuple[str, str]]) -> list[NliLabel]: ...


class NliUnavailable(RuntimeError):
    """Report that NLI inference cannot be used."""


def available() -> bool:
    """Return whether both optional NLI packages are importable."""
    transformers_spec = importlib.util.find_spec("transformers")
    torch_spec = importlib.util.find_spec("torch")
    return transformers_spec is not None and torch_spec is not None


def model_name() -> str:
    """Return the configured NLI checkpoint name."""
    return os.environ.get("MYCELIUM_NLI_MODEL") or DEFAULT_MODEL


def confidence_threshold() -> float:
    """Return the configured minimum NLI label confidence."""
    return float(os.environ.get("MYCELIUM_NLI_CONFIDENCE") or DEFAULT_CONFIDENCE)


def max_pairs() -> int:
    """Return the configured per-batch NLI pair budget."""
    configured = os.environ.get("MYCELIUM_NLI_MAX_PAIRS") or DEFAULT_MAX_PAIRS
    try:
        resolved = int(configured)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"NLI max pairs {configured!r} must be an integer of at least 2 "
            "because each candidate costs two pairs"
        ) from error
    if resolved < 2:
        raise ValueError(
            f"NLI max pairs {resolved!r} must be an integer of at least 2 "
            "because each candidate costs two pairs"
        )
    return resolved


def _resolve_model_name(configured_name: str | None) -> str:
    """Resolve an explicit checkpoint before consulting the environment."""
    return model_name() if configured_name is None else configured_name


def _torch():
    """Import torch, reporting an unusable installation as unavailable."""
    try:
        import torch  # local import: heavy optional nli dependency
    except (ImportError, OSError) as error:
        raise NliUnavailable(f"torch could not be imported: {error}") from error
    return torch


def _within_unit_range(value: float) -> bool:
    """Return whether a confidence is finite and between 0.0 and 1.0."""
    return math.isfinite(value) and 0.0 <= value <= 1.0


def _resolve_threshold(threshold: float | None) -> float:
    """Resolve an explicit threshold before consulting the environment."""
    resolved = confidence_threshold() if threshold is None else threshold
    if not _within_unit_range(resolved):
        raise ValueError(
            f"NLI confidence threshold {resolved!r} is not between 0.0 and 1.0"
        )
    return resolved


class TransformersNli:
    """Run a CPU cross-encoder over ``transformers``.

    The first non-empty classification downloads the checkpoint to the Hugging
    Face cache (``~/.cache/huggingface`` by default, or ``HF_HOME``).
    """

    def __init__(
        self,
        model_name: str | None = None,
        *,
        batch_size: int = 16,
        max_length: int = 256,
    ) -> None:
        if not available():
            raise NliUnavailable(
                "the nli extra is not installed; run `uv sync --extra nli`"
            )
        self._model_name = _resolve_model_name(model_name)
        self._batch_size = batch_size
        self._max_length = max_length
        self._tokenizer = None
        self._transformer = None
        self._id2label: dict[int, str] = {}
        self._load_lock = threading.Lock()

    @property
    def model_name(self) -> str:
        """Return the resolved checkpoint name."""
        return self._model_name

    def _load(self) -> None:
        """Load and validate the configured checkpoint once."""
        # ``_transformer`` is assigned last, so a non-None read means the
        # tokenizer and label map are already published to other threads.
        if self._transformer is not None:
            return
        # Concurrent tool calls reach this before the first load finishes; the
        # checkpoint is ~1GB, so a second in-flight load is a second copy in
        # memory and a second download.
        with self._load_lock:
            if self._transformer is None:
                self._load_checkpoint()

    def _load_checkpoint(self) -> None:
        """Fetch and validate the checkpoint, reporting any failure as unavailable."""
        try:
            from transformers import (  # local import: heavy optional nli dependency
                AutoModelForSequenceClassification,
                AutoTokenizer,
            )

            tokenizer = AutoTokenizer.from_pretrained(self._model_name)
            transformer = AutoModelForSequenceClassification.from_pretrained(
                self._model_name
            )
        except (ImportError, OSError) as error:
            # Callers degrade on NliUnavailable and only on that, so a missing
            # package, an absent checkpoint and a failed download must arrive
            # as one kind of failure.
            raise NliUnavailable(
                f"checkpoint {self._model_name!r} could not be loaded: {error}"
            ) from error
        transformer.eval()
        id2label = {
            int(label_id): str(label).strip().lower()
            for label_id, label in transformer.config.id2label.items()
        }
        if set(id2label.values()) != set(LABELS):
            raise NliUnavailable(
                f"checkpoint {self._model_name!r} reports labels "
                f"{sorted(id2label.values())}, expected {sorted(LABELS)}"
            )
        self._tokenizer = tokenizer
        self._id2label = id2label
        # Assigned last: `_load` reads this field outside the lock as the
        # "fully loaded" flag, so every other field must be set first.
        self._transformer = transformer

    def classify(self, pairs: list[tuple[str, str]]) -> list[NliLabel]:
        """Classify premise and hypothesis pairs in input order."""
        if not pairs:
            return []

        torch = _torch()
        self._load()
        labels: list[NliLabel] = []
        for start in range(0, len(pairs), self._batch_size):
            chunk = pairs[start : start + self._batch_size]
            premises = [premise for premise, _ in chunk]
            hypotheses = [hypothesis for _, hypothesis in chunk]
            inputs = self._tokenizer(
                premises,
                hypotheses,
                padding=True,
                truncation=True,
                max_length=self._max_length,
                return_tensors="pt",
            )
            with torch.no_grad():
                logits = self._transformer(**inputs).logits
                probabilities = torch.softmax(logits, dim=-1)
                confidences, label_ids = probabilities.max(dim=-1)
            labels.extend(
                NliLabel(self._id2label[label_id], float(confidence))
                for label_id, confidence in zip(
                    label_ids.tolist(), confidences.tolist(), strict=True
                )
            )
        return labels


_model: TransformersNli | None = None
_model_lock = threading.Lock()


def default_model() -> TransformersNli:
    """Return the process-wide default NLI model."""
    global _model
    with _model_lock:
        configured_model_name = model_name()
        if _model is None or _model.model_name != configured_model_name:
            _model = TransformersNli(configured_model_name)
        return _model


@dataclass(frozen=True)
class PairVerdict:
    new_index: int
    statement_id: str
    forward: NliLabel
    backward: NliLabel
    verdict: str
    score: float


def _verdict(
    statement: BatchStatement,
    candidate: Candidate,
    forward: NliLabel,
    backward: NliLabel,
    threshold: float,
) -> str:
    """Resolve confident directional labels to a proposal verdict."""
    entails_both_ways = (
        forward.label == "entailment"
        and forward.confidence >= threshold
        and backward.label == "entailment"
        and backward.confidence >= threshold
    )
    if entails_both_ways and statement.kind == candidate.kind:
        return "duplicate"
    contradicts = (
        forward.label == "contradiction" and forward.confidence >= threshold
    ) or (backward.label == "contradiction" and backward.confidence >= threshold)
    if contradicts:
        return "contradiction"
    return "related"


def _validate_labels(labels: list[NliLabel], pair_count: int) -> None:
    """Reject model output that cannot resolve to a trustworthy verdict."""
    if len(labels) != pair_count:
        raise ValueError(
            f"NLI model returned {len(labels)} labels for {pair_count} pairs"
        )
    for label in labels:
        if label.label not in LABELS:
            raise ValueError(
                f"NLI model returned unknown label {label.label!r}, "
                f"expected one of {sorted(LABELS)}"
            )
        if not _within_unit_range(label.confidence):
            raise ValueError(
                f"NLI model returned confidence {label.confidence!r} for label "
                f"{label.label!r}, which is not between 0.0 and 1.0"
            )


def classify_candidates(
    batch: list[BatchStatement],
    candidates: list[Candidate],
    model: NliModel,
    *,
    text_of: Callable[[str], str | None],
    threshold: float | None = None,
) -> list[PairVerdict]:
    """Classify funnel candidates as duplicate, contradiction, or related.

    Only confident bidirectional same-kind entailment proposes a duplicate;
    confident contradiction in either direction yields a contradiction verdict.
    All other results are demoted to related candidates.
    """
    resolved_threshold = _resolve_threshold(threshold)
    statements = {statement.index: statement for statement in batch}
    for candidate in candidates:
        if candidate.new_index not in statements:
            raise ValueError(
                f"candidate new_index {candidate.new_index} is absent from the batch"
            )

    surviving: list[tuple[Candidate, BatchStatement, str]] = []
    pairs: list[tuple[str, str]] = []
    for candidate in candidates:
        existing_text = text_of(candidate.statement_id)
        if existing_text is None:
            continue
        statement = statements[candidate.new_index]
        surviving.append((candidate, statement, existing_text))
        pairs.extend([(statement.text, existing_text), (existing_text, statement.text)])
    if not surviving:
        return []

    labels = model.classify(pairs)
    _validate_labels(labels, len(pairs))

    verdicts: list[PairVerdict] = []
    for offset, (candidate, statement, _) in enumerate(surviving):
        forward, backward = labels[offset * 2 : offset * 2 + 2]
        verdicts.append(
            PairVerdict(
                new_index=candidate.new_index,
                statement_id=candidate.statement_id,
                forward=forward,
                backward=backward,
                verdict=_verdict(
                    statement,
                    candidate,
                    forward,
                    backward,
                    resolved_threshold,
                ),
                score=candidate.score,
            )
        )
    return verdicts
