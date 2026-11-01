"""The calls the Loop workflow makes across its own services.

Accepting implementation starts a QA instruction run, and a finished QA run applies its instructions
to the QA Task, so QA and generation reference each other. Keeping those two calls in one object,
instead of assigning attributes after construction, means the cycle is visible in one place and a
service that is used before the composition root wired it fails with a clear error rather than an
``AttributeError``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..core.errors import ServiceUnavailable

StartGeneration = Callable[..., Any]
ApplyQaInstructions = Callable[..., Any]


class LoopWorkflowLinks:
    def __init__(self) -> None:
        self._start_generation: StartGeneration | None = None
        self._apply_qa_instructions: ApplyQaInstructions | None = None

    def bind(
        self,
        *,
        start_generation: StartGeneration,
        apply_qa_instructions: ApplyQaInstructions,
    ) -> None:
        self._start_generation = start_generation
        self._apply_qa_instructions = apply_qa_instructions

    @property
    def start_generation(self) -> StartGeneration | None:
        """``None`` when generation is unavailable, so acceptance never depends on a provider."""
        return self._start_generation

    @property
    def apply_qa_instructions(self) -> ApplyQaInstructions:
        if self._apply_qa_instructions is None:
            raise ServiceUnavailable("The Loop QA workflow is not initialised")
        return self._apply_qa_instructions
