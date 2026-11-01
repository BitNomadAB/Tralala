from __future__ import annotations

from typing import Any

from conftest import Api


def _list_id(api: Api, board_id: str, index: int) -> str:
    lists = api.data(api.get(f"/api/v1/boards/{board_id}/lists"))
    return lists[index]["id"]


def test_card_lifecycle(api: Api, board: dict[str, Any]) -> None:
    todo = _list_id(api, board["id"], 1)
    created = api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/cards",
            json={
                "list_id": todo,
                "title": "Implement authentication",
                "description": "Create API authentication",
                "priority": "high",
                "labels": ["backend", "security"],
            },
        )
    )
    assert created["version"] == 1
    assert {label["name"] for label in created["labels"]} == {"backend", "security"}

    updated = api.data(
        api.patch(
            f"/api/v1/boards/{board['id']}/cards/{created['id']}",
            json={"version": 1, "title": "Implement auth", "completed": True},
        )
    )
    assert updated["title"] == "Implement auth"
    assert updated["version"] == 2
    assert updated["completed_at"] is not None

    archived = api.data(api.post(f"/api/v1/boards/{board['id']}/cards/{created['id']}/archive"))
    assert archived["archived_at"] is not None
    hidden = api.data(api.get(f"/api/v1/boards/{board['id']}/cards"))
    assert hidden == []
    restored = api.data(api.post(f"/api/v1/boards/{board['id']}/cards/{created['id']}/restore"))
    assert restored["archived_at"] is None


def test_version_conflict_returns_409(api: Api, board: dict[str, Any]) -> None:
    todo = _list_id(api, board["id"], 1)
    created = api.data(
        api.post(f"/api/v1/boards/{board['id']}/cards", json={"list_id": todo, "title": "v1"})
    )
    api.data(
        api.patch(
            f"/api/v1/boards/{board['id']}/cards/{created['id']}",
            json={"version": 1, "title": "v2"},
        )
    )
    response = api.patch(
        f"/api/v1/boards/{board['id']}/cards/{created['id']}",
        json={"version": 1, "title": "stale"},
    )
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "version_conflict"
    assert error["details"]["current_version"] == 2


def test_move_card_persists_ordering(api: Api, board: dict[str, Any]) -> None:
    todo = _list_id(api, board["id"], 1)
    doing = _list_id(api, board["id"], 2)
    ids = [
        api.data(
            api.post(
                f"/api/v1/boards/{board['id']}/cards",
                json={"list_id": todo, "title": f"card-{index}"},
            )
        )
        for index in range(3)
    ]
    moved = api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/cards/{ids[0]['id']}/move",
            json={"version": 1, "list_id": todo, "position": 2},
        )
    )
    assert moved["list_id"] == todo
    ordered = api.data(api.get(f"/api/v1/boards/{board['id']}/cards", params={"list_id": todo}))
    assert [card["title"] for card in ordered] == ["card-1", "card-2", "card-0"]

    api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/cards/{ids[1]['id']}/move",
            json={"version": 1, "list_id": doing, "position": 0},
        )
    )
    doing_cards = api.data(
        api.get(f"/api/v1/boards/{board['id']}/cards", params={"list_id": doing})
    )
    assert [card["title"] for card in doing_cards] == ["card-1"]


def test_list_reorder_and_archive(api: Api, board: dict[str, Any]) -> None:
    lists = api.data(api.get(f"/api/v1/boards/{board['id']}/lists"))
    moved = api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/lists/{lists[-1]['id']}/move",
            json={"position": 0},
        )
    )
    assert moved[0]["name"] == "Done"
    archived = api.data(api.post(f"/api/v1/boards/{board['id']}/lists/{moved[0]['id']}/archive"))
    assert archived["archived_at"] is not None
    remaining = api.data(api.get(f"/api/v1/boards/{board['id']}/lists"))
    assert "Done" not in [item["name"] for item in remaining]


def test_checklist_and_comment_workflow(api: Api, board: dict[str, Any]) -> None:
    todo = _list_id(api, board["id"], 1)
    card = api.data(
        api.post(f"/api/v1/boards/{board['id']}/cards", json={"list_id": todo, "title": "Tasks"})
    )
    checklist = api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/cards/{card['id']}/checklists", json={"title": "Steps"}
        )
    )
    item = api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/checklists/{checklist['id']}/items",
            json={"text": "Write tests"},
        )
    )
    completed = api.data(
        api.patch(
            f"/api/v1/boards/{board['id']}/checklist-items/{item['id']}",
            json={"completed": True},
        )
    )
    assert completed["completed"] is True

    comment = api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/cards/{card['id']}/comments",
            json={"content": "Looks good"},
        )
    )
    assert comment["actor_name"] == "admin"

    detail = api.data(
        api.get(
            f"/api/v1/boards/{board['id']}/cards/{card['id']}",
            params={"include": "checklists,comments"},
        )
    )
    assert detail["checklists"][0]["items"][0]["completed"] is True
    assert detail["comments"][0]["content"] == "Looks good"
    assert detail["checklist_total"] == 1
    assert detail["checklist_completed"] == 1


def test_search_by_title_label_and_overdue(api: Api, board: dict[str, Any]) -> None:
    todo = _list_id(api, board["id"], 1)
    api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/cards",
            json={
                "list_id": todo,
                "title": "Fix login bug",
                "labels": ["bug"],
                "due_at": "2020-01-01T00:00:00Z",
            },
        )
    )
    api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/cards",
            json={"list_id": todo, "title": "Write documentation", "priority": "low"},
        )
    )
    found = api.data(api.get(f"/api/v1/boards/{board['id']}/search", params={"q": "login"}))
    assert len(found) == 1
    meta = api.get(f"/api/v1/boards/{board['id']}/search", params={"q": "login"}).json()["meta"]
    assert meta["engine"] in {"fts5", "like"}

    by_label = api.data(api.get(f"/api/v1/boards/{board['id']}/search", params={"label": "bug"}))
    assert [card["title"] for card in by_label] == ["Fix login bug"]

    overdue = api.data(api.get(f"/api/v1/boards/{board['id']}/search", params={"overdue": True}))
    assert [card["title"] for card in overdue] == ["Fix login bug"]


def test_global_search_combines_boards(api: Api) -> None:
    first = api.data(api.post("/api/v1/boards", json={"name": "One"}))
    second = api.data(api.post("/api/v1/boards", json={"name": "Two"}))
    for board in (first, second):
        todo = _list_id(api, board["id"], 1)
        api.data(
            api.post(
                f"/api/v1/boards/{board['id']}/cards",
                json={"list_id": todo, "title": "Shared keyword"},
            )
        )
    results = api.data(api.get("/api/v1/search", params={"q": "Shared"}))
    assert {item["board_id"] for item in results} == {first["id"], second["id"]}


def test_bulk_create_reports_partial_failures(api: Api, board: dict[str, Any]) -> None:
    todo = _list_id(api, board["id"], 1)
    response = api.post(
        f"/api/v1/boards/{board['id']}/cards/bulk",
        json={
            "cards": [
                {"list_id": todo, "title": "First"},
                {"list_id": "missing-list", "title": "Broken"},
                {"list_id": todo, "title": "Third"},
            ]
        },
    )
    assert response.status_code == 201
    result = response.json()["data"]
    assert [card["title"] for card in result["created"]] == ["First", "Third"]
    assert len(result["failed"]) == 1
    assert result["failed"][0]["index"] == 1


def test_card_creation_idempotency(api: Api, board: dict[str, Any]) -> None:
    todo = _list_id(api, board["id"], 1)
    payload = {"list_id": todo, "title": "Only once"}
    headers = {"Idempotency-Key": "card-1"}
    first = api.data(api.post(f"/api/v1/boards/{board['id']}/cards", json=payload, headers=headers))
    second = api.data(
        api.post(f"/api/v1/boards/{board['id']}/cards", json=payload, headers=headers)
    )
    assert first["id"] == second["id"]
    cards = api.data(api.get(f"/api/v1/boards/{board['id']}/cards"))
    assert len(cards) == 1


def test_activity_feed_distinguishes_actors(api: Api, board: dict[str, Any]) -> None:
    todo = _list_id(api, board["id"], 1)
    api.data(
        api.post(f"/api/v1/boards/{board['id']}/cards", json={"list_id": todo, "title": "Audited"})
    )
    activity = api.data(api.get(f"/api/v1/boards/{board['id']}/activity"))
    actions = [entry["action"] for entry in activity]
    assert "card.created" in actions
    assert all(entry["actor_type"] == "user" for entry in activity)


def test_cross_board_transfer_moves_card(api: Api, board: dict[str, Any]) -> None:
    target = api.data(api.post("/api/v1/boards", json={"name": "Target"}))
    todo = _list_id(api, board["id"], 1)
    target_list = _list_id(api, target["id"], 1)
    card = api.data(
        api.post(f"/api/v1/boards/{board['id']}/cards", json={"list_id": todo, "title": "Move me"})
    )
    result = api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/cards/{card['id']}/transfer",
            json={
                "version": 1,
                "target_board_id": target["id"],
                "target_list_id": target_list,
            },
        )
    )
    assert result["finalized"] is True
    assert api.get(f"/api/v1/boards/{board['id']}/cards/{card['id']}").status_code == 404
    target_cards = api.data(api.get(f"/api/v1/boards/{target['id']}/cards"))
    assert [item["title"] for item in target_cards] == ["Move me"]


def test_bulk_creation_is_idempotent(api: Api, board: dict[str, Any]) -> None:
    todo = _list_id(api, board["id"], 1)
    payload = {
        "cards": [
            {"list_id": todo, "title": "Batch A"},
            {"list_id": todo, "title": "Batch B"},
        ]
    }
    headers = {"Idempotency-Key": "bulk-batch-1"}
    first = api.data(
        api.post(f"/api/v1/boards/{board['id']}/cards/bulk", json=payload, headers=headers)
    )
    second = api.data(
        api.post(f"/api/v1/boards/{board['id']}/cards/bulk", json=payload, headers=headers)
    )
    assert [card["id"] for card in first["created"]] == [card["id"] for card in second["created"]]
    cards = api.data(api.get(f"/api/v1/boards/{board['id']}/cards"))
    assert len(cards) == 2


def test_transfer_failure_archives_source(
    api: Api, board: dict[str, Any], monkeypatch: Any
) -> None:
    target = api.data(api.post("/api/v1/boards", json={"name": "Fallback target"}))
    source_list = _list_id(api, board["id"], 1)
    target_list = _list_id(api, target["id"], 1)
    card = api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/cards",
            json={"list_id": source_list, "title": "Fallback"},
        )
    )

    boards = api.client.app.state.services.boards
    original_session = boards.session
    state = {"failed": False}

    def flaky_session(board_id: str) -> Any:
        if board_id == board["id"] and not state["failed"]:
            state["failed"] = True
            raise RuntimeError("simulated delete failure")
        return original_session(board_id)

    monkeypatch.setattr(boards, "session", flaky_session)
    result = api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/cards/{card['id']}/transfer",
            json={"version": 1, "target_board_id": target["id"], "target_list_id": target_list},
        )
    )
    monkeypatch.setattr(boards, "session", original_session)

    assert result["finalized"] is False
    assert "archived" in (result["warning"] or "")
    assert "simulated delete failure" not in (result["warning"] or "")
    source = api.data(api.get(f"/api/v1/boards/{board['id']}/cards/{card['id']}"))
    assert source["archived_at"] is not None
    target_cards = api.data(api.get(f"/api/v1/boards/{target['id']}/cards"))
    assert [item["title"] for item in target_cards] == ["Fallback"]
    activity = api.data(
        api.get(
            f"/api/v1/boards/{board['id']}/activity", params={"action": "card.transfer_incomplete"}
        )
    )
    assert len(activity) == 1
