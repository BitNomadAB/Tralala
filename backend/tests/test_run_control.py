from __future__ import annotations

import threading
import time
from typing import Any

from conftest import Api, loop_id

from app.services import runtime

RUN_URL = "/api/v1/boards/{board}/discussions/{discussion}/runs"


def _agent(api: Api, name: str, role_key: str = "qa_engineer") -> dict[str, Any]:
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
    max_rounds: int = 3,
    mode: str = "manual",
) -> dict[str, Any]:
    lists = api.data(
        api.get(f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/lists")
    )
    card = api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/cards",
            json={"list_id": lists[0]["id"], "title": "Run control"},
        )
    )
    return api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/discussions",
            json={
                "card_id": card["id"],
                "goal": "Should the loop keep running?",
                "participant_ids": [agent["id"] for agent in agents],
                "max_rounds": max_rounds,
                "mode": mode,
            },
        )
    )


def _runtime(
    verdicts: dict[str, str],
    *,
    usage: dict[str, Any] | None = None,
    delay: float = 0.0,
    varying: bool = True,
):
    calls = {"n": 0}

    def call(settings: Any, agent_row: dict[str, Any], *, system_prompt: str, messages: list):
        calls["n"] += 1
        if delay:
            time.sleep(delay)
        verdict = verdicts[agent_row["name"]]
        text = f"{agent_row['name']} says: keep going. {verdict.upper()}"
        if varying:
            text = f"take {calls['n']}: {text}"
        return {
            "ok": True,
            "error": None,
            "text": text,
            "verdict": verdict,
            "justification": "keep going",
            "model": agent_row.get("model") or "test-model",
            "usage": usage or {},
        }

    return call


def _wait_until(predicate, *, timeout: float = 10.0) -> None:
    """Poll a plain condition in this process; used where no API call can report the state."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition never became true")


def _urls(board: dict[str, Any], discussion: dict[str, Any]) -> tuple[str, str]:
    base = f"/api/v1/boards/{board['id']}/discussions/{discussion['id']}"
    return base, f"{base}/runs"


def _wait(api: Api, url: str, done, *, timeout: float = 15.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        latest = api.data(api.get(url))
        if done(latest):
            return latest
        time.sleep(0.05)
    raise AssertionError(f"Timed out waiting for {url}: {latest}")


def _stable(api: Api, url: str, *, quiet: float = 0.4, timeout: float = 15.0) -> dict[str, Any]:
    """Wait until the run stops making progress (the in-flight round may still land)."""
    deadline = time.monotonic() + timeout
    latest = api.data(api.get(url))
    since = time.monotonic()
    while time.monotonic() < deadline:
        time.sleep(0.1)
        current = api.data(api.get(url))
        if current["rounds_completed"] != latest["rounds_completed"]:
            latest = current
            since = time.monotonic()
        elif time.monotonic() - since >= quiet:
            return current
    raise AssertionError(f"Run never settled at {url}: {latest}")


def test_single_round_records_a_run_with_round_and_usage(
    api: Api, board: dict[str, Any], monkeypatch: Any
) -> None:
    agent = _agent(api, "Round Bot")
    discussion = _discussion(api, board, [agent])
    monkeypatch.setattr(
        runtime, "call_agent", _runtime({"Round Bot": "disagree"}, usage={"total_tokens": 42})
    )

    _, runs_url = _urls(board, discussion)
    result = api.data(api.post(f"{runs_url.rsplit('/runs', 1)[0]}/start", json={}))

    assert result["rounds_requested"] == 1
    assert result["rounds_completed"] == 1
    assert result["run_status"] == "completed"
    assert result["run_state"] == "idle"
    assert result["tokens_used"] == 42
    assert result["answers"] == 1, result

    detail = api.data(api.get(f"/api/v1/boards/{board['id']}/discussions/{discussion['id']}"))
    assert detail["round_count"] == 1
    assert detail["tokens_used"] == 42
    assert len(detail["runs"]) == 1
    run = detail["runs"][0]
    assert run["status"] == "completed"
    assert [entry["round_number"] for entry in run["rounds"]] == [1]
    assert run["rounds"][0]["tokens_used"] == 42
    assert detail["messages"][-1]["round_number"] == 1


def test_autonomous_run_uses_every_requested_round(
    api: Api, board: dict[str, Any], monkeypatch: Any
) -> None:
    lead = _agent(api, "Auto Lead", "lead_developer")
    qa = _agent(api, "Auto Qa")
    discussion = _discussion(api, board, [lead, qa], max_rounds=2)
    monkeypatch.setattr(
        runtime,
        "call_agent",
        _runtime({"Auto Lead": "disagree", "Auto Qa": "disagree"}),
    )

    base, runs_url = _urls(board, discussion)
    created = api.post(runs_url, json={"autonomous": True})
    assert created.status_code == 202, created.text
    run_id = api.data(created)["run_id"]

    final = _wait(api, f"{runs_url}/{run_id}", lambda run: run["status"] != "running")
    assert final["status"] == "completed"
    assert final["rounds_requested"] == 2
    assert final["rounds_completed"] == 2
    assert [entry["round_number"] for entry in final["rounds"]] == [1, 2]

    detail = api.data(api.get(base))
    assert detail["round_count"] == 2
    assert detail["status"] == "discussing"
    assert detail["run_state"] == "idle"


def test_consensus_stops_the_loop_after_one_round(
    api: Api, board: dict[str, Any], monkeypatch: Any
) -> None:
    lead = _agent(api, "Agree Lead", "lead_developer")
    qa = _agent(api, "Agree Qa")
    discussion = _discussion(api, board, [lead, qa], max_rounds=4)
    monkeypatch.setattr(
        runtime, "call_agent", _runtime({"Agree Lead": "agree", "Agree Qa": "agree"})
    )

    base, runs_url = _urls(board, discussion)
    run_id = api.data(api.post(runs_url, json={"autonomous": True}))["run_id"]
    final = _wait(api, f"{runs_url}/{run_id}", lambda run: run["status"] != "running")

    assert final["status"] == "completed"
    assert final["stop_reason"] == "consensus"
    assert final["rounds_completed"] == 1

    detail = api.data(api.get(base))
    assert detail["status"] == "consensus_proposed"


def test_repeated_answers_stop_the_loop(api: Api, board: dict[str, Any], monkeypatch: Any) -> None:
    agent = _agent(api, "Echo Bot")
    discussion = _discussion(api, board, [agent], max_rounds=4)
    monkeypatch.setattr(runtime, "call_agent", _runtime({"Echo Bot": "disagree"}, varying=False))

    base, runs_url = _urls(board, discussion)
    run_id = api.data(api.post(runs_url, json={"autonomous": True}))["run_id"]
    final = _wait(api, f"{runs_url}/{run_id}", lambda run: run["status"] != "running")

    assert final["status"] == "no_progress"
    assert final["stop_reason"] == "duplicate_answers"
    assert final["rounds_completed"] == 2
    assert final["rounds"][0]["answers"] == 1
    assert final["rounds"][1]["repeats"] == 1

    detail = api.data(api.get(base))
    agent_messages = [m for m in detail["messages"] if m["author_type"] == "agent"]
    assert len(agent_messages) == 1


def test_token_budget_ends_the_round_early(
    api: Api, board: dict[str, Any], monkeypatch: Any
) -> None:
    lead = _agent(api, "Budget Lead", "lead_developer")
    qa = _agent(api, "Budget Qa")
    discussion = _discussion(api, board, [lead, qa], max_rounds=3)
    monkeypatch.setattr(
        runtime,
        "call_agent",
        _runtime({"Budget Lead": "disagree", "Budget Qa": "disagree"}, usage={"total_tokens": 600}),
    )

    base, runs_url = _urls(board, discussion)
    run_id = api.data(api.post(runs_url, json={"autonomous": True, "token_budget": 500}))["run_id"]
    final = _wait(api, f"{runs_url}/{run_id}", lambda run: run["status"] != "running")

    assert final["status"] == "budget_exhausted"
    assert final["stop_reason"] == "token_budget"
    assert final["rounds_completed"] == 1
    assert final["rounds"][0]["answers"] == 1
    assert final["tokens_used"] == 600

    detail = api.data(api.get(base))
    assert len([m for m in detail["messages"] if m["author_type"] == "agent"]) == 1


def test_time_budget_stops_further_rounds(
    api: Api, board: dict[str, Any], monkeypatch: Any
) -> None:
    agent = _agent(api, "Slow Bot")
    discussion = _discussion(api, board, [agent], max_rounds=4)
    monkeypatch.setattr(runtime, "call_agent", _runtime({"Slow Bot": "disagree"}, delay=0.05))

    _, runs_url = _urls(board, discussion)
    run_id = api.data(api.post(runs_url, json={"autonomous": True, "time_budget_seconds": 0}))[
        "run_id"
    ]
    final = _wait(api, f"{runs_url}/{run_id}", lambda run: run["status"] != "running")

    assert final["status"] == "budget_exhausted"
    assert final["stop_reason"] == "time_budget"
    assert final["rounds_completed"] == 1
    assert final["elapsed_ms"] > 0


def test_pause_holds_the_loop_and_resume_continues(
    api: Api, board: dict[str, Any], monkeypatch: Any
) -> None:
    agent = _agent(api, "Pause Bot")
    discussion = _discussion(api, board, [agent], max_rounds=4)
    # The second round blocks until the test opens the gate, so the pause is requested at a known
    # point instead of racing the loop. Every wait below is deterministic; no sleep decides it.
    gate = threading.Event()
    calls = {"n": 0}
    counter = threading.Lock()

    def call(settings: Any, agent_row: dict[str, Any], *, system_prompt: str, messages: list):
        with counter:
            calls["n"] += 1
            take = calls["n"]
        if take > 1:
            gate.wait(timeout=10)
        return {
            "ok": True,
            "error": None,
            "text": f"take {take}: keep going. DISAGREE",
            "verdict": "disagree",
            "justification": "keep going",
            "model": "test-model",
            "usage": {},
        }

    monkeypatch.setattr(runtime, "call_agent", call)
    _, runs_url = _urls(board, discussion)
    run_id = api.data(api.post(runs_url, json={"autonomous": True}))["run_id"]
    _wait(api, f"{runs_url}/{run_id}", lambda run: run["rounds_completed"] >= 1)
    # Round two is now parked inside the gate, so no further round can start behind us.
    _wait_until(lambda: calls["n"] >= 2)

    paused = api.data(api.post(f"{runs_url}/{run_id}/pause"))
    assert paused["run_status"] == "paused"
    assert paused["run_state"] == "paused"

    gate.set()
    settled = _wait(
        api,
        f"{runs_url}/{run_id}",
        lambda run: run["status"] == "paused" and run["rounds_completed"] == 2,
    )
    assert settled["status"] == "paused"
    assert settled["rounds_completed"] == 2
    still = api.data(api.get(f"{runs_url}/{run_id}"))
    assert still["status"] == "paused"
    assert still["rounds_completed"] == 2

    resumed = api.data(api.post(f"{runs_url}/{run_id}/resume"))
    assert resumed["run_status"] == "running"
    final = _wait(api, f"{runs_url}/{run_id}", lambda run: run["status"] != "running")
    assert final["status"] == "completed"
    assert final["rounds_completed"] == 4


def test_stop_ends_the_run_and_blocks_new_work(
    api: Api, board: dict[str, Any], monkeypatch: Any
) -> None:
    agent = _agent(api, "Stop Bot")
    discussion = _discussion(api, board, [agent], max_rounds=4)
    monkeypatch.setattr(runtime, "call_agent", _runtime({"Stop Bot": "disagree"}, delay=0.12))

    base, runs_url = _urls(board, discussion)
    run_id = api.data(api.post(runs_url, json={"autonomous": True}))["run_id"]
    _wait(api, f"{runs_url}/{run_id}", lambda run: run["rounds_completed"] >= 1)

    stopped = api.data(api.post(f"{runs_url}/{run_id}/stop"))
    assert stopped["run_status"] == "stopped"
    assert stopped["run_state"] == "stopped"

    detail = _wait(api, base, lambda item: item["run_state"] == "stopped")
    assert detail["active_run"] is None

    assert api.post(f"{runs_url}/{run_id}/stop").status_code == 409
    assert api.post(f"{runs_url}/{run_id}/pause").status_code == 409
    assert api.post(f"{runs_url}/{run_id}/resume").status_code == 409

    review = api.post(f"{base}/review", json={"decision": "approve"})
    assert review.status_code == 200


def test_only_one_active_run_per_discussion(
    api: Api, board: dict[str, Any], monkeypatch: Any
) -> None:
    agent = _agent(api, "Busy Bot")
    discussion = _discussion(api, board, [agent], max_rounds=3)
    monkeypatch.setattr(runtime, "call_agent", _runtime({"Busy Bot": "disagree"}, delay=0.15))

    _, runs_url = _urls(board, discussion)
    run_id = api.data(api.post(runs_url, json={"autonomous": True}))["run_id"]
    second = api.post(runs_url, json={"autonomous": True})
    assert second.status_code == 409
    assert second.json()["error"]["details"]["run_id"] == run_id

    api.data(api.post(f"{runs_url}/{run_id}/stop"))

    retry = api.post(f"{runs_url}/{run_id}/pause")
    assert retry.status_code == 409


def test_run_inputs_are_validated(api: Api, board: dict[str, Any], monkeypatch: Any) -> None:
    agent = _agent(api, "Valid Bot")
    discussion = _discussion(api, board, [agent])
    monkeypatch.setattr(runtime, "call_agent", _runtime({"Valid Bot": "disagree"}))

    _, runs_url = _urls(board, discussion)
    assert api.post(runs_url, json={"rounds": 0}).status_code == 422
    assert api.post(runs_url, json={"token_budget": -1}).status_code == 422
    assert api.post(runs_url, json={"mode": "auto"}).status_code == 422
    assert api.get(f"{runs_url}/00000000-0000-0000-0000-000000000000").status_code == 404
    assert api.post(f"{runs_url}/nope/pause").status_code == 404

    listing = api.data(api.get(runs_url))
    assert listing["total"] == 0


def test_roundtable_message_starts_one_round_automatically(
    api: Api, board: dict[str, Any], monkeypatch: Any
) -> None:
    agent = _agent(api, "Roundtable Bot")
    discussion = _discussion(api, board, [agent], mode="roundtable")
    monkeypatch.setattr(runtime, "call_agent", _runtime({"Roundtable Bot": "agree"}))

    base, runs_url = _urls(board, discussion)
    posted = api.data(
        api.post(f"{base}/messages", json={"content": "What do you think about this?"})
    )
    assert posted["mode"] == "roundtable"
    assert posted["auto_run"] == "started"

    runs = _wait(
        api, runs_url, lambda data: data["items"] and data["items"][0]["status"] != "running"
    )
    run = runs["items"][0]
    assert run["rounds_requested"] == 1
    assert run["rounds_completed"] == 1
    assert run["status"] == "completed"
    assert run["started_by_type"] == "user"

    detail = api.data(api.get(base))
    assert detail["round_count"] == 1
    assert detail["message_count"] == 3
    assert detail["messages"][-1]["author_type"] == "agent"


def test_manual_and_closed_threads_do_not_start_runs_from_a_message(
    api: Api, board: dict[str, Any], monkeypatch: Any
) -> None:
    agent = _agent(api, "Quiet Bot")
    manual = _discussion(api, board, [agent])
    monkeypatch.setattr(runtime, "call_agent", _runtime({"Quiet Bot": "agree"}))

    base, runs_url = _urls(board, manual)
    posted = api.data(api.post(f"{base}/messages", json={"content": "Manual thread question"}))
    assert posted["auto_run"] is None
    assert api.data(api.get(runs_url))["total"] == 0

    api.data(api.post(f"{base}/review", json={"decision": "approve", "reason": "done"}))
    closed = api.data(api.post(f"{base}/messages", json={"content": "@agents after approval"}))
    assert closed["auto_run"] == "thread_closed"
    assert api.data(api.get(runs_url))["total"] == 0
    assert api.data(api.get(base))["status"] == "approved"


def test_autonomous_mode_message_starts_one_background_round(
    api: Api, board: dict[str, Any], monkeypatch: Any
) -> None:
    agent = _agent(api, "Autonomous Bot")
    discussion = _discussion(api, board, [agent], mode="autonomous")
    monkeypatch.setattr(runtime, "call_agent", _runtime({"Autonomous Bot": "disagree"}))

    base, runs_url = _urls(board, discussion)
    api.data(api.post(f"{base}/messages", json={"content": "Please react to this"}))

    runs = _wait(
        api, runs_url, lambda data: data["items"] and data["items"][0]["status"] != "running"
    )
    assert runs["items"][0]["rounds_requested"] == 1
    assert runs["items"][0]["rounds_completed"] == 1
    assert api.data(api.get(runs_url))["total"] == 1


def test_agents_mention_starts_a_round_in_a_manual_thread(
    api: Api, board: dict[str, Any], monkeypatch: Any
) -> None:
    agent = _agent(api, "Summoned Bot")
    discussion = _discussion(api, board, [agent])
    monkeypatch.setattr(runtime, "call_agent", _runtime({"Summoned Bot": "agree"}))

    base, runs_url = _urls(board, discussion)
    posted = api.data(
        api.post(
            f"{base}/messages",
            json={"content": "@agents what do you think about the plan?"},
        )
    )
    assert posted["auto_run"] == "started"
    runs = _wait(
        api, runs_url, lambda data: data["items"] and data["items"][0]["status"] != "running"
    )
    assert runs["items"][0]["rounds_completed"] == 1
    detail = api.data(api.get(base))
    assert detail["round_count"] == 1
    assert detail["messages"][-1]["author_type"] == "agent"


def test_participant_name_mention_starts_a_round_in_a_manual_thread(
    api: Api, board: dict[str, Any], monkeypatch: Any
) -> None:
    agent = _agent(api, "Named Bot")
    discussion = _discussion(api, board, [agent])
    monkeypatch.setattr(runtime, "call_agent", _runtime({"Named Bot": "disagree"}))

    base, runs_url = _urls(board, discussion)
    api.data(
        api.post(
            f"{base}/messages",
            json={"content": "Named Bot, can you check this?"},
        )
    )
    assert api.data(api.get(runs_url))["total"] == 0

    api.data(
        api.post(
            f"{base}/messages",
            json={"content": "@Named Bot, can you check this?"},
        )
    )
    runs = _wait(
        api, runs_url, lambda data: data["items"] and data["items"][0]["status"] != "running"
    )
    assert runs["items"][0]["rounds_completed"] == 1
    assert api.data(api.get(runs_url))["total"] == 1


def test_auto_run_reports_a_run_that_is_already_active(
    api: Api, board: dict[str, Any], monkeypatch: Any
) -> None:
    import threading

    agent = _agent(api, "Busy Bot")
    discussion = _discussion(api, board, [agent])
    entered = threading.Event()
    release = threading.Event()

    def blocking(settings: Any, agent_row: dict[str, Any], *, system_prompt: str, messages: list):
        entered.set()
        release.wait(timeout=10)
        return {
            "ok": True,
            "error": None,
            "text": "busy answer AGREE",
            "verdict": "agree",
            "justification": "busy",
            "model": "test-model",
            "usage": {},
        }

    monkeypatch.setattr(runtime, "call_agent", blocking)
    base, runs_url = _urls(board, discussion)
    started = api.post(runs_url, json={"rounds": 2, "autonomous": True})
    assert started.status_code == 202, started.text
    assert entered.wait(timeout=10), "the run never reached the agent call"
    try:
        posted = api.data(api.post(f"{base}/messages", json={"content": "@agents are you there?"}))
        assert posted["auto_run"] == "already_running"
    finally:
        release.set()
    run_id = api.data(started)["run_id"]
    _wait(api, f"{runs_url}/{run_id}", lambda run: run["status"] != "running")
