"""Bounded, durable generation runs for analysis, RoadMap and QA instructions.

The provider call never runs inside a board transaction. Inputs are captured first, the external
call happens outside any lock, and the result is only promoted when the captured revisions are
still current.

``LoopGenerationService`` reaches the board database only through the board unit of work and the
registry only through the registry unit of work; it takes the provider call, the clock and the id
source as arguments, and runs a run inline when it is built with ``background=False``, so every
rule here runs in a unit test without a database, a thread or a network.

The prompt and its contract live in ``loop_generation_prompts``, the choice of agent in
``loop_generation_agents`` and a run's record and steps in ``loop_generation_runs``; this module
keeps the service and the import path, and re-exports what callers import from it.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from pydantic import JsonValue

from ..core.context import ActorContext
from ..core.dates import iso_utc
from ..core.errors import ApiError, Conflict, NotFound
from ..core.logging import carry_request_id
from ..db.generated.board import LoopGenerationRunsRow, LoopsRow
from ..db.generated.registry import AgentsRow, BoardsRow
from ..repositories.board import BoardUnitOfWork
from ..repositories.errors import ConstraintViolationError
from ..repositories.registry import RegistryUnitOfWork
from ..schemas.loops import GenerationRequest
from . import runtime
from .idempotency import remember, request_fingerprint, stored_answer
from .loop_documents import LoopDocumentService
from .loop_generation_agents import (
    PreferredAgents,
    RolePrompt,
    RoleSource,
    resolve_agent,
    role_prompt,
)
from .loop_generation_prompts import (
    FENCE,
    MAX_OUTPUT_CHARS,
    PURPOSE_PROMPTS,
    SCHEMAS,
    SNAPSHOT_CAPS,
    JsonObject,
    compose_system_prompt,
    parse_output,
    response_schema_for,
    user_message,
)
from .loop_generation_prompts import strip_fences as _strip_fences
from .loop_generation_runs import (
    MAX_REPAIRS,
    CompletionCall,
    Outcome,
    RepositorySnapshots,
    RunEntry,
    attach_repositories,
    failure_of,
    finish,
    generate,
    log_started,
    promote,
    record_phase,
    serialize_run,
)
from .loop_links import LoopWorkflowLinks
from .loops import (
    Approvals,
    DocumentSlots,
    StaleReasons,
    analysis_approved,
    document_slots,
    ensure_writable,
    latest_approvals,
    require_loop,
    stale_reasons,
)

__all__ = [
    "CLOSED_LOOP_CODES",
    "FENCE",
    "MAX_OUTPUT_CHARS",
    "MAX_REPAIRS",
    "PURPOSE_PROMPTS",
    "SCHEMAS",
    "SNAPSHOT_CAPS",
    "BoardRows",
    "CompletionCall",
    "JsonObject",
    "LoopGenerationService",
    "Outcome",
    "PreferredAgents",
    "RepositorySnapshots",
    "RolePrompt",
    "RoleSource",
    "RunEntry",
    "_strip_fences",
    "serialize_run",
]

logger = logging.getLogger("tralala.loop_generation")

CLOSED_LOOP_CODES = {"loop_read_only", "loop_not_found"}


class BoardRows(Protocol):
    """What generation needs from BoardService: the board takes writes, and its name."""

    def ensure_active(self, board_id: str) -> object: ...

    def require_row(self, board_id: str) -> BoardsRow: ...


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid4())


class LoopGenerationService:
    def __init__(
        self,
        settings: object,
        board_service: BoardRows,
        store: BoardUnitOfWork,
        registry: RegistryUnitOfWork,
        documents: LoopDocumentService,
        links: LoopWorkflowLinks,
        agents: RoleSource,
        loop_agents: PreferredAgents | None = None,
        snapshots: RepositorySnapshots | None = None,
        *,
        idempotency_ttl_seconds: int,
        call_completion: CompletionCall = runtime.call_completion,
        clock: Callable[[], datetime] = _now,
        new_id: Callable[[], str] = _new_id,
        background: bool = True,
    ) -> None:
        self.settings = settings
        self.board_service = board_service
        self.store = store
        self.registry = registry
        self.documents = documents
        self.links = links
        self.agents = agents
        self.loop_agents = loop_agents
        # A bounded, read-only repository snapshot (decision 0011, slice 2). Absent in tests that
        # only exercise the document flow.
        self.snapshots = snapshots
        self.idempotency_ttl_seconds = idempotency_ttl_seconds
        self._call_completion = call_completion
        self._clock = clock
        self._new_id = new_id
        # A unit test runs a run inline; the application hands it to a small pool.
        self._executor: ThreadPoolExecutor | None = (
            ThreadPoolExecutor(max_workers=2, thread_name_prefix="loop-generation")
            if background
            else None
        )
        self._futures: set[Future[None]] = set()

    def _now(self) -> str:
        return iso_utc(self._clock())

    # --- queries ---------------------------------------------------------------

    def _run_row(self, board_id: str, loop_id: str, run_id: str) -> LoopGenerationRunsRow:
        with self.store.reader(board_id) as repos:
            require_loop(repos, loop_id)
            row = repos.generation_runs.get_in_loop(loop_id, run_id)
        if row is None:
            raise NotFound("Generation run not found")
        return row

    def get(self, board_id: str, loop_id: str, run_id: str) -> RunEntry:
        return serialize_run(self._run_row(board_id, loop_id, run_id))

    def list_runs(self, board_id: str, loop_id: str, *, limit: int = 20) -> list[RunEntry]:
        with self.store.reader(board_id) as repos:
            require_loop(repos, loop_id)
            records = repos.generation_runs.recent(loop_id, limit=limit)
        return [serialize_run(row) for row in records]

    # --- agent resolution ------------------------------------------------------

    def _resolve_agent(
        self, agent_id: str | None, board_id: str, loop_id: str, purpose: str
    ) -> AgentsRow:
        """Explicit choice, then the Loop's stored preference, then a board agent."""
        return resolve_agent(
            agent_id,
            board_id,
            loop_id,
            purpose,
            store=self.registry,
            loop_agents=self.loop_agents,
        )

    # --- start -----------------------------------------------------------------

    @staticmethod
    def _precondition(
        loop: LoopsRow,
        purpose: str,
        documents: DocumentSlots,
        approvals: Approvals,
        stale: StaleReasons,
    ) -> None:
        if purpose == "analysis":
            if documents["info"].current is None:
                raise Conflict(
                    "Analysis needs a current Info revision written by a human",
                    code="document_stale",
                    details={"missing": "info"},
                )
            return
        if purpose == "roadmap":
            if not analysis_approved(documents, approvals, stale):
                raise Conflict(
                    "RoadMap generation requires a current approved analysis",
                    code="approval_required",
                    details={"scope": "analysis"},
                )
            return
        if loop.implementation_approval_id is None and loop.stage != "awaiting_qa":
            raise Conflict(
                "QA instructions are generated after implementation is accepted",
                code="approval_required",
                details={"scope": "implementation"},
            )

    def start(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        request: GenerationRequest,
        *,
        idempotency_key: str | None = None,
    ) -> tuple[Mapping[str, object], bool]:
        actor.require("loops:generate")
        self.board_service.ensure_active(board_id)
        fingerprint = request_fingerprint(
            {
                "op": "loop.generate",
                "board_id": board_id,
                "loop_id": loop_id,
                "payload": request.model_dump(),
            }
        )
        agent = self._resolve_agent(request.agent_id, board_id, loop_id, request.purpose)
        run_id = self._new_id()
        with self.store.writer(board_id) as repos:
            loop = require_loop(repos, loop_id)
            ensure_writable(loop)
            documents = document_slots(repos.documents.current_or_approved(loop_id))
            approvals = latest_approvals(repos.approvals.newest_first(loop_id))
            stale = stale_reasons(documents, approvals)
            self._precondition(loop, request.purpose, documents, approvals, stale)
            context = self.documents.collect_context(repos, loop)
            context_hash = request_fingerprint(context)
            source_revisions: JsonObject = {
                kind: (slot.current.id if slot.current else None)
                for kind, slot in documents.items()
            }
            captured: dict[str, object] = {
                "purpose": request.purpose,
                "instructions": request.instructions,
                "board_name": self.board_service.require_row(board_id).name,
                "context": context,
                "context_hash": context_hash,
                "source_revisions": source_revisions,
                "agent": {"id": agent.id, "name": agent.name, "model": agent.model},
            }
            role = self._role_prompt(agent)
            prompt = self._system_prompt(request.purpose, agent)
            if idempotency_key:
                stored = stored_answer(
                    repos.idempotency,
                    actor_id=actor.actor_id,
                    key=idempotency_key,
                    fingerprint=fingerprint,
                    now=self._clock(),
                )
                if stored is not None:
                    return stored, True
            row = LoopGenerationRunsRow(
                id=run_id,
                loop_id=loop_id,
                purpose=request.purpose,
                status="queued",
                input_json=json.dumps(captured),
                input_hash=context_hash,
                source_revisions_json=json.dumps(source_revisions),
                output_json="{}",
                error_code=None,
                error_message=None,
                attempts=0,
                agent_id=agent.id,
                agent_name=agent.name,
                model=agent.model,
                role_snapshot_json=json.dumps(
                    {
                        "system_prompt": prompt,
                        "role_source": role["role_source"],
                        "role_template_id": role["role_template_id"],
                        "role_template_name": role["role_template_name"],
                        "agent_id": agent.id,
                        "agent_name": agent.name,
                        "model": agent.model,
                        "purpose": request.purpose,
                    }
                ),
                usage_json="{}",
                created_by_actor_id=actor.actor_id,
                created_by_actor_type=actor.actor_type,
                created_at=self._now(),
                started_at=None,
                finished_at=None,
                phase=None,
            )
            try:
                repos.generation_runs.add(row)
            except ConstraintViolationError as exc:
                raise Conflict(
                    "A generation run for this purpose is already active",
                    code="generation_in_progress",
                    details={"purpose": request.purpose},
                ) from exc
            result = serialize_run(row)
            if idempotency_key:
                remember(
                    repos.idempotency,
                    actor_id=actor.actor_id,
                    key=idempotency_key,
                    fingerprint=fingerprint,
                    answer=result,
                    now=self._clock(),
                    ttl_seconds=self.idempotency_ttl_seconds,
                )
        self._submit(board_id, loop_id, run_id)
        return result, False

    def _submit(self, board_id: str, loop_id: str, run_id: str) -> None:
        if self._executor is None:
            self._run(board_id, loop_id, run_id)
            return
        future = self._executor.submit(carry_request_id(self._run), board_id, loop_id, run_id)
        self._futures.add(future)
        future.add_done_callback(self._futures.discard)

    def retry(
        self, actor: ActorContext, board_id: str, loop_id: str, run_id: str
    ) -> tuple[Mapping[str, object], bool]:
        existing = self._run_row(board_id, loop_id, run_id)
        if existing.status in {"queued", "running"}:
            raise Conflict("The run is still active", code="generation_in_progress")
        request = GenerationRequest.model_validate(
            {"purpose": existing.purpose, "agent_id": existing.agent_id}
        )
        return self.start(actor, board_id, loop_id, request)

    def cancel(self, actor: ActorContext, board_id: str, loop_id: str, run_id: str) -> RunEntry:
        actor.require("loops:generate")
        self.board_service.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            require_loop(repos, loop_id)
            row = repos.generation_runs.get_in_loop(loop_id, run_id)
            if row is None:
                raise NotFound("Generation run not found")
            if row.status in {"completed", "failed", "cancelled"}:
                return serialize_run(row)
            repos.generation_runs.cancel(run_id, now=self._now())
            cancelled = repos.generation_runs.get(run_id)
            if cancelled is None:
                raise NotFound("Generation run not found")
        return serialize_run(cancelled)

    # --- execution -------------------------------------------------------------

    def _role_prompt(self, agent: AgentsRow) -> RolePrompt:
        """Resolve the agent's role the same way a discussion does, without joining it later."""
        return role_prompt(agent, agents=self.agents)

    def _system_prompt(self, purpose: str, agent: AgentsRow) -> str:
        return self._compose_system_prompt(purpose, self._role_prompt(agent)["system_prompt"])

    # The prompt and its contract are pure (loop_generation_prompts); they stay reachable here.
    _compose_system_prompt = staticmethod(compose_system_prompt)
    _user_message = staticmethod(user_message)
    _parse = staticmethod(parse_output)
    _response_schema = staticmethod(response_schema_for)

    def _generate(self, purpose: str, captured: JsonObject, agent: AgentsRow) -> Outcome:
        return generate(
            purpose,
            captured,
            agent,
            system_prompt=self._system_prompt(purpose, agent),
            call_completion=self._call_completion,
            settings=self.settings,
        )

    def _run(self, board_id: str, loop_id: str, run_id: str) -> None:
        try:
            with self.store.writer(board_id) as repos:
                row = repos.generation_runs.get(run_id)
                if row is None or row.status != "queued":
                    return
                repos.generation_runs.start(run_id, now=self._now())
            log_started(row)
            captured: JsonObject = json.loads(row.input_json)
            agent_id = row.agent_id
            # The archive fetch is network I/O, so it happens here — inside the run, outside every
            # board lock — and never from the model. What the model saw is then written back to the
            # run, so a later reader can tell exactly which commit an analysis was based on.
            if captured.get("purpose") in {"analysis", "roadmap"}:
                self._phase(board_id, run_id, "analysing_repository")
                captured = self._attach_repositories(board_id, loop_id, run_id, captured)
            with self.registry.reader() as registry:
                agent = registry.agents.get(agent_id) if agent_id else None
            if agent is None:
                self._finish(
                    board_id,
                    loop_id,
                    run_id,
                    status="failed",
                    error_code="agent_missing",
                    error_message="The configured generation agent no longer exists",
                )
                return
            self._phase(board_id, run_id, "generating")
            result = self._generate(str(captured["purpose"]), captured, agent)
            if result.payload is None:
                self._finish(
                    board_id,
                    loop_id,
                    run_id,
                    status="failed",
                    error_code=result.error_code,
                    error_message=result.error_message,
                    details=result.details,
                    error_details=result.error_details,
                    retryable=result.retryable,
                )
                return
            self._promote(board_id, loop_id, run_id, captured, result.payload, result)

        except ApiError as exc:
            if exc.code in CLOSED_LOOP_CODES:
                # The Loop closed or was archived while the model was working: nothing is wrong
                # with the provider, so name the real cause instead of a generic failure.
                self._finish(
                    board_id,
                    loop_id,
                    run_id,
                    status="failed",
                    error_code="loop_closed",
                    error_message=exc.message,
                    details=None,
                    retryable=False,
                )
                return
            # A rule refused the result (a RoadMap whose references do not resolve, say): the run
            # keeps the rule's code, message and details, so a person can read what went wrong.
            self._fail(board_id, loop_id, run_id, exc)
        except Exception as exc:  # a run failure must not break the process
            logger.exception("generation_run_error", extra={"run_id": run_id})
            self._fail(board_id, loop_id, run_id, exc)

    def _fail(self, board_id: str, loop_id: str, run_id: str, exc: Exception) -> None:
        failure = failure_of(exc)
        self._finish(
            board_id,
            loop_id,
            run_id,
            status="failed",
            error_code=failure.error_code,
            error_message=failure.error_message,
            error_details=failure.error_details,
            retryable=True,
        )

    def _phase(self, board_id: str, run_id: str, phase: str) -> None:
        """Record which step a run is on; best effort, it never fails the run."""
        record_phase(board_id, run_id, phase, store=self.store)

    def _attach_repositories(
        self,
        board_id: str,
        loop_id: str,
        run_id: str,
        captured: JsonObject,
    ) -> JsonObject:
        """Fetch the board's repositories into the captured context and record what was seen."""
        return attach_repositories(
            board_id, loop_id, run_id, captured, store=self.store, snapshots=self.snapshots
        )

    def _promote(
        self,
        board_id: str,
        loop_id: str,
        run_id: str,
        captured: JsonObject,
        payload: JsonObject,
        result: Outcome,
    ) -> None:
        promote(
            board_id,
            loop_id,
            run_id,
            captured,
            payload,
            result,
            store=self.store,
            documents=self.documents,
            links=self.links,
            timestamp=self._now,
        )

    def _finish(
        self,
        board_id: str,
        loop_id: str,
        run_id: str,
        *,
        status: str,
        error_code: str | None = None,
        error_message: str | None = None,
        details: str | None = None,
        error_details: JsonValue = None,
        retryable: bool = False,
    ) -> None:
        finish(
            board_id,
            loop_id,
            run_id,
            status=status,
            error_code=error_code,
            error_message=error_message,
            details=details,
            error_details=error_details,
            retryable=retryable,
            store=self.store,
            timestamp=self._now,
        )

    # --- recovery --------------------------------------------------------------

    def recover(self, board_id: str) -> int:
        """Interrupted runs are marked failed and retryable; they are never replayed blindly."""
        with self.store.writer(board_id) as repos:
            pending = repos.generation_runs.unfinished_ids()
            for run_id in pending:
                repos.generation_runs.interrupt(
                    run_id,
                    message="The process stopped while this run was in flight; retry when ready",
                    now=self._now(),
                )
        return len(pending)

    def shutdown(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False)
