"""Bounded, durable generation runs for analysis, RoadMap and QA instructions.

The provider call never runs inside a board transaction. Inputs are captured first, the external
call happens outside any lock, and the result is only promoted when the captured revisions are
still current.
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from ..core.context import ActorContext
from ..core.errors import ApiError, Conflict, NotFound, ServiceUnavailable, ValidationFailure
from ..schemas.loops import AnalysisPayload, GenerationRequest, PlanPayload, QaInstructions
from ..storage.sqlite import utcnow
from . import runtime
from .agents import AgentService
from .boards import BoardService
from .common import one, request_fingerprint, rows, run_idempotent
from .loop_documents import LoopDocumentService
from .loop_links import LoopWorkflowLinks
from .loops import LoopService

logger = logging.getLogger("tralala.loop_generation")

MAX_REPAIRS = 2
CLOSED_LOOP_CODES = {"loop_read_only", "loop_not_found"}
MAX_OUTPUT_CHARS = 200_000
FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)

SCHEMAS = {
    "analysis": AnalysisPayload,
    "roadmap": PlanPayload,
    "qa": QaInstructions,
}

PURPOSE_PROMPTS = {
    "analysis": (
        "You are the technical analysis agent for a software change initiative (a Loop). "
        "Assess the request against the supplied context only. Separate observed facts, "
        "reported evidence, assumptions and recommendations. If the context does not show a "
        "repository, a tool or a legal review, say so explicitly instead of claiming you "
        "inspected it. Every material finding needs plain_language written for a project "
        "manager without technical background and no unexplained jargon in that field. "
        "Return only a JSON object that conforms to the provided schema."
    ),
    "roadmap": (
        "You are the delivery planning agent for a software change initiative (a Loop). "
        "Produce numbered Phases and concrete planned Tickets for the approved analysis. "
        "Reuse the id of an existing Phase or Ticket when it is the same item (explicit "
        "identity retention); never guess identity from similar text. Use a new UUID for a new "
        "item. Mark work that a human must perform with required_actor='human' and fill in "
        "human_action_reason and human_instructions. Model a human check that gates a later "
        "Phase as execution_mode='pre_phase_gate'. Keep dependencies acyclic and reference "
        "only ids inside this payload. Return only a JSON object that conforms to the schema."
    ),
    "qa": (
        "You are the QA planning agent for a software change initiative (a Loop). Write test "
        "scenarios from the approved requirements, the published plan and the delivery results "
        "that were actually recorded. Every scenario needs an id, AI-oriented steps (steps_ai) "
        "and short human-oriented numbered steps (steps_human) for the same expected result. "
        "Never report a test result; you only write instructions. Return only a JSON object "
        "that conforms to the provided schema."
    ),
}


def _strip_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = FENCE.sub("", cleaned).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        cleaned = cleaned[start : end + 1]
    return cleaned


class LoopGenerationService:
    def __init__(
        self,
        board_service: BoardService,
        loop_service: LoopService,
        document_service: LoopDocumentService,
        links: LoopWorkflowLinks,
        agent_service: AgentService,
        loop_agents: Any | None = None,
    ) -> None:
        self.board_service = board_service
        self.boards = board_service.boards
        self.registry = board_service.registry
        self.settings = board_service.settings
        self.loops = loop_service
        self.documents = document_service
        self.links = links
        self.agents = agent_service
        self.loop_agents = loop_agents
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="loop-generation")
        self._futures: set[Future[None]] = set()

    # --- queries ---------------------------------------------------------------

    def _serialize_run(self, row: dict[str, Any]) -> dict[str, Any]:
        entry = dict(row)
        entry["output"] = json.loads(entry.pop("output_json", "{}") or "{}")
        entry["source_revisions"] = json.loads(entry.pop("source_revisions_json", "{}") or "{}")
        entry["usage"] = json.loads(entry.pop("usage_json", "{}") or "{}")
        entry.pop("input_json", None)
        entry.pop("role_snapshot_json", None)
        entry.pop("created_by_actor_id", None)
        entry.pop("created_by_actor_type", None)
        return entry

    def get(self, board_id: str, loop_id: str, run_id: str) -> dict[str, Any]:
        with self.boards.reader(board_id) as conn:
            self.loops.require_loop_row(conn, board_id, loop_id)
            row = one(
                conn,
                "SELECT * FROM loop_generation_runs WHERE id = :id AND loop_id = :loop_id",
                {"id": run_id, "loop_id": loop_id},
            )
        if row is None:
            raise NotFound("Generation run not found")
        return self._serialize_run(row)

    def list_runs(self, board_id: str, loop_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        with self.boards.reader(board_id) as conn:
            self.loops.require_loop_row(conn, board_id, loop_id)
            records = rows(
                conn,
                "SELECT * FROM loop_generation_runs WHERE loop_id = :id"
                " ORDER BY created_at DESC, rowid DESC LIMIT :limit",
                {"id": loop_id, "limit": limit},
            )
        return [self._serialize_run(row) for row in records]

    # --- agent resolution ------------------------------------------------------

    def _board_agent_ids(self, board_id: str) -> list[str]:
        return [
            record["agent_id"]
            for record in self.registry.read(
                "SELECT agent_id FROM board_agents WHERE board_id = :id", {"id": board_id}
            )
        ]

    def _preferred_agent(self, board_id: str, loop_id: str, purpose: str) -> str | None:
        """The Loop's stored choice for this purpose, or None when it has no preference."""
        return (
            self.loop_agents.resolve(board_id, loop_id, purpose)
            if self.loop_agents is not None
            else None
        )

    def _resolve_agent(
        self, agent_id: str | None, board_id: str, loop_id: str, purpose: str
    ) -> dict[str, Any]:
        """Explicit choice, then the Loop's stored preference, then a board agent.

        An explicit choice must be usable or the run fails loudly. A stored preference may have gone
        stale (the agent was deleted, disabled, dropped from the board, or is an organisation
        profile), and then the run falls back to the board default instead of blocking.
        """
        requested = agent_id
        if not agent_id:
            agent_id = self._preferred_agent(board_id, loop_id, purpose)
        row = self._agent_row(agent_id, board_id, strict=bool(requested)) if agent_id else None
        if row is None:
            row = self._default_agent_row(board_id)
        if row is None:
            raise ServiceUnavailable(
                "No enabled generation agent is configured",
                code="generation_unavailable",
                details={"hint": "Configure an OpenAI-compatible agent in Settings"},
            )
        if row.get("connection_type") != "openai_compatible":
            raise ServiceUnavailable(
                "This connection type cannot execute generation requests",
                code="generation_unavailable",
                details={
                    "connection_type": row.get("connection_type"),
                    "supported": ["openai_compatible"],
                },
            )
        return row

    def _agent_row(
        self, agent_id: str, board_id: str, *, strict: bool
    ) -> dict[str, Any] | None:
        """An agent a run may use, or None when it is unusable and the caller is not strict."""
        row = self.registry.read_one("SELECT * FROM agents WHERE id = :id", {"id": agent_id})
        if row is None:
            if strict:
                raise ValidationFailure("Agent not found", details={"agent_id": agent_id})
            return None
        if self._is_organisation_profile(agent_id):
            if strict:
                raise ValidationFailure(
                    "An organisation profile cannot run a Loop",
                    code="agent_scope_organisation",
                    details={"agent_id": agent_id, "board_id": board_id},
                )
            return None
        if not row["enabled"]:
            if strict:
                raise ValidationFailure("Agent is disabled", details={"agent_id": agent_id})
            return None
        board_agents = self._board_agent_ids(board_id)
        if board_agents and agent_id not in board_agents:
            if strict:
                raise ValidationFailure(
                    "That agent does not work on this board",
                    code="agent_not_on_board",
                    details={"agent_id": agent_id, "board_id": board_id},
                )
            return None
        return row

    def _is_organisation_profile(self, agent_id: str) -> bool:
        row = self.registry.read_one(
            "SELECT COALESCE(r.scope, 'board') AS scope FROM agents a"
            " LEFT JOIN role_templates r ON r.id = a.role_template_id WHERE a.id = :id",
            {"id": agent_id},
        )
        return bool(row and row["scope"] == "organisation")

    def _default_agent_row(self, board_id: str) -> dict[str, Any] | None:
        """First board agent by name, else the first enabled generator of the installation.

        Organisation profiles are excluded either way: they are not a Loop's worker.
        """
        board_agents = self._board_agent_ids(board_id)
        placeholders = ", ".join(f":agent_{index}" for index in range(len(board_agents)))
        board_clause = f" AND a.id IN ({placeholders})" if board_agents else ""
        select = (
            "SELECT a.* FROM agents a LEFT JOIN role_templates r ON r.id = a.role_template_id"
            " WHERE a.enabled = 1 AND a.connection_type = 'openai_compatible'"
            " AND COALESCE(r.scope, 'board') != 'organisation'"
        )
        row = self.registry.read_one(
            select + board_clause + " ORDER BY a.name LIMIT 1",
            {f"agent_{index}": value for index, value in enumerate(board_agents)},
        )
        if row is None and board_agents:
            row = self.registry.read_one(select + " ORDER BY a.name LIMIT 1")
        return row

    # --- start -----------------------------------------------------------------

    def _precondition(
        self,
        conn: Any,
        loop: dict[str, Any],
        purpose: str,
        documents: dict[str, dict[str, Any]],
        approvals: dict[str, dict[str, Any]],
        stale: dict[str, list[str]],
    ) -> None:
        if purpose == "analysis":
            if documents["info"]["current"] is None:
                raise Conflict(
                    "Analysis needs a current Info revision written by a human",
                    code="document_stale",
                    details={"missing": "info"},
                )
            return
        if purpose == "roadmap":
            if not self.loops.analysis_approved(documents, approvals, stale):
                raise Conflict(
                    "RoadMap generation requires a current approved analysis",
                    code="approval_required",
                    details={"scope": "analysis"},
                )
            return
        if loop["implementation_approval_id"] is None and loop["stage"] != "awaiting_qa":
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
    ) -> tuple[dict[str, Any], bool]:
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
        run_id = str(uuid4())
        with self.boards.session(board_id) as conn:
            loop = self.loops.require_loop_row(conn, board_id, loop_id)
            self.loops.ensure_writable(loop)
            documents = self.loops.document_rows(conn, loop_id)
            approvals = self.loops.latest_approvals(conn, loop_id)
            stale = self.loops._stale_reasons(documents, approvals)
            self._precondition(conn, loop, request.purpose, documents, approvals, stale)
            context = self.documents.collect_context(conn, loop)
            captured = {
                "purpose": request.purpose,
                "instructions": request.instructions,
                "context": context,
                "context_hash": request_fingerprint(context),
                "source_revisions": {
                    kind: (documents[kind]["current"]["id"] if documents[kind]["current"] else None)
                    for kind in documents
                },
                "agent": {
                    "id": agent["id"],
                    "name": agent["name"],
                    "model": agent.get("model"),
                },
            }
            role = self._role_prompt(agent)
            prompt = self._system_prompt(request.purpose, agent)

            def action() -> dict[str, Any]:
                conn.execute(
                    text(
                        "INSERT INTO loop_generation_runs (id, loop_id, purpose, status,"
                        " input_json, input_hash, source_revisions_json, output_json, attempts,"
                        " agent_id, agent_name, model, role_snapshot_json, created_by_actor_id,"
                        " created_by_actor_type, created_at)"
                        " VALUES (:id, :loop_id, :purpose, 'queued', :input, :hash, :sources,"
                        " '{}', 0, :agent_id, :agent_name, :model, :role, :actor_id, :actor_type,"
                        " :now)"
                    ),
                    {
                        "id": run_id,
                        "loop_id": loop_id,
                        "purpose": request.purpose,
                        "input": json.dumps(captured),
                        "hash": captured["context_hash"],
                        "sources": json.dumps(captured["source_revisions"]),
                        "agent_id": agent["id"],
                        "agent_name": agent["name"],
                        "model": agent.get("model"),
                        "role": json.dumps(
                            {
                                "system_prompt": prompt,
                                "role_source": role["role_source"],
                                "role_template_id": role["role_template_id"],
                                "role_template_name": role["role_template_name"],
                                "agent_id": agent["id"],
                                "agent_name": agent["name"],
                                "model": agent.get("model"),
                                "purpose": request.purpose,
                            }
                        ),
                        "actor_id": actor.actor_id,
                        "actor_type": actor.actor_type,
                        "now": utcnow(),
                    },
                )
                row = one(
                    conn, "SELECT * FROM loop_generation_runs WHERE id = :id", {"id": run_id}
                )
                return self._serialize_run(row)

            try:
                result, replayed = run_idempotent(
                    conn,
                    actor_id=actor.actor_id,
                    key=idempotency_key,
                    fingerprint=fingerprint,
                    ttl_seconds=self.settings.idempotency_ttl_seconds,
                    action=action,
                )
            except IntegrityError as exc:
                raise Conflict(
                    "A generation run for this purpose is already active",
                    code="generation_in_progress",
                    details={"purpose": request.purpose},
                ) from exc
        if not replayed:
            self._submit(board_id, loop_id, result["id"])
        return result, replayed

    def _submit(self, board_id: str, loop_id: str, run_id: str) -> None:
        future = self._executor.submit(self._run, board_id, loop_id, run_id)
        self._futures.add(future)
        future.add_done_callback(self._futures.discard)

    def retry(
        self, actor: ActorContext, board_id: str, loop_id: str, run_id: str
    ) -> tuple[dict[str, Any], bool]:
        existing = self.get(board_id, loop_id, run_id)
        if existing["status"] in {"queued", "running"}:
            raise Conflict("The run is still active", code="generation_in_progress")
        request = GenerationRequest(
            purpose=existing["purpose"], agent_id=existing.get("agent_id")
        )
        return self.start(actor, board_id, loop_id, request)

    def cancel(self, actor: ActorContext, board_id: str, loop_id: str, run_id: str) -> dict[str,
    Any]:
        actor.require("loops:generate")
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            self.loops.require_loop_row(conn, board_id, loop_id)
            row = one(
                conn,
                "SELECT * FROM loop_generation_runs WHERE id = :id AND loop_id = :loop_id",
                {"id": run_id, "loop_id": loop_id},
            )
            if row is None:
                raise NotFound("Generation run not found")
            if row["status"] in {"completed", "failed", "cancelled"}:
                return self._serialize_run(row)
            conn.execute(
                text(
                    "UPDATE loop_generation_runs SET status = 'cancelled', finished_at = :now"
                    " WHERE id = :id"
                ),
                {"now": utcnow(), "id": run_id},
            )
            row = one(conn, "SELECT * FROM loop_generation_runs WHERE id = :id", {"id": run_id})
        return self._serialize_run(row)

    # --- execution -------------------------------------------------------------

    def _role_prompt(self, agent_row: dict[str, Any]) -> dict[str, Any]:
        """Resolve the agent's role the same way a discussion does, without joining it later."""
        role = self.agents.effective_role(agent_row["id"])
        return {
            "system_prompt": str(role.get("system_prompt") or "").strip(),
            "role_source": role.get("role_source"),
            "role_template_id": role.get("role_template_id"),
            "role_template_name": role.get("role_template_name"),
        }

    def _system_prompt(self, purpose: str, agent_row: dict[str, Any]) -> str:
        schema = json.dumps(SCHEMAS[purpose].model_json_schema(), ensure_ascii=False)
        role = self._role_prompt(agent_row)["system_prompt"]
        persona = f"{role}\n\n" if role else ""
        return f"{persona}{PURPOSE_PROMPTS[purpose]}\n\nJSON schema:\n{schema}"

    def _user_message(self, captured: dict[str, Any]) -> str:
        context = json.dumps(captured["context"], ensure_ascii=False)
        if len(context) > MAX_OUTPUT_CHARS:
            context = context[:MAX_OUTPUT_CHARS] + "\n… (context truncated)"
        lines = [
            f"Purpose: {captured['purpose']}",
            f"Loop: {captured['context'].get('loop_name')} ({captured['context'].get('loop_key')})",
        ]
        if captured.get("source_revisions"):
            lines.append("Captured revisions: " + json.dumps(captured["source_revisions"]))
        if captured.get("instructions"):
            lines.append("Additional instructions: " + captured["instructions"])
        lines.append("Context (JSON):")
        lines.append(context)
        return "\n".join(lines)

    def _parse(self, purpose: str, text: str) -> dict[str, Any]:
        if len(text) > MAX_OUTPUT_CHARS:
            raise ValidationFailure("Generation output exceeds the size limit")
        payload = json.loads(_strip_fences(text))
        model = SCHEMAS[purpose]
        validated = model.model_validate(payload)
        return validated.model_dump()

    def _generate(self, purpose: str, captured: dict[str, Any], agent_row: dict[str,
    Any]) -> dict[str, Any]:
        system_prompt = self._system_prompt(purpose, agent_row)
        messages = [{"role": "user", "content": self._user_message(captured)}]
        usage: dict[str, Any] = {}
        model_name: str | None = None
        outcome = runtime.call_completion(
            self.settings, agent_row, system_prompt=system_prompt, messages=messages
        )
        if not outcome["ok"]:
            return {
                "ok": False,
                "error_code": "provider_error",
                "error_message": f"The provider call failed: {outcome['error']}",
                "retryable": True,
            }
        usage = outcome.get("usage") or {}
        model_name = outcome.get("model")
        text = outcome["text"]
        for attempt in range(MAX_REPAIRS + 1):
            try:
                payload = self._parse(purpose, text)
                return {
                    "ok": True,
                    "payload": payload,
                    "usage": usage,
                    "model": model_name,
                    "attempts": attempt + 1,
                }
            except (ValueError, ValidationError) as exc:
                if attempt >= MAX_REPAIRS:
                    return {
                        "ok": False,
                        "error_code": "invalid_output",
                        "error_message": "Generated output did not match the schema",
                        "details": str(exc)[:2000],
                        "retryable": False,
                    }
                repair = {
                    "role": "user",
                    "content": (
                        "That response did not validate. Fix it and return the corrected JSON "
                        f"object only. Error: {str(exc)[:1500]}"
                    ),
                }
                outcome = runtime.call_completion(
                    self.settings,
                    agent_row,
                    system_prompt=system_prompt,
                    messages=[*messages, {"role": "assistant", "content": text}, repair],
                )
                if not outcome["ok"]:
                    return {
                        "ok": False,
                        "error_code": "provider_error",
                        "error_message": f"The provider call failed: {outcome['error']}",
                        "retryable": True,
                    }
                text = outcome["text"]
        return {
            "ok": False,
            "error_code": "invalid_output",
            "error_message": "Generated output did not match the schema",
            "retryable": False,
        }

    def _run(self, board_id: str, loop_id: str, run_id: str) -> None:
        try:
            with self.boards.session(board_id) as conn:
                row = one(
                    conn, "SELECT * FROM loop_generation_runs WHERE id = :id", {"id": run_id}
                )
                if row is None or row["status"] != "queued":
                    return
                conn.execute(
                    text(
                        "UPDATE loop_generation_runs SET status = 'running',"
                        " started_at = :now, attempts = attempts + 1 WHERE id = :id"
                    ),
                    {"now": utcnow(), "id": run_id},
                )
                captured = json.loads(row["input_json"])
                agent_id = row["agent_id"]
            agent_row = self.registry.read_one(
                "SELECT * FROM agents WHERE id = :id", {"id": agent_id}
            )
            if agent_row is None:
                self._finish(
                    board_id,
                    loop_id,
                    run_id,
                    status="failed",
                    error_code="agent_missing",
                    error_message="The configured generation agent no longer exists",
                )
                return
            result = self._generate(captured["purpose"], captured, agent_row)
            if not result["ok"]:
                self._finish(
                    board_id,
                    loop_id,
                    run_id,
                    status="failed",
                    error_code=result["error_code"],
                    error_message=result["error_message"],
                    details=result.get("details"),
                    retryable=bool(result.get("retryable")),
                )
                return
            self._promote(board_id, loop_id, run_id, captured, result)

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
            logger.exception("loop generation run failed", extra={"run_id": run_id})
            self._finish(
                board_id,
                loop_id,
                run_id,
                status="failed",
                error_code="generation_failed",
                error_message=f"{type(exc).__name__}",
                retryable=True,
            )
        except Exception as exc:  # noqa: BLE001 - a run failure must not break the process
            logger.exception("loop generation run failed", extra={"run_id": run_id})
            self._finish(
                board_id,
                loop_id,
                run_id,
                status="failed",
                error_code="generation_failed",
                error_message=f"{type(exc).__name__}",
                retryable=True,
            )

    def _promote(
        self,
        board_id: str,
        loop_id: str,
        run_id: str,
        captured: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        payload = result["payload"]
        with self.boards.session(board_id) as conn:
            row = one(conn, "SELECT * FROM loop_generation_runs WHERE id = :id", {"id": run_id})
            if row is None or row["status"] == "cancelled":
                return
            loop = self.loops.require_loop_row(conn, board_id, loop_id)
            self.loops.ensure_writable(loop)
            current = self.documents.collect_context(conn, loop)
            if request_fingerprint(current) != captured["context_hash"]:
                conn.execute(
                    text(
                        "UPDATE loop_generation_runs SET status = 'failed',"
                        " error_code = 'generation_input_changed',"
                        " error_message = :message, output_json = :output,"
                        " finished_at = :now WHERE id = :id"
                    ),
                    {
                        "message": (
                            "The documents changed while the model was working; the result was "
                            "kept for inspection and was not promoted"
                        ),
                        "output": json.dumps({"stale_candidate": payload})[:MAX_OUTPUT_CHARS],
                        "now": utcnow(),
                        "id": run_id,
                    },
                )
                return
            provenance = {
                "generation_run_id": run_id,
                "agent_id": row["agent_id"],
                "agent_name": row["agent_name"],
                "model": result.get("model") or row["model"],
            }
            if captured["purpose"] == "analysis":
                outputs = self.documents.store_generated_analysis(
                    conn, loop, AnalysisPayload.model_validate(payload), _system_actor(row),
                    run_id=run_id, provenance=provenance
                )
            elif captured["purpose"] == "roadmap":
                outputs = self.documents.store_generated_roadmap(
                    conn, loop, PlanPayload.model_validate(payload), _system_actor(row),
                    run_id=run_id, provenance=provenance
                )
            else:
                outputs = self.links.apply_qa_instructions(
                    conn,
                    loop,
                    QaInstructions.model_validate(payload),
                    run_id=run_id,
                    provenance=provenance,
                )
            conn.execute(
                text(
                    "UPDATE loop_generation_runs SET status = 'completed', output_json = :output,"
                    " usage_json = :usage, model = :model, finished_at = :now WHERE id = :id"
                ),
                {
                    "output": json.dumps({**payload, "_references": outputs})[:MAX_OUTPUT_CHARS],
                    "usage": json.dumps(result.get("usage") or {}),
                    "model": result.get("model") or row["model"],
                    "now": utcnow(),
                    "id": run_id,
                },
            )
            self.loops.refresh_stage(conn, loop_id)

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
        retryable: bool = False,
    ) -> None:
        try:
            with self.boards.session(board_id) as conn:
                conn.execute(
                    text(
                        "UPDATE loop_generation_runs SET status = :status,"
                        " error_code = :code, error_message = :message, finished_at = :now"
                        " WHERE id = :id"
                    ),
                    {
                        "status": status,
                        "code": error_code,
                        "message": (
                            (error_message or "")
                            + (f" ({details})" if details else "")
                            + ("" if retryable else " (not retryable)")
                        ).strip()
                        or None,
                        "now": utcnow(),
                        "id": run_id,
                    },
                )
        except Exception:  # noqa: BLE001 - never mask the original failure
            logger.exception("could not record generation failure", extra={"run_id": run_id})
        del loop_id

    # --- recovery --------------------------------------------------------------

    def recover(self, board_id: str) -> int:
        """Interrupted runs are marked failed and retryable; they are never replayed blindly."""
        with self.boards.session(board_id) as conn:
            pending = rows(
                conn,
                "SELECT id, loop_id FROM loop_generation_runs"
                " WHERE status IN ('queued','running')",
            )
            for row in pending:
                conn.execute(
                    text(
                        "UPDATE loop_generation_runs SET status = 'failed',"
                        " error_code = 'interrupted', error_message = :message,"
                        " finished_at = :now WHERE id = :id"
                    ),
                    {
                        "message": (
                            "The process stopped while this run was in flight; retry when ready"
                        ),
                        "now": utcnow(),
                        "id": row["id"],
                    },
                )
        return len(pending)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False)


def _system_actor(run_row: dict[str, Any]) -> ActorContext:
    return ActorContext(
        actor_id=run_row["agent_id"] or "generation",
        actor_type="agent",
        actor_name=run_row["agent_name"] or "Generation agent",
    )
