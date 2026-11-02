from __future__ import annotations

from typing import Any

from conftest import Api, loop_id

from app.services import runtime


def _agent(api: Api, name: str, role_key: str) -> dict[str, Any]:
    roles = api.data(api.get("/api/v1/role-templates"))
    role = next(entry for entry in roles if entry["builtin_key"] == role_key)
    return api.data(
        api.post(
            "/api/v1/agents",
            json={
                "name": name,
                "connection_type": "openai_compatible",
                "base_url": "http://127.0.0.1:8099/v1",
                "role_template_id": role["id"],
            },
        )
    )


def _discussion(
    api: Api,
    board: dict[str, Any],
    agents: list[dict[str, Any]],
    *,
    mode: str = "manual",
) -> dict[str, Any]:
    lists = api.data(
        api.get(f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/lists")
    )
    card = api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/cards",
            json={"list_id": lists[0]["id"], "title": "Session strategy"},
        )
    )
    return api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/discussions",
            json={
                "card_id": card["id"],
                "goal": "Which session strategy?",
                "mode": mode,
                "participant_ids": [agent["id"] for agent in agents],
            },
        )
    )


def _fake_runtime(verdicts: dict[str, str]):
    def call(settings: Any, agent_row: dict[str, Any], *, system_prompt: str, messages: list):
        verdict = verdicts[agent_row["name"]]
        text = f"{agent_row['name']} says: use server sessions. {verdict.upper()}"
        return {
            "ok": True,
            "error": None,
            "text": text,
            "verdict": verdict,
            "justification": "server sessions",
            "model": agent_row.get("model") or "test-model",
            "usage": {},
        }

    return call


def test_round_records_agent_answers_and_unanimous_consensus(
    api: Api, board: dict[str, Any], monkeypatch: Any
) -> None:
    lead = _agent(api, "Lead", "lead_developer")
    qa = _agent(api, "Qa", "qa_engineer")
    discussion = _discussion(api, board, [lead, qa])
    monkeypatch.setattr(runtime, "call_agent", _fake_runtime({"Lead": "agree", "Qa": "agree"}))

    result = api.data(
        api.post(f"/api/v1/boards/{board['id']}/discussions/{discussion['id']}/start", json={})
    )
    assert result["status"] == "consensus_proposed"
    assert result["failures"] == []
    assert {vote["position"] for vote in result["votes"]} == {"agree"}

    reloaded = api.data(api.get(f"/api/v1/boards/{board['id']}/discussions/{discussion['id']}"))
    assert reloaded["status"] == "consensus_proposed"
    agent_messages = [m for m in reloaded["messages"] if m["author_type"] == "agent"]
    assert len(agent_messages) == 2
    assert all("use server sessions" in message["content"] for message in agent_messages)
    assert {message["author_name"] for message in agent_messages} == {"Lead", "Qa"}


def test_dissent_keeps_discussion_open(api: Api, board: dict[str, Any], monkeypatch: Any) -> None:
    lead = _agent(api, "Lead2", "lead_developer")
    sec = _agent(api, "Sec2", "security_engineer")
    discussion = _discussion(api, board, [lead, sec])
    monkeypatch.setattr(
        runtime, "call_agent", _fake_runtime({"Lead2": "agree", "Sec2": "disagree"})
    )
    result = api.data(
        api.post(f"/api/v1/boards/{board['id']}/discussions/{discussion['id']}/start", json={})
    )
    assert result["status"] == "discussing"
    reloaded = api.data(api.get(f"/api/v1/boards/{board['id']}/discussions/{discussion['id']}"))
    assert reloaded["status"] == "discussing"


def test_agent_failures_are_reported_without_losing_the_thread(
    api: Api, board: dict[str, Any], monkeypatch: Any
) -> None:
    agent = _agent(api, "Broken", "qa_engineer")
    discussion = _discussion(api, board, [agent])

    def failing(settings: Any, agent_row: dict[str, Any], *, system_prompt: str, messages: list):
        return {"ok": False, "error": "ConnectError", "text": ""}

    monkeypatch.setattr(runtime, "call_agent", failing)
    result = api.data(
        api.post(f"/api/v1/boards/{board['id']}/discussions/{discussion['id']}/start", json={})
    )
    assert result["failures"] == [{"agent": "Broken", "error": "ConnectError"}]
    assert result["status"] == "discussing"
    reloaded = api.data(api.get(f"/api/v1/boards/{board['id']}/discussions/{discussion['id']}"))
    assert [m["author_type"] for m in reloaded["messages"]] == ["user"]


def test_extract_position_parses_the_trailing_verdict() -> None:
    verdict, justification = runtime.extract_position("Use sessions.\nDISAGREE")
    assert verdict == "disagree"
    assert justification == "Use sessions."
    assert runtime.extract_position("No verdict here")[0] == "abstain"


def test_extract_position_never_reads_a_negation_as_agreement() -> None:
    # Matching the bare word anywhere made "I do not AGREE" a vote for agreement, which is how a
    # discussion reached consensus while its agents disagreed.
    assert runtime.extract_position("I do not AGREE with this proposal.")[0] == "abstain"
    assert runtime.extract_position("Honestly, I can not AGREE here.\nIt leaks.")[0] == "abstain"
    assert runtime.extract_position("Some AGREE, some do not.")[0] == "abstain"


def test_extract_position_prefers_a_structured_verdict() -> None:
    answer = (
        "The plan is sound but the rollback is missing.\n"
        '{"verdict": "disagree", "reasoning": "No rollback path for the migration."}'
    )
    assert runtime.extract_position(answer) == (
        "disagree",
        "No rollback path for the migration.",
    )


def test_extract_position_uses_the_last_labelled_line() -> None:
    answer = (
        "My first reading said AGREE.\n"
        "Then I checked the storage layer.\n"
        "Verdict: DISAGREE\nI still think the shape is right."
    )
    assert runtime.extract_position(answer)[0] == "disagree"


def test_each_agent_sees_the_answers_from_its_own_round(
    api: Api, board: dict[str, Any], monkeypatch: Any
) -> None:
    lead = _agent(api, "Lead5", "lead_developer")
    qa = _agent(api, "Qa5", "qa_engineer")
    discussion = _discussion(api, board, [lead, qa])
    prompts: list[tuple[str, str]] = []

    def call(settings: Any, agent_row: dict[str, Any], *, system_prompt: str, messages: list):
        prompts.append((agent_row["name"], messages[-1]["content"]))
        return {
            "ok": True,
            "error": None,
            "text": f"{agent_row['name']} says: use server sessions.\nVerdict: AGREE",
            "verdict": "agree",
            "justification": "server sessions",
            "model": "test-model",
            "usage": {},
        }

    monkeypatch.setattr(runtime, "call_agent", call)
    url = f"/api/v1/boards/{board['id']}/discussions/{discussion['id']}/start"
    api.data(api.post(url, json={}))
    first, second = prompts
    assert first[0] == "Lead5" and second[0] == "Qa5"
    assert "Answers earlier in this round" not in first[1]
    assert "Lead5 says: use server sessions" in second[1]


def test_a_roundtable_needs_a_review_round_before_consensus(
    api: Api, board: dict[str, Any], monkeypatch: Any
) -> None:
    lead = _agent(api, "Lead6", "lead_developer")
    qa = _agent(api, "Qa6", "qa_engineer")
    discussion = _discussion(api, board, [lead, qa], mode="roundtable")
    passes: dict[str, int] = {}

    def call(settings: Any, agent_row: dict[str, Any], *, system_prompt: str, messages: list):
        name = agent_row["name"]
        passes[name] = passes.get(name, 0) + 1
        return {
            "ok": True,
            "error": None,
            "text": f"{name} says: use server sessions (pass {passes[name]}).\nVerdict: AGREE",
            "verdict": "agree",
            "justification": "server sessions",
            "model": "test-model",
            "usage": {},
        }

    monkeypatch.setattr(runtime, "call_agent", call)
    url = f"/api/v1/boards/{board['id']}/discussions/{discussion['id']}/start"

    first = api.data(api.post(url, json={}))
    assert first["status"] == "discussing"
    second = api.data(api.post(url, json={}))
    assert second["status"] == "consensus_proposed"


def test_human_review_approve_veto_and_rework(
    api: Api, board: dict[str, Any], monkeypatch: Any
) -> None:
    agent = _agent(api, "Reviewer", "qa_engineer")
    discussion = _discussion(api, board, [agent])
    monkeypatch.setattr(runtime, "call_agent", _fake_runtime({"Reviewer": "agree"}))
    start = f"/api/v1/boards/{board['id']}/discussions/{discussion['id']}/start"
    api.data(api.post(start, json={}))

    base = f"/api/v1/boards/{board['id']}/discussions/{discussion['id']}/review"
    assert api.post(base, json={"decision": "veto"}).status_code == 422
    vetoed = api.data(api.post(base, json={"decision": "veto", "reason": "Missing threat model"}))
    assert vetoed["status"] == "vetoed"
    assert vetoed["votes"][0]["position"] == "agree"
    closed = api.post(base, json={"decision": "approve"})
    assert closed.status_code == 409

    second = _discussion(api, board, [agent])
    api.data(api.post(f"/api/v1/boards/{board['id']}/discussions/{second['id']}/start", json={}))
    rework = api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/discussions/{second['id']}/review",
            json={"decision": "rework", "reason": "Quantify the risk"},
        )
    )
    assert rework["status"] == "rework_requested"

    third = _discussion(api, board, [agent])
    api.data(api.post(f"/api/v1/boards/{board['id']}/discussions/{third['id']}/start", json={}))
    approved = api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/discussions/{third['id']}/review",
            json={"decision": "approve"},
        )
    )
    assert approved["status"] == "approved"


def test_a_discussion_names_the_loop_and_ticket_it_is_about(
    api: Api, board: dict[str, Any], monkeypatch: Any
) -> None:
    """The role prompt stays generic; the identifiers come from the thread at call time."""
    agent = _agent(api, "Context Bot", "lead_developer")
    discussion = _discussion(api, board, [agent])
    captured: dict[str, Any] = {}

    def capture(settings: Any, agent_row: dict[str, Any], *, system_prompt: str, messages: list):
        captured["system_prompt"] = system_prompt
        captured["messages"] = messages
        return _fake_runtime({"Context Bot": "agree"})(
            settings, agent_row, system_prompt=system_prompt, messages=messages
        )

    monkeypatch.setattr(runtime, "call_agent", capture)
    api.data(
        api.post(f"/api/v1/boards/{board['id']}/discussions/{discussion['id']}/start", json={})
    )

    prompt = captured["messages"][0]["content"]
    ticket = api.data(api.get(f"/api/v1/boards/{board['id']}/tickets"))[0]
    assert f"Loop: {ticket['loop_name']} ({ticket['loop_key']})" in prompt
    assert "Ticket: Session strategy" in prompt
    assert f"Ticket id: {ticket['id']}" in prompt
    assert "Discussion goal: Which session strategy?" in prompt
    # The role text itself names neither the ticket nor the product.
    assert "Tralala" not in captured["system_prompt"]
    assert ticket["id"] not in captured["system_prompt"]
