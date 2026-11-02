from __future__ import annotations

import uuid
from typing import Any

from conftest import Api, loop_id
from fastapi.testclient import TestClient
from sqlalchemy import text


def _services(client: TestClient) -> Any:
    return client.app.state.services  # type: ignore[attr-defined]


def _create_card(api: Api, board_id: str, title: str) -> dict[str, Any]:
    lists = api.data(api.get(f"/api/v1/boards/{board_id}/loops/{loop_id(api, board_id)}/lists"))
    return api.data(
        api.post(
            f"/api/v1/boards/{board_id}/loops/{loop_id(api, board_id)}/cards",
            json={"list_id": lists[0]["id"], "title": title},
        )
    )


def _insert_card_behind_the_manager(
    client: TestClient, board_id: str, loop: str, list_id: str
) -> None:
    """Write a Ticket with a raw transaction, so the write hook is deliberately bypassed.

    This is the situation the cache time limit exists for: a board file changed by something other
    than this process.
    """
    services = _services(client)
    now = "2026-11-02T00:00:00Z"
    with services.boards.open(board_id).begin() as conn:
        conn.execute(
            text(
                "INSERT INTO cards (id, list_id, loop_id, title, description, position, priority,"
                " created_at, updated_at, version)"
                " VALUES (:id, :list_id, :loop_id, 'behind the manager', '', 9.0, 'none',"
                " :now, :now, 1)"
            ),
            {"id": str(uuid.uuid4()), "list_id": list_id, "loop_id": loop, "now": now},
        )


def test_board_list_measures_once_and_reuses_the_result(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    first = api.data(api.get("/api/v1/boards"))
    stamp = _services(api.client).registry.board_stats([board["id"]])[board["id"]]["measured_at"]

    second = api.data(api.get("/api/v1/boards"))

    assert second[0]["card_count"] == first[0]["card_count"] == 0
    assert second[0]["list_count"] == 5
    assert (
        _services(api.client).registry.board_stats([board["id"]])[board["id"]]["measured_at"]
        == stamp
    )


def test_a_write_drops_the_measured_counters(api: Api, board: dict[str, Any]) -> None:
    api.data(api.get("/api/v1/boards"))
    registry = _services(api.client).registry
    assert board["id"] in registry.board_stats([board["id"]])

    _create_card(api, board["id"], "First")

    assert registry.board_stats([board["id"]]) == {}
    assert api.data(api.get("/api/v1/boards"))[0]["card_count"] == 1


def test_a_board_changed_behind_the_manager_is_measured_again_after_the_limit(
    api: Api, board: dict[str, Any], settings: Any
) -> None:
    loop = loop_id(api, board["id"])
    lists = api.data(api.get(f"/api/v1/boards/{board['id']}/loops/{loop}/lists"))
    api.data(api.get("/api/v1/boards"))

    _insert_card_behind_the_manager(api.client, board["id"], loop, lists[0]["id"])

    # Inside the limit the remembered number is still served: that is the point of the cache.
    assert api.data(api.get("/api/v1/boards"))[0]["card_count"] == 0
    settings.board_counts_cache_seconds = 0
    assert api.data(api.get("/api/v1/boards"))[0]["card_count"] == 1


def test_listing_without_counts_never_opens_a_board(api: Api, board: dict[str, Any]) -> None:
    registry = _services(api.client).registry
    # Creating the board answered with its counters, which is what the dashboard does next.
    registry.forget_board_stats(board["id"])

    listed = api.data(api.get("/api/v1/boards", params={"with_counts": "false"}))

    assert listed[0]["card_count"] == 0
    assert registry.board_stats([board["id"]]) == {}
