"""One generation run, executed from queued to its result or to the reason there is none.

``LoopGenerationService`` queues a run and hands it here: inline in a unit test, on its small pool
in the application. The steps, each recorded on the run as it happens (its phase, and the process
tree of ``loop_generation_trace``):

1. start the run and read the Loop's documents it captured, and the agent it was queued for;
2. for an analysis or a RoadMap, read the board's repositories: an agent whose provider takes tools
   gets the commits as a workspace and reads the code itself (``loop_generation_tools``); any
   other agent, or a provider that refuses the tools after all, gets the fixed snapshot;
3. ask the model and check its answer (``loop_generation_ask``);
4. promote the answer, unless the documents changed meanwhile or the run was cancelled.

The repository fetch and the provider calls happen outside every board lock. Nothing here raises:
a failure ends the run with its code and message, and the tree ends with what was not saved.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from pydantic import JsonValue

from ..core.context import ActorContext
from ..core.errors import ApiError
from ..db.generated.registry import AgentsRow
from ..repositories.board import BoardUnitOfWork
from ..repositories.registry import RegistryUnitOfWork
from .loop_documents import LoopDocumentService
from .loop_generation_ask import CompletionCall, RunIds, generate
from .loop_generation_human import write_for_people
from .loop_generation_prompts import JsonObject
from .loop_generation_report import (
    Ended,
    failure_of,
    log_finished,
    log_started,
    repairs_line,
)
from .loop_generation_runs import (
    Outcome,
    RepositorySnapshots,
    attach_repositories,
    finish,
    promote,
    record_phase,
    record_trace,
)
from .loop_generation_tools import (
    TOOLS_REFUSED_CODE,
    ReadingLimits,
    attach_workspace,
    open_workspace,
    read_and_answer,
)
from .loop_generation_trace import RunTrace, StepKind, documents_step
from .loop_links import LoopWorkflowLinks
from .repo_snapshot import FetchedRepository
from .repo_workspace import RepositoryWorkspace

logger = logging.getLogger("tralala.loop_generation")

CLOSED_LOOP_CODES = {"loop_read_only", "loop_not_found"}
# Why a run sends the fixed snapshot instead of letting the model read, as the tree says it.
NO_TOOLS = "the agent's provider does not take tools; its connection test says so"
A2A = "an A2A agent cannot be offered tools"
REFUSED = "the provider refused tool calls this time"
# The purposes whose run writes the brief for people (loop_generation_human).
FOR_PEOPLE = frozenset({"analysis_human", "roadmap_human"})
_DOCUMENTS = {
    "analysis": "analysis",
    "analysis_human": "analysis for people",
    "roadmap": "RoadMap",
    "roadmap_human": "RoadMap for people",
    "qa": "QA instructions",
}


@dataclass(frozen=True, slots=True)
class RunContext:
    """What executing a run needs from the service: the stores, the collaborators, the provider
    call, the system prompt of a purpose and an agent, the clock and the context window's limits."""

    settings: object
    store: BoardUnitOfWork
    registry: RegistryUnitOfWork
    documents: LoopDocumentService
    links: LoopWorkflowLinks
    snapshots: RepositorySnapshots | None
    call_completion: CompletionCall
    system_prompt: Callable[[str, AgentsRow], str]
    timestamp: Callable[[], str]
    limits: ReadingLimits


def reads_with_tools(agent: AgentsRow) -> bool:
    """The agent's provider takes tools (its connection test found so), and it is not A2A."""
    return bool(agent.supports_tools) and agent.connection_type != "a2a"


def execute_run(context: RunContext, board_id: str, loop_id: str, run_id: str) -> None:
    def write(trace_json: str) -> str | None:
        return record_trace(board_id, run_id, trace_json, store=context.store)

    run = _Run(context, board_id, loop_id, run_id, RunTrace(write, context.timestamp))
    try:
        run.execute()
    except ApiError as exc:
        if exc.code in CLOSED_LOOP_CODES:
            # The Loop closed or was archived while the model was working: nothing is wrong
            # with the provider, so name the real cause instead of a generic failure.
            run.finish(Outcome(error_code="loop_closed", error_message=exc.message))
            return
        # A rule refused the result (a RoadMap whose references do not resolve, say): the run
        # keeps the rule's code, message and details, so a person can read what went wrong.
        run.fail(exc)
    except Exception as exc:  # a run failure must not break the process
        logger.exception("generation_run_error", extra={"run_id": run_id})
        run.fail(exc)


@dataclass(slots=True)
class _Run:
    context: RunContext
    board_id: str
    loop_id: str
    run_id: str
    trace: RunTrace
    fetched: Sequence[FetchedRepository] = field(default_factory=list[FetchedRepository])

    def execute(self) -> None:
        with self.context.store.writer(self.board_id) as repos:
            row = repos.generation_runs.get(self.run_id)
            if row is None or row.status != "queued":
                return
            repos.generation_runs.start(self.run_id, now=self.context.timestamp())
        log_started(row)
        captured: JsonObject = json.loads(row.input_json)
        documents = captured.get("context")
        self.trace.add(
            "documents", "step", documents_step(documents if isinstance(documents, dict) else {})
        )
        with self.context.registry.reader() as registry:
            agent = registry.agents.get(row.agent_id) if row.agent_id else None
        if agent is None:
            self.finish(
                Outcome(
                    error_code="agent_missing",
                    error_message="The configured generation agent no longer exists",
                )
            )
            return
        purpose = str(captured["purpose"])
        workspace: RepositoryWorkspace | None = None
        # The archive fetch is network I/O, so it happens here — inside the run, outside every
        # board lock — and never from the model. What the model saw is then written back to the
        # run, so a later reader can tell exactly which commit an analysis was based on.
        if purpose in {"analysis", "roadmap"}:
            self.phase("analysing_repository")
            captured, workspace = self.read_repositories(captured, agent)
        self.phase("writing_for_people" if purpose in FOR_PEOPLE else "generating")
        captured, result = self.ask(purpose, captured, agent, workspace)
        counts = self.trace.counts()
        if counts["repairs"] and not result.cancelled:
            self.trace.add("checking", "step", repairs_line(counts))
        if result.cancelled:
            self.trace.add("saving", "step", "Not saved: the run was cancelled")
            traced = row.__replace__(trace_json=self.trace.dumps())
            log_finished(traced, Ended("cancelled", None, self.context.timestamp()), captured)
            return
        if result.payload is None:
            self.finish(result)
            return
        ended = promote(
            self.board_id,
            self.loop_id,
            self.run_id,
            captured,
            result.payload,
            result,
            store=self.context.store,
            documents=self.context.documents,
            links=self.context.links,
            timestamp=self.context.timestamp,
        )
        kind, text = _saved(purpose, ended)
        self.trace.add("saving", kind, text)
        if purpose in {"analysis", "roadmap"} and ended is not None and ended.status == "completed":
            self.after_technical(purpose, row.created_by_actor_id, row.created_by_actor_type)

    def after_technical(self, kind: str, actor_id: str, actor_type: str) -> None:
        """A promoted analysis or RoadMap gets its brief for people next, from a run of its own;
        the person who asked for the analysis or RoadMap asked for that too."""
        actor = ActorContext(actor_id=actor_id, actor_type=actor_type, actor_name="")
        started = self.context.documents.after_technical(actor, self.board_id, self.loop_id, kind)
        if started["run_id"] is not None:
            self.trace.add("saving", "note", "A board agent writes the brief for people next")

    def read_repositories(
        self, captured: JsonObject, agent: AgentsRow
    ) -> tuple[JsonObject, RepositoryWorkspace | None]:
        snapshots = self.context.snapshots
        if snapshots is None:
            return captured, None
        if not reads_with_tools(agent):
            reason = A2A if agent.connection_type == "a2a" else NO_TOOLS
            return self.snapshot(captured, reason, fetch=True, trace=self.trace), None
        self.fetched = snapshots.fetch(self.board_id)
        entries, workspace = open_workspace(
            self.fetched, result_chars=self.context.limits.tool_result_chars, trace=self.trace
        )
        if workspace is None:
            # Nothing could be read: with no repository linked the snapshot path says so; a
            # repository that did not answer already has its step from open_workspace.
            quiet = None if self.fetched else self.trace
            return self.snapshot(captured, NO_TOOLS, fetch=False, trace=quiet), None
        captured = attach_workspace(
            self.board_id, self.loop_id, self.run_id, captured, entries, store=self.context.store
        )
        return captured, workspace

    def snapshot(
        self,
        captured: JsonObject,
        reason: str,
        *,
        fetch: bool,
        trace: RunTrace | None,
    ) -> JsonObject:
        """The fixed snapshot in the request: fetched now, or of the repositories the run already
        fetched."""
        snapshots = self.context.snapshots
        if snapshots is None:
            return captured
        fetched = self.fetched

        def read(budget: int) -> Sequence[Mapping[str, JsonValue]]:
            if fetch:
                return snapshots.for_board(self.board_id, budget_chars=budget)
            return snapshots.snapshot_of(fetched, budget_chars=budget)

        return attach_repositories(
            self.board_id,
            self.loop_id,
            self.run_id,
            captured,
            store=self.context.store,
            read=read,
            budget_chars=self.context.limits.context_chars,
            trace=trace,
            reason=reason,
        )

    def ask(
        self,
        purpose: str,
        captured: JsonObject,
        agent: AgentsRow,
        workspace: RepositoryWorkspace | None,
    ) -> tuple[JsonObject, Outcome]:
        prompt = self.context.system_prompt(purpose, agent)
        if purpose in FOR_PEOPLE:
            result = write_for_people(
                captured,
                agent,
                system_prompt=prompt,
                call_completion=self.context.call_completion,
                settings=self.context.settings,
                trace=self.trace,
            )
            return captured, result
        if workspace is not None:
            result = read_and_answer(
                purpose,
                captured,
                agent,
                workspace,
                system_prompt=prompt,
                call_completion=self.context.call_completion,
                settings=self.context.settings,
                limits=self.context.limits,
                trace=self.trace,
                ids=RunIds(self.loop_id, self.run_id),
            )
            if result.error_code != TOOLS_REFUSED_CODE:
                return captured, result
            self.trace.add(
                "repository",
                "limit",
                "The provider refused tool calls, although the agent's connection test found "
                "them; sent a fixed selection of files instead (test the connection again)",
            )
            captured = self.snapshot(captured, REFUSED, fetch=False, trace=self.trace)
        result = generate(
            purpose,
            captured,
            agent,
            system_prompt=prompt,
            call_completion=self.context.call_completion,
            settings=self.context.settings,
            context_chars=self.context.limits.context_chars,
            trace=self.trace,
            ids=RunIds(self.loop_id, self.run_id),
        )
        return captured, result

    def phase(self, phase: str) -> None:
        """Record which step a run is on; best effort, it never fails the run."""
        record_phase(self.board_id, self.run_id, phase, store=self.context.store)

    def finish(self, result: Outcome) -> None:
        """End the run without a result, and say so as the tree's last step."""
        message = result.error_message or result.error_code
        self.trace.add("saving", "error", f"Nothing was saved: {message}")
        finish(
            self.board_id,
            self.loop_id,
            self.run_id,
            status="failed",
            error_code=result.error_code,
            error_message=result.error_message,
            details=result.details,
            error_details=result.error_details,
            retryable=result.retryable,
            store=self.context.store,
            timestamp=self.context.timestamp,
        )

    def fail(self, exc: Exception) -> None:
        failure = failure_of(exc)
        self.finish(
            Outcome(
                error_code=failure.error_code,
                error_message=failure.error_message,
                error_details=failure.error_details,
                retryable=True,
            )
        )


def _saved(purpose: str, ended: Ended | None) -> tuple[StepKind, str]:
    """The tree's last step after promotion: its kind and its sentence."""
    document = _DOCUMENTS.get(purpose, purpose)
    if ended is None:
        return "error", "Not saved: the run no longer exists"
    if ended.status == "completed":
        if purpose == "qa":
            return "step", "Saved the QA instructions"
        return "step", f"Saved the {document} as a draft for a person to review and approve"
    if ended.error_code == "generation_input_changed":
        return (
            "error",
            "Not saved: the Loop's documents changed while the model worked; the answer is kept "
            "on the run for inspection",
        )
    return "step", "Not saved: the run was cancelled"
