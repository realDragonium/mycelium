"""Factual Ask events and cooperative cancellation shared by transports."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import Event
from typing import Literal, TypeVar

from pydantic import BaseModel, ConfigDict, JsonValue, model_validator
from pydantic_core import from_json


class AskEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal[
        "progress", "answer_delta", "answer_reset", "complete", "error", "cancelled"
    ]
    phase: Literal["retrieval", "evidence_check", "composition"] | None = None
    message: str | None = None
    text: str | None = None
    result: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def require_payload(self) -> AskEvent:
        if self.type == "progress" and (self.phase is None or not self.message):
            raise ValueError("Progress needs a phase and factual message")
        if self.type == "answer_delta" and not self.text:
            raise ValueError("An answer delta needs text")
        if self.type == "complete" and self.result is None:
            raise ValueError("Completion needs the structured result")
        if self.type in {"error", "cancelled"} and not self.message:
            raise ValueError("An unsuccessful stream needs an explicit message")
        return self


class AskCancelled(Exception):
    """Cancellation ends the run without a forced model finalization."""


@dataclass
class AskStream:
    emit: Callable[[AskEvent], None] | None = None
    cancelled: Event = field(default_factory=Event)
    started: float = field(default_factory=time.monotonic)
    timings: dict[str, float] = field(default_factory=dict)

    def check(self) -> None:
        if self.cancelled.is_set():
            raise AskCancelled("Ask cancelled")

    def send(self, event: AskEvent) -> None:
        self.check()
        key = {
            "progress": "first_progress_ms",
            "answer_delta": "first_answer_text_ms",
            "complete": "completion_ms",
        }.get(event.type)
        if self.emit:
            self.emit(event)
            if key:
                self.timings.setdefault(
                    key, round((time.monotonic() - self.started) * 1000, 2)
                )

    def progress(
        self, phase: Literal["retrieval", "evidence_check", "composition"], message: str
    ) -> None:
        self.send(AskEvent(type="progress", phase=phase, message=message))


current_stream: ContextVar[AskStream | None] = ContextVar("ask_stream", default=None)


@dataclass
class AnswerDeltas:
    stream: AskStream
    allowed: bool
    arguments: str = ""
    text: str = ""
    tool_id: str | None = None

    def receive(self, tool_id: str, name: str, delta: str) -> None:
        self.stream.check()
        if not self.allowed or name != "submit_answer":
            return
        if self.tool_id is None:
            self.tool_id = tool_id
            self.stream.progress(
                "composition", "Composing the answer from retrieved evidence."
            )
        if tool_id != self.tool_id:
            return
        self.arguments += delta
        try:
            partial = from_json(self.arguments, allow_partial="trailing-strings")
        except ValueError:
            return
        answer = partial.get("answer") if isinstance(partial, dict) else None
        if isinstance(answer, str) and answer.startswith(self.text):
            suffix = answer[len(self.text) :]
            if suffix:
                self.stream.send(AskEvent(type="answer_delta", text=suffix))
                self.text = answer

    def reset(self) -> None:
        if self.text:
            self.stream.send(
                AskEvent(
                    type="answer_reset",
                    message="The draft answer was not accepted; checking the result.",
                )
            )
            self.text = ""


Result = TypeVar("Result")


async def run_cancellable(run: Callable[[], Awaitable[Result]]) -> Result:
    """Tie a completed-result MCP request's cancellation to its worker loop."""
    stream = AskStream()
    token = current_stream.set(stream)
    try:
        return await run()
    finally:
        stream.cancelled.set()
        current_stream.reset(token)
