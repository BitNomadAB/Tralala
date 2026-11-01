from __future__ import annotations

from typing import Any

from conftest import Api

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


def _discussion(api: Api, board: dict[str, Any], agents: list[dict[str, Any]]) -> dict[str, Any]:
    lists = api.data(api.get(f"/api/v1/boards/{board['id']}/lists"))
    card = api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/cards",
            json={"list_id": lists[0]["id"], "title": "Session strategy"},
        )
    )
    return api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/discussions",
            json={
                "card_id": card["id"],
                "goal": "Which session strategy?",
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
        api.post(
            f"/api/v1/boards/{board['id']}/discussions/{discussion['id']}/start", json={}
        )
    )
    assert result["status"] == "consensus_proposed"
    assert result["failures"] == []
    assert {vote["position"] for vote in result["votes"]} == {"agree"}

    reloaded = api.data(
        api.get(f"/api/v1/boards/{board['id']}/discussions/{discussion['id']}")
    )
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
    reloaded = api.data(
        api.get(f"/api/v1/boards/{board['id']}/discussions/{discussion['id']}")
    )
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
    reloaded = api.data(
        api.get(f"/api/v1/boards/{board['id']}/discussions/{discussion['id']}")
    )
    assert [m["author_type"] for m in reloaded["messages"]] == ["user"]


def test_extract_position_parses_the_trailing_verdict() -> None:
    verdict, justification = runtime.extract_position("Use sessions.\nDISAGREE")
    assert verdict == "disagree"
    assert justification == "Use sessions."
    assert runtime.extract_position("No verdict here")[0] == "abstain"


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
    api.data(
        api.post(f"/api/v1/boards/{board['id']}/discussions/{second['id']}/start", json={})
    )
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
