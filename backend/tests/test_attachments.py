from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from uuid import uuid4

from conftest import Api, loop_id


def _card(api: Api, board: dict[str, Any]) -> dict[str, Any]:
    lists = api.data(
        api.get(f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/lists")
    )
    return api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/cards",
            json={"list_id": lists[0]["id"], "title": "Attachment host"},
        )
    )


def _upload(api: Api, board: dict[str, Any], card_id: str, name: str, data: bytes, **kwargs: Any):
    return api.post(
        f"/api/v1/boards/{board['id']}/attachments",
        params={"card_id": card_id, "filename": name},
        content=data,
        headers={"Content-Type": kwargs.pop("content_type", "text/plain")},
        **kwargs,
    )


def test_upload_list_download_and_delete(api: Api, board: dict[str, Any], settings: Any) -> None:
    card = _card(api, board)
    body = b"# Notes\nAttachment body.\n"
    created = api.data(
        _upload(api, board, card["id"], "notes.md", body, content_type="text/markdown")
    )
    assert created["original_filename"] == "notes.md"
    assert created["content_type"] == "text/markdown"
    assert created["size_bytes"] == len(body)
    assert created["sha256"] == hashlib.sha256(body).hexdigest()
    assert created["card_id"] == card["id"]

    stored = (
        Path(settings.data_dir) / "boards" / board["id"] / "attachments"
    ) / f"{created['id']}.bin"
    assert stored.exists()

    listing = api.data(
        api.get(f"/api/v1/boards/{board['id']}/attachments", params={"card_id": card["id"]})
    )
    assert [item["id"] for item in listing] == [created["id"]]

    download = api.get(f"/api/v1/boards/{board['id']}/attachments/{created['id']}/download")
    assert download.status_code == 200
    assert download.content == body
    assert "attachment;" in download.headers["content-disposition"]
    assert download.headers["x-content-type-options"] == "nosniff"

    api.data(api.delete(f"/api/v1/boards/{board['id']}/attachments/{created['id']}"))
    assert not stored.exists()
    assert api.get(f"/api/v1/boards/{board['id']}/attachments/{created['id']}").status_code == 404
    remaining = api.data(
        api.get(f"/api/v1/boards/{board['id']}/attachments", params={"card_id": card["id"]})
    )
    assert remaining == []


def test_unsupported_extension_and_content_mismatch_are_rejected(
    api: Api, board: dict[str, Any]
) -> None:
    card = _card(api, board)
    rejected = _upload(api, board, card["id"], "payload.exe", b"MZ\x90\x00")
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "validation_failed"

    disguised = _upload(api, board, card["id"], "fake.pdf", b"\x89PNG\r\n\x1a\n data")
    assert disguised.status_code == 422

    traversal = api.data(_upload(api, board, card["id"], "../../etc/passwd.txt", b"safe text"))
    assert traversal["original_filename"] == "passwd.txt"


def test_size_limit_is_enforced(
    api: Api, board: dict[str, Any], settings: Any, monkeypatch: Any
) -> None:
    card = _card(api, board)
    monkeypatch.setattr(settings, "attachment_max_bytes", 8)
    response = _upload(api, board, card["id"], "big.txt", b"x" * 32)
    assert response.status_code == 422
    assert "size limit" in response.json()["error"]["message"].lower()


def test_attachment_requires_authentication(api: Api, board: dict[str, Any], client: Any) -> None:
    card = _card(api, board)
    client.cookies.clear()
    anonymous = client.get(f"/api/v1/boards/{board['id']}/attachments")
    assert anonymous.status_code == 401
    anonymous_upload = client.post(
        f"/api/v1/boards/{board['id']}/attachments",
        params={"card_id": card["id"], "filename": "a.txt"},
        content=b"x",
    )
    assert anonymous_upload.status_code == 401


def test_card_assignment_to_human_and_agent(api: Api, board: dict[str, Any]) -> None:
    card = _card(api, board)
    me = api.data(api.get("/api/v1/auth/me"))
    assigned = api.data(
        api.patch(
            f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/cards/{card['id']}",
            json={"version": card["version"], "assignee_actor_id": me["id"]},
        )
    )
    assert assigned["assignee_actor_id"] == me["id"]
    assert assigned["assignee_type"] == "user"
    assert assigned["assignee_name"] == me["name"]
    assert assigned["assigned_at"] is not None
    assert assigned["assigned_by_actor_id"] == me["id"]

    mine = api.data(
        api.get(
            f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/cards",
            params={"assignee": "me"},
        )
    )
    assert [item["id"] for item in mine] == [card["id"]]

    roles = api.data(api.get("/api/v1/role-templates"))
    agent = api.data(
        api.post(
            "/api/v1/agents",
            json={
                "name": "Assignment Bot",
                "connection_type": "openai_compatible",
                "base_url": "http://127.0.0.1:8099/v1",
                "role_template_id": roles[0]["id"],
            },
        )
    )
    to_agent = api.data(
        api.patch(
            f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/cards/{card['id']}",
            json={"version": assigned["version"], "assignee_actor_id": agent["id"]},
        )
    )
    assert to_agent["assignee_type"] == "agent"
    assert to_agent["assignee_name"] == "Assignment Bot"

    by_agent = api.data(
        api.get(
            f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/cards",
            params={"assignee": agent["id"]},
        )
    )
    assert [item["id"] for item in by_agent] == [card["id"]]

    cleared = api.data(
        api.patch(
            f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/cards/{card['id']}",
            json={"version": to_agent["version"], "clear_assignee": True},
        )
    )
    assert cleared["assignee_actor_id"] is None
    unassigned = api.data(
        api.get(
            f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/cards",
            params={"assignee": "unassigned"},
        )
    )
    assert [item["id"] for item in unassigned] == [card["id"]]

    activity = api.data(
        api.get(f"/api/v1/boards/{board['id']}/activity", params={"entity_id": card["id"]})
    )
    assignee_changes = [entry for entry in activity if "assignee" in entry["changes"]]
    assert len(assignee_changes) >= 3
    assert activity[0]["actor_id"] == me["id"]


def test_disabled_agent_cannot_be_assigned(api: Api, board: dict[str, Any]) -> None:
    card = _card(api, board)
    roles = api.data(api.get("/api/v1/role-templates"))
    agent = api.data(
        api.post(
            "/api/v1/agents",
            json={
                "name": "Disabled Bot",
                "connection_type": "openai_compatible",
                "base_url": "http://127.0.0.1:8099/v1",
                "role_template_id": roles[0]["id"],
                "enabled": False,
            },
        )
    )
    response = api.patch(
        f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/cards/{card['id']}",
        json={"version": card["version"], "assignee_actor_id": agent["id"]},
    )
    assert response.status_code == 422
    assert "disabled" in response.json()["error"]["message"].lower()

    unknown = api.patch(
        f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/cards/{card['id']}",
        json={"version": card["version"], "assignee_actor_id": "not-a-real-id"},
    )
    assert unknown.status_code == 422


def test_a_rejected_upload_leaves_no_file_behind(
    api: Api, board: dict[str, Any], settings: Any
) -> None:
    missing = api.post(
        f"/api/v1/boards/{board['id']}/attachments",
        params={"card_id": str(uuid4()), "filename": "notes.txt"},
        content=b"body",
        headers={"Content-Type": "text/plain"},
    )
    assert missing.status_code == 404
    # The file is written before the row names it, so a rejected upload must clean up after itself
    # instead of leaving an unreferenced blob in the board directory.
    directory = Path(settings.data_dir) / "boards" / board["id"] / "attachments"
    leftovers = list(directory.glob("*")) if directory.exists() else []
    assert leftovers == []
