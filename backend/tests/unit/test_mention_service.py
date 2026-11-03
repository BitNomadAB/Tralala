"""MentionService on the in-memory fakes, with the agent call scripted and the work run inline:
a mention queues one job per agent, the answer comes back as the agent's comment exactly once,
and the prompt carries the ticket's context."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from app.core.context import ActorContext
from app.core.errors import Conflict, NotFound
from app.db.generated.board import (
    AttachmentsRow,
    ChecklistItemsRow,
    ChecklistsRow,
    CommentsRow,
)
from app.services.agents import AgentService, RoleSnapshot
from app.services.mentions import MentionAgents, MentionService, serialize_job
from tests.unit.fakes.board import (
    BOARD_ID,
    BoardState,
    FakeBoardChecks,
    FakeBoardUnitOfWork,
    card_row,
    list_row,
    loop_row,
)
from tests.unit.fakes.registry import RegistryState, actor_row, agent_row, registry_unit_of_work

NOW = "2026-11-03T10:00:00Z"
CARD = "card-1"
ADA = ActorContext(
    actor_id="actor-1", actor_type="user", actor_name="Ada", scopes=frozenset({"comments:write"})
)


def agent_service_fits(service: AgentService) -> MentionAgents:
    """Never called: pyright proves that AgentService gives mentions their agents and roles."""
    return service


@dataclass
class Agents:
    names: dict[str, str] = field(default_factory=lambda: {"alpha": "Alpha", "beta": "Beta"})
    broken: set[str] = field(default_factory=set[str])

    def list(self, *, enabled: bool | None = None) -> Sequence[Mapping[str, object]]:
        del enabled
        return [{"id": agent_id, "name": name} for agent_id, name in self.names.items()]

    def role_snapshot(self, agent_id: str) -> RoleSnapshot:
        if agent_id in self.broken:
            raise RuntimeError("no role")
        return {
            "agent_id": agent_id,
            "agent_name": self.names[agent_id],
            "role_template_id": None,
            "role_template_name": "Reviewer",
            "role_template_updated_at": None,
            "role_source": "default",
            "system_prompt": f"You are {agent_id}.",
            "system_prompt_sha256": "0" * 64,
            "snapshot_at": NOW,
        }


@dataclass
class Calls:
    answers: list[Mapping[str, object]] = field(default_factory=list[Mapping[str, object]])
    prompts: list[str] = field(default_factory=list[str])
    systems: list[str] = field(default_factory=list[str])

    def __call__(
        self,
        settings: object,
        agent_row: dict[str, object],
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
    ) -> Mapping[str, object]:
        del settings, agent_row
        self.systems.append(system_prompt)
        self.prompts.append(messages[0]["content"])
        if not self.answers:
            return {"ok": False, "error": "unreachable"}
        return self.answers.pop(0)


@dataclass
class Directory:
    root: Path

    def attachments_dir(self, board_id: str) -> Path:
        return self.root / board_id


class Ids:
    def __init__(self) -> None:
        self.issued = 0

    def __call__(self) -> str:
        self.issued += 1
        return f"id-{self.issued}"


@dataclass
class World:
    state: BoardState
    registry: RegistryState
    calls: Calls
    agents: Agents
    service: MentionService


def world(tmp_path: Path) -> World:
    state = BoardState()
    state.loops["loop-a"] = loop_row("loop-a")
    state.lists["list-a"] = list_row("list-a", "loop-a", 1, name="Doing")
    state.cards[CARD] = card_row(CARD, "list-a", "loop-a")
    registry = RegistryState()
    for agent_id, name in (("alpha", "Alpha"), ("beta", "Beta")):
        registry.agents[agent_id] = agent_row(agent_id, name=name)
    registry.actors[ADA.actor_id] = actor_row(ADA.actor_id, name="Ada")
    calls = Calls()
    agents = Agents()
    service = MentionService(
        object(),
        FakeBoardChecks(),
        agents,
        FakeBoardUnitOfWork(state),
        registry_unit_of_work(registry),
        Directory(tmp_path),
        call_agent=calls,
        clock=lambda: NOW,
        new_id=Ids(),
        monotonic=lambda: 0.0,
        background=False,
    )
    return World(state, registry, calls, agents, service)


def comment(w: World, comment_id: str, content: str, *, actor_id: str = "actor-1") -> str:
    w.state.comments[comment_id] = CommentsRow(
        id=comment_id,
        card_id=CARD,
        actor_id=actor_id,
        content=content,
        created_at=NOW,
        updated_at=NOW,
    )
    return comment_id


def ok(text: str) -> Mapping[str, object]:
    return {"ok": True, "text": f"  {text}  ", "usage": {"total_tokens": 9}}


def test_a_mention_queues_one_job_per_agent_and_answers_inline(tmp_path: Path) -> None:
    w = world(tmp_path)
    w.calls.answers = [ok("Here."), ok("There.")]
    comment(w, "c-1", "@Alpha and @[Beta], have a look")
    created = w.service.queue(ADA, BOARD_ID, CARD, "c-1", "@Alpha and @[Beta], have a look")
    assert len(created) == 2
    jobs = w.state.mention_jobs
    assert {job.status for job in jobs.values()} == {"completed"}
    answers = [c for c in w.state.comments.values() if c.actor_id in {"alpha", "beta"}]
    assert sorted(c.content for c in answers) == ["Here.", "There."]
    assert all(job.response_comment_id for job in jobs.values())
    assert {job.tokens_used for job in jobs.values()} == {9}
    assert w.calls.systems == ["You are alpha.", "You are beta."]


def test_a_comment_without_a_known_agent_or_on_another_ticket_queues_nothing(
    tmp_path: Path,
) -> None:
    w = world(tmp_path)
    comment(w, "c-1", "mail me at x@Alpha.com")
    assert w.service.queue(ADA, BOARD_ID, CARD, "c-1", "mail me at x@Alpha.com") == []
    assert w.service.queue(ADA, BOARD_ID, "other", "c-1", "@Alpha") == []
    assert w.state.mention_jobs == {}


def test_the_same_comment_mentions_an_agent_once(tmp_path: Path) -> None:
    w = world(tmp_path)
    w.calls.answers = [ok("Once.")]
    comment(w, "c-1", "@Alpha")
    w.service.queue(ADA, BOARD_ID, CARD, "c-1", "@Alpha")
    assert w.service.queue(ADA, BOARD_ID, CARD, "c-1", "@Alpha") == []
    assert len(w.state.mention_jobs) == 1


def test_an_agent_without_a_usable_role_is_skipped(tmp_path: Path) -> None:
    w = world(tmp_path)
    w.agents.broken.add("alpha")
    comment(w, "c-1", "@Alpha")
    assert w.service.queue(ADA, BOARD_ID, CARD, "c-1", "@Alpha") == []


def test_a_failed_call_fails_the_job_and_a_person_may_retry_it(tmp_path: Path) -> None:
    w = world(tmp_path)
    comment(w, "c-1", "@Alpha")
    (job_id,) = w.service.queue(ADA, BOARD_ID, CARD, "c-1", "@Alpha")
    failed = w.state.mention_jobs[job_id]
    assert (failed.status, failed.error) == ("failed", "unreachable")
    assert serialize_job(failed)["can_retry"] is True
    w.calls.answers = [ok("Second try.")]
    retried = w.service.retry(ADA, BOARD_ID, CARD, job_id)
    assert retried["status"] == "completed"
    assert w.state.mention_jobs[job_id].attempts == 2
    with pytest.raises(Conflict):
        w.service.retry(ADA, BOARD_ID, CARD, job_id)
    with pytest.raises(NotFound):
        w.service.retry(ADA, BOARD_ID, "other", job_id)


def test_a_disabled_agent_fails_its_job(tmp_path: Path) -> None:
    w = world(tmp_path)
    w.registry.agents["alpha"] = agent_row("alpha", name="Alpha", enabled=False)
    comment(w, "c-1", "@Alpha")
    (job_id,) = w.service.queue(ADA, BOARD_ID, CARD, "c-1", "@Alpha")
    assert w.state.mention_jobs[job_id].error == "agent_missing"
    assert w.calls.prompts == []


def test_the_prompt_carries_the_ticket_its_lists_checklists_and_recent_comments(
    tmp_path: Path,
) -> None:
    w = world(tmp_path)
    w.state.checklists["cl-1"] = ChecklistsRow(
        id="cl-1", card_id=CARD, title="Steps", position=1
    )
    w.state.checklist_items["i-1"] = ChecklistItemsRow(
        id="i-1", checklist_id="cl-1", text="Do it", completed=1, position=1
    )
    w.state.attachments["a-1"] = AttachmentsRow(
        id="a-1",
        card_id=CARD,
        original_filename="notes.txt",
        stored_filename="stored-notes",
        content_type="text/plain",
        size_bytes=5,
        sha256="0" * 64,
        uploaded_by_actor_id=ADA.actor_id,
        created_at=NOW,
        deleted_at=None,
        discussion_id=None,
        message_id=None,
    )
    (tmp_path / BOARD_ID).mkdir()
    (tmp_path / BOARD_ID / "stored-notes").write_text("hello", encoding="utf-8")
    comment(w, "c-0", "earlier words")
    comment(w, "c-1", "@Alpha what now?")
    w.calls.answers = [ok("Next.")]
    w.service.queue(ADA, BOARD_ID, CARD, "c-1", "@Alpha what now?")
    (prompt,) = w.calls.prompts
    assert "List: Doing" in prompt
    assert "- Steps: [x] Do it" in prompt
    assert "- notes.txt (text/plain, 5 bytes)\n  content:\nhello" in prompt
    assert "Recent comments:\n[Ada · user] earlier words" in prompt
    assert "Comment that mentioned you:\n@Alpha what now?" in prompt


def test_recover_fails_running_jobs_and_resumes_queued_ones(tmp_path: Path) -> None:
    w = world(tmp_path)
    comment(w, "c-1", "@Alpha @Beta")
    w.service.queue(ADA, BOARD_ID, CARD, "c-1", "@Alpha @Beta")
    first, second = list(w.state.mention_jobs)
    w.state.mention_jobs[first] = w.state.mention_jobs[first].__replace__(status="running")
    w.state.mention_jobs[second] = w.state.mention_jobs[second].__replace__(
        status="queued", error=None
    )
    w.calls.answers = [ok("Resumed.")]
    assert w.service.recover(BOARD_ID) == 2
    assert w.state.mention_jobs[first].error == "process_restart"
    assert w.state.mention_jobs[second].status == "completed"


def test_list_needs_the_ticket(tmp_path: Path) -> None:
    w = world(tmp_path)
    with pytest.raises(NotFound):
        w.service.list(BOARD_ID, "missing")
    assert w.service.list(BOARD_ID, CARD) == []
