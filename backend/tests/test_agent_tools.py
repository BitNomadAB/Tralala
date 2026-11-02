"""The worker surface: `/llms.txt`, `/mcp` and the catalogue both are generated from."""

from __future__ import annotations

from typing import Any

from conftest import Api
from fastapi.testclient import TestClient

READ_SCOPES = ["boards:read", "cards:read", "loops:read", "history:read"]
WRITE_SCOPES = [
    *READ_SCOPES,
    "boards:read",
    "loops:write",
    "loops:generate",
    "cards:write",
    "comments:write",
    "discussions:read",
    "discussions:write",
]


def _token(api: Api, scopes: list[str], name: str = "worker") -> str:
    issued = api.data(
        api.post(
            "/api/v1/credentials",
            json={"name": name, "scopes": scopes, "expires_in_days": 30},
        )
    )
    return str(issued["token"])


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _rpc(
    client: TestClient,
    token: str,
    method: str,
    params: dict[str, Any] | None = None,
    message_id: int | None = 1,
) -> Any:
    message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if message_id is not None:
        message["id"] = message_id
    if params is not None:
        message["params"] = params
    return client.post("/mcp", json=message, headers=_headers(token))


def _call(client: TestClient, token: str, name: str, arguments: dict[str, Any]) -> Any:
    response = _rpc(client, token, "tools/call", {"name": name, "arguments": arguments})
    assert response.status_code == 200, response.text
    return response.json()["result"]


def _ticket(api: Api, board: dict[str, Any], loop: dict[str, Any], title: str) -> dict[str, Any]:
    columns = api.data(api.get(f"/api/v1/boards/{board['id']}/loops/{loop['id']}/lists"))
    return api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/loops/{loop['id']}/cards",
            json={"list_id": columns[0]["id"], "title": title},
        )
    )


def _agent(api: Api, name: str) -> dict[str, Any]:
    roles = api.data(api.get("/api/v1/role-templates"))
    role = next(entry for entry in roles if entry["builtin_key"] == "analytics_agent")
    return api.data(
        api.post(
            "/api/v1/agents",
            json={
                "name": name,
                "connection_type": "openai_compatible",
                "base_url": "http://127.0.0.1:8099/v1",
                "model": f"{name}-model",
                "role_template_id": role["id"],
            },
        )
    )


def test_llms_txt_is_public_and_names_the_tools(client: TestClient) -> None:
    response = client.get("/llms.txt")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/plain")
    text = response.text
    for name in (
        "read_board",
        "read_loop",
        "read_ticket",
        "assign_ticket",
        "move_ticket",
        "comment_ticket",
        "ask_agents",
    ):
        assert name in text
    assert "Authorization: Bearer" in text
    # The bootstrap is a contract, never a data dump: no password, no ids.
    assert "test-password" not in text


def test_mcp_requires_a_token(client: TestClient) -> None:
    response = client.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_initialize_and_tools_list_are_scope_filtered(
    api: Api, client: TestClient, board: dict[str, Any]
) -> None:
    read_only = _token(api, READ_SCOPES, "reader")
    initialized = _rpc(client, read_only, "initialize").json()["result"]
    assert initialized["protocolVersion"]
    assert initialized["serverInfo"]["name"] == "tralala"

    listed = _rpc(client, read_only, "tools/list").json()["result"]["tools"]
    assert {tool["name"] for tool in listed} == {"read_board", "read_loop", "read_ticket"}
    assert all(tool["inputSchema"]["type"] == "object" for tool in listed)

    writer = _token(api, WRITE_SCOPES, "writer")
    everything = _rpc(client, writer, "tools/list").json()["result"]["tools"]
    assert {tool["name"] for tool in everything} == {
        "read_board",
        "read_loop",
        "read_ticket",
        "create_loop",
        "write_info",
        "run_analysis",
        "run_roadmap",
        "assign_ticket",
        "move_ticket",
        "comment_ticket",
        "ask_agents",
        "read_discussion",
        "reply_discussion",
    }


def test_notifications_are_accepted_without_a_body(
    api: Api, client: TestClient, board: dict[str, Any]
) -> None:
    token = _token(api, READ_SCOPES)
    response = _rpc(client, token, "notifications/initialized", message_id=None)
    assert response.status_code == 202


def test_read_board_names_loops_people_and_agents(
    api: Api, client: TestClient, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    _agent(api, "Reader agent")
    token = _token(api, READ_SCOPES)
    result = _call(client, token, "read_board", {"board_id": board["id"]})
    assert result["isError"] is False
    payload = result["structuredContent"]
    assert payload["board"]["id"] == board["id"]
    assert [entry["id"] for entry in payload["loops"]] == [loop["id"]]
    assert payload["loops"][0]["execution_allowed"] is False
    assert payload["loops"][0]["blocked_reason"]["code"] == "approval_required"
    assert [person["name"] for person in payload["people"]] == ["admin"]
    assert [agent["name"] for agent in payload["agents"]] == ["Reader agent"]


def test_read_loop_and_ticket_carry_the_task(
    api: Api, client: TestClient, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    api.data(
        api.put(
            f"/api/v1/boards/{board['id']}/loops/{loop['id']}/documents/info",
            json={"content": "We must be able to enrol a person without e-mail."},
        )
    )
    ticket = _ticket(api, board, loop, "Enrolment page")
    token = _token(api, READ_SCOPES)

    context = _call(client, token, "read_loop", {"board_id": board["id"], "loop_id": loop["id"]})
    assert context["isError"] is False
    documents = context["structuredContent"]["documents"]
    assert documents["info"]["content"].startswith("We must be able to enrol")
    assert [column["name"] for column in context["structuredContent"]["columns"]][:1] == [
        "Backlog"
    ]

    single = _call(client, token, "read_ticket", {"board_id": board["id"], "card_id": ticket["id"]})
    payload = single["structuredContent"]
    assert payload["ticket"]["title"] == "Enrolment page"
    assert payload["ticket"]["version"] == 1
    assert "move_ticket" in payload["allowed_actions"]


def test_assign_move_and_comment_a_ticket(
    api: Api, client: TestClient, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    ticket = _ticket(api, board, loop, "Wire the invite form")
    admin = api.data(api.get("/api/v1/auth/me"))
    token = _token(api, WRITE_SCOPES)

    assigned = _call(
        client,
        token,
        "assign_ticket",
        {"board_id": board["id"], "card_id": ticket["id"], "assignee_id": admin["id"]},
    )
    assert assigned["isError"] is False
    assert assigned["structuredContent"]["assignee"]["name"] == "admin"
    assert assigned["structuredContent"]["version"] == 2

    moved = _call(
        client,
        token,
        "move_ticket",
        {"board_id": board["id"], "card_id": ticket["id"], "column": "In progress"},
    )
    assert moved["isError"] is False, moved
    assert moved["structuredContent"]["column"] == "In Progress"
    assert moved["structuredContent"]["version"] == 3

    commented = _call(
        client,
        token,
        "comment_ticket",
        {"board_id": board["id"], "card_id": ticket["id"], "content": "Started on the form."},
    )
    assert commented["isError"] is False
    assert commented["structuredContent"]["actor"] == "worker"

    refreshed = _call(
        client, token, "read_ticket", {"board_id": board["id"], "card_id": ticket["id"]}
    )
    payload = refreshed["structuredContent"]["ticket"]
    assert payload["column"] == "In Progress"
    assert payload["assignee"]["id"] == admin["id"]
    assert payload["comments"][-1]["content"] == "Started on the form."


def test_a_tool_outside_the_token_scope_is_refused(
    api: Api, client: TestClient, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    ticket = _ticket(api, board, loop, "Read me")
    token = _token(api, READ_SCOPES)
    response = _rpc(
        client,
        token,
        "tools/call",
        {
            "name": "move_ticket",
            "arguments": {"board_id": board["id"], "card_id": ticket["id"], "column": "Done"},
        },
    )
    body = response.json()
    assert "error" in body
    assert "cards:write" in body["error"]["message"]


def test_an_unknown_tool_is_a_protocol_error(
    api: Api, client: TestClient, board: dict[str, Any]
) -> None:
    token = _token(api, WRITE_SCOPES)
    body = _rpc(client, token, "tools/call", {"name": "create_board", "arguments": {}}).json()
    assert body["error"]["code"] == -32602


def test_ask_agents_reports_the_question_and_the_run(
    api: Api, client: TestClient, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    _agent(api, "Analytics reader")
    ticket = _ticket(api, board, loop, "Session strategy")
    token = _token(api, WRITE_SCOPES)
    result = _call(
        client,
        token,
        "ask_agents",
        {
            "board_id": board["id"],
            "card_id": ticket["id"],
            "question": "Which session strategy fits an on-premise install?",
        },
    )
    assert result["isError"] is False, result
    payload = result["structuredContent"]
    assert payload["discussion_id"]
    assert payload["messages"][0]["content"].startswith("Which session strategy")
    # The provider is unreachable in tests, so the run must report that instead of pretending.
    assert payload["run"]["status"] in {"failed", "completed"}


def test_ask_agents_without_any_agent_is_readable(
    api: Api, client: TestClient, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    ticket = _ticket(api, board, loop, "Nobody to ask")
    token = _token(api, WRITE_SCOPES)
    result = _call(
        client,
        token,
        "ask_agents",
        {"board_id": board["id"], "card_id": ticket["id"], "question": "Anybody home?"},
    )
    assert result["isError"] is True
    assert "no_agents_available" in result["content"][0]["text"]


def test_board_actors_are_readable_with_a_board_token(
    api: Api, client: TestClient, board: dict[str, Any]
) -> None:
    _agent(api, "Askable agent")
    token = _token(api, READ_SCOPES)
    response = client.get(
        f"/api/v1/boards/{board['id']}/actors", headers=_headers(token)
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert [person["name"] for person in data["people"]] == ["admin"]
    assert [agent["name"] for agent in data["agents"]] == ["Askable agent"]
    # No credential or connection detail leaks through the lookup.
    assert "api_key" not in response.text


def test_create_loop_write_info_and_run_analysis(api: Api, client: TestClient) -> None:
    """The flow a person and their worker use to start work: agree, seed, analyse."""
    board = api.data(api.post("/api/v1/boards", json={"name": "Planning board"}))
    _agent(api, "Planner agent")
    token = _token(api, WRITE_SCOPES, "planner")

    created = _call(
        client,
        token,
        "create_loop",
        {
            "board_id": board["id"],
            "name": "Account enrolment",
            "goal": "A person joins through a one-time link",
        },
    )
    assert created["isError"] is False, created
    loop = created["structuredContent"]["loop"]
    assert loop["stage"] == "draft"
    assert loop["key"]

    seeded = _call(
        client,
        token,
        "write_info",
        {
            "board_id": board["id"],
            "loop_id": loop["id"],
            "content": "A person joins through a one-time link; no e-mail is sent.",
            "note": "agreed in the planning chat",
        },
    )
    assert seeded["isError"] is False, seeded
    assert seeded["structuredContent"]["revision_number"] == 1
    assert seeded["structuredContent"]["state"] == "ready_for_review"

    # The provider is unreachable in tests, so the run itself must report that honestly.
    analysis = _call(
        client,
        token,
        "run_analysis",
        {"board_id": board["id"], "loop_id": loop["id"], "wait_seconds": 2},
    )
    assert analysis["isError"] is False, analysis
    payload = analysis["structuredContent"]
    assert payload["run"]["id"]
    assert payload["run"]["status"] in {"queued", "running", "failed", "completed"}
    assert payload["analysis"]["state"] in {"empty", "ready_for_review", "draft"}


def test_read_board_is_not_offered_without_the_loop_scope(
    api: Api, client: TestClient, board: dict[str, Any]
) -> None:
    """A tool that would fail on a missing scope must not be advertised in the first place."""
    token = _token(api, ["boards:read"], "board-only")
    listed = _rpc(client, token, "tools/list").json()["result"]["tools"]
    assert [tool["name"] for tool in listed] == []
    refused = _rpc(
        client,
        token,
        "tools/call",
        {"name": "read_board", "arguments": {"board_id": board["id"]}},
    ).json()
    assert "loops:read" in refused["error"]["message"]


def test_a_retried_create_loop_does_not_clone_the_loop(api: Api, client: TestClient) -> None:
    board = api.data(api.post("/api/v1/boards", json={"name": "Retry board"}))
    token = _token(api, WRITE_SCOPES, "retrier")
    arguments = {
        "board_id": board["id"],
        "name": "Account enrolment",
        "idempotency_key": "retry-1",
    }
    first = _call(client, token, "create_loop", arguments)["structuredContent"]["loop"]
    second = _call(client, token, "create_loop", arguments)["structuredContent"]["loop"]
    assert first["id"] == second["id"]
    loops = api.data(api.get(f"/api/v1/boards/{board['id']}/loops"))
    assert len(loops) == 1


def test_a_repeated_write_and_comment_are_not_duplicated(
    api: Api, client: TestClient, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    token = _token(api, WRITE_SCOPES, "repeater")
    info = {"board_id": board["id"], "loop_id": loop["id"], "content": "One intent."}
    first = _call(client, token, "write_info", info)["structuredContent"]
    again = _call(client, token, "write_info", info)["structuredContent"]
    assert again["deduplicated"] is True
    assert again["revision_number"] == first["revision_number"] == 1

    ticket = _ticket(api, board, loop, "Repeat me")
    comment = {"board_id": board["id"], "card_id": ticket["id"], "content": "Working on it."}
    one = _call(client, token, "comment_ticket", comment)["structuredContent"]
    two = _call(client, token, "comment_ticket", comment)["structuredContent"]
    assert two["deduplicated"] is True
    assert one["id"] == two["id"]


def test_run_roadmap_reports_the_missing_approval(
    api: Api, client: TestClient, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    _agent(api, "Roadmap agent")
    api.data(
        api.put(
            f"/api/v1/boards/{board['id']}/loops/{loop['id']}/documents/info",
            json={"content": "Intent"},
        )
    )
    token = _token(api, WRITE_SCOPES, "roadmapper")
    result = _call(
        client, token, "run_roadmap", {"board_id": board["id"], "loop_id": loop["id"]}
    )
    assert result["isError"] is True
    assert "approval_required" in result["content"][0]["text"]


def test_a_question_becomes_a_conversation(
    api: Api, client: TestClient, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    _agent(api, "Debate agent")
    ticket = _ticket(api, board, loop, "Ask twice")
    token = _token(api, WRITE_SCOPES, "asker")
    arguments = {
        "board_id": board["id"],
        "card_id": ticket["id"],
        "question": "Is a queue needed?",
    }
    first = _call(client, token, "ask_agents", arguments)["structuredContent"]
    retried = _call(client, token, "ask_agents", arguments)["structuredContent"]
    assert retried.get("deduplicated") is True
    assert retried["discussion_id"] == first["discussion_id"]

    read = _call(
        client,
        token,
        "read_discussion",
        {"board_id": board["id"], "discussion_id": first["discussion_id"]},
    )["structuredContent"]
    assert read["messages"][0]["content"] == "Is a queue needed?"

    replied = _call(
        client,
        token,
        "reply_discussion",
        {
            "board_id": board["id"],
            "discussion_id": first["discussion_id"],
            "content": "Follow-up: what about the retry path?",
        },
    )["structuredContent"]
    assert any("retry path" in message["content"] for message in replied["messages"])
    assert len(replied["messages"]) > len(read["messages"])
