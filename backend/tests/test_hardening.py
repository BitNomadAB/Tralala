from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, get_args

import pytest
from conftest import Api, loop_id
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import Settings
from app.core.security import (
    INSECURE_DEFAULT_SECRET,
    SECRET_FILE_NAME,
    resolve_secret_key,
    verify_password,
)
from app.main import create_app
from app.schemas.auth import Scope
from app.schemas.boards import BoardCreate
from app.services import Services
from app.services.common import request_fingerprint
from app.storage.sqlite import utcnow


def test_secret_is_generated_once_per_install(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", secret_key=None)
    first = resolve_secret_key(settings)
    second = resolve_secret_key(settings)
    assert first == second
    assert first != INSECURE_DEFAULT_SECRET
    assert len(first) >= 32
    secret_file = settings.data_dir / SECRET_FILE_NAME
    assert secret_file.exists()
    assert secret_file.read_text(encoding="utf-8").strip() == first


def test_published_default_secret_is_replaced(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", secret_key=INSECURE_DEFAULT_SECRET)
    resolved = resolve_secret_key(settings)
    assert resolved != INSECURE_DEFAULT_SECRET
    assert (settings.data_dir / SECRET_FILE_NAME).exists()


def test_explicit_secret_wins(tmp_path: Path) -> None:
    secret = "explicit-test-secret-with-enough-length"
    settings = Settings(data_dir=tmp_path / "data", secret_key=secret)
    assert resolve_secret_key(settings) == secret
    assert not (settings.data_dir / SECRET_FILE_NAME).exists()


def test_short_explicit_secret_is_replaced(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", secret_key="short-secret")
    resolved = resolve_secret_key(settings)
    assert resolved != "short-secret"
    assert (settings.data_dir / SECRET_FILE_NAME).exists()


def test_a_second_process_cannot_use_the_same_data_directory(tmp_path: Path) -> None:
    """The per-board locks, the rate limiter and the session secret live in one process."""
    settings = Settings(
        data_dir=tmp_path / "data",
        secret_key="test-secret",
        bootstrap_password="test-password",
    )
    first = Services(settings)
    first.initialize()
    second = Services(settings)
    try:
        with pytest.raises(RuntimeError) as failure:
            second.initialize()
        message = str(failure.value)
        assert "already in use" in message
        assert "TRALALA_DATA_DIR" in message
        assert (settings.data_dir / ".process.lock").exists()
    finally:
        second.shutdown()
        first.shutdown()
    # The lock is released with the process, so the directory is usable again.
    third = Services(settings)
    third.initialize()
    third.shutdown()


def test_meta_reports_sqlite_capabilities(api: Api) -> None:
    body = api.data(api.get("/api/v1/meta"))
    assert isinstance(body["features"]["fts5"], bool)
    assert body["features"]["idempotency"] is True


def test_meta_lists_exactly_the_grantable_token_scopes(api: Api) -> None:
    body = api.data(api.get("/api/v1/meta"))
    grantable = set(body["token_scopes"])
    # The Settings page renders this list, so it must match what a token may actually hold.
    assert grantable == set(get_args(Scope))
    assert {"loops:read", "loops:write", "loops:generate", "history:read"} <= grantable
    assert "loops:review" not in grantable
    assert set(body["scopes"]) >= grantable


def test_interrupted_board_creation_is_recoverable(api: Api) -> None:
    services = api.client.app.state.services
    broken_id = str(uuid.uuid4())
    services.registry.insert_board(broken_id, "Interrupted", "", "maintenance", 1)
    services.board.recover()
    assert services.registry.board(broken_id)["status"] == "error"

    healthy = api.data(api.post("/api/v1/boards", json={"name": "Recover me"}))
    services.registry.update_board(healthy["id"], status="maintenance")
    services.board.recover()
    assert services.registry.board(healthy["id"])["status"] == "active"


def test_pending_board_reservation_blocks_a_retry(api: Api) -> None:
    services = api.client.app.state.services
    payload = BoardCreate(name="Reserved board")
    fingerprint = request_fingerprint({"op": "board.create", "payload": payload.model_dump()})
    reserved_id = str(uuid.uuid4())
    actor_id = api.data(api.get("/api/v1/auth/me"))["id"]
    with services.registry.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO idempotency_records"
                " (actor_id, idempotency_key, request_hash, response_json, created_at, expires_at)"
                " VALUES (:actor_id, :key, :hash, :response, :now, :expires_at)"
            ),
            {
                "actor_id": actor_id,
                "key": "reserved-key",
                "hash": fingerprint,
                "response": json.dumps({"_pending": True, "board_id": reserved_id}),
                "now": utcnow(),
                "expires_at": "2999-01-01T00:00:00Z",
            },
        )

    response = api.post(
        "/api/v1/boards",
        json=payload.model_dump(),
        headers={"Idempotency-Key": "reserved-key"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "creation_in_progress"

    services.registry.insert_board(reserved_id, "Reserved board", "", "active", 1)
    replayed = api.data(
        api.post(
            "/api/v1/boards",
            json=payload.model_dump(),
            headers={"Idempotency-Key": "reserved-key"},
        )
    )
    assert replayed["id"] == reserved_id


def test_restore_lock_blocks_concurrent_readers(api: Api, board: dict[str, Any]) -> None:
    boards = api.client.app.state.services.boards
    events: list[str] = []

    def hold_lock() -> None:
        with boards.locked(board["id"]):
            events.append("locked")
            time.sleep(0.4)
            events.append("released")

    worker = threading.Thread(target=hold_lock)
    worker.start()
    time.sleep(0.1)
    with boards.reader(board["id"]) as conn:
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM lists").scalar_one() == 0
        events.append("read")
    worker.join()
    assert events.index("released") < events.index("read")


def test_restore_rejects_a_corrupt_backup(
    api: Api, board: dict[str, Any], settings: Settings
) -> None:
    lists = api.data(
        api.get(f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/lists")
    )
    api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/cards",
            json={"list_id": lists[0]["id"], "title": "Still here"},
        )
    )
    directory = Path(settings.data_dir) / "backups" / board["id"]
    directory.mkdir(parents=True, exist_ok=True)
    corrupt = directory / "backup-20260101T000000Z.sqlite"
    corrupt.write_bytes(b"this is not a sqlite database")

    response = api.post(f"/api/v1/boards/{board['id']}/backups/{corrupt.name}/restore")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"

    cards = api.data(
        api.get(f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/cards")
    )
    assert [card["title"] for card in cards] == ["Still here"]


@pytest.mark.parametrize("value", ["next tuesday", "2026-13-45", "15/01/2027"])
def test_invalid_due_dates_are_rejected(api: Api, board: dict[str, Any], value: str) -> None:
    lists = api.data(
        api.get(f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/lists")
    )
    response = api.post(
        f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/cards",
        json={"list_id": lists[0]["id"], "title": "Bad due", "due_at": value},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_due_date_is_normalized(api: Api, board: dict[str, Any]) -> None:
    lists = api.data(
        api.get(f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/lists")
    )
    created = api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/cards",
            json={"list_id": lists[0]["id"], "title": "Dated", "due_at": "2027-01-15"},
        )
    )
    assert created["due_at"] == "2027-01-15T00:00:00Z"

    invalid_filter = api.get(
        f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/cards",
        params={"due_before": "soon"},
    )
    assert invalid_filter.status_code == 422


def test_default_bootstrap_password_cannot_sign_in(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", secret_key="test-secret")
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_credentials"
    stored = app.state.services.registry.read_one(
        "SELECT c.password_hash, a.name FROM actors a JOIN user_credentials c ON c.actor_id = a.id"
    )
    assert stored is not None
    assert stored["name"] == "admin"
    assert verify_password("admin", stored["password_hash"]) is False


def test_api_documentation_requires_authentication(client: TestClient) -> None:
    assert client.get("/openapi.json").status_code == 401
    assert client.get("/docs").status_code == 401


def test_api_documentation_available_after_sign_in(api: Api) -> None:
    schema = api.get("/openapi.json")
    assert schema.status_code == 200
    assert "/api/v1/boards" in schema.json()["paths"]
    docs = api.get("/docs")
    assert docs.status_code == 200
    assert "text/html" in docs.headers["content-type"]


def test_metadata_endpoints_require_authentication(client: TestClient) -> None:
    assert client.get("/api/v1/meta").status_code == 401
    assert client.get("/api/v1/auth/scopes").status_code == 401


def test_api_responses_are_not_cacheable(api: Api) -> None:
    response = api.get("/api/v1/boards")
    assert response.headers["cache-control"] == "no-store"


def test_unauthenticated_response_declares_bearer(client: TestClient) -> None:
    response = client.get("/api/v1/boards")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_request_id_is_sanitized(api: Api) -> None:
    hostile = "bad id! <script>"
    response = api.get("/api/v1/boards", headers={"X-Request-ID": hostile})
    assert response.status_code == 200
    assert response.headers["x-request-id"] != hostile
    assert response.headers["x-request-id"] == response.json()["request_id"]
    accepted = "trace_123-abc"
    again = api.get("/api/v1/boards", headers={"X-Request-ID": accepted})
    assert again.headers["x-request-id"] == accepted


def test_bulk_failure_does_not_expose_internals(api: Api, board: dict[str, Any]) -> None:
    response = api.post(
        f"/api/v1/boards/{board['id']}/loops/{loop_id(api, board['id'])}/cards/bulk",
        json={"cards": [{"list_id": "missing-list", "title": "Broken"}]},
    )
    payload = response.json()["data"]
    assert set(payload["failed"][0]) == {"index", "code", "message"}
    assert payload["failed"][0]["code"] == "card_create_failed"
    serialized = json.dumps(payload).lower()
    for internal in ("traceback", "sqlalchemy", "sqlite", "board.sqlite"):
        assert internal not in serialized


def test_backup_response_does_not_expose_server_paths(
    api: Api, board: dict[str, Any], settings: Settings
) -> None:
    payload = api.data(api.post(f"/api/v1/boards/{board['id']}/backups"))
    assert "data_dir" not in payload
    assert str(settings.data_dir) not in json.dumps(payload)


def _chunked(payload: bytes):
    """Yield in pieces so httpx sends a chunked body with no ``Content-Length`` header."""
    for offset in range(0, len(payload), 64 * 1024):
        yield payload[offset : offset + 64 * 1024]


def test_a_body_without_content_length_is_still_bounded(api: Api, board: dict[str, Any]) -> None:
    oversized = b" " * (9 * 1024 * 1024)
    upload = api.request(
        "POST",
        f"/api/v1/boards/{board['id']}/attachments",
        params={"card_id": str(uuid.uuid4()), "filename": "notes.txt"},
        content=_chunked(oversized),
        headers={"Content-Type": "text/plain"},
    )
    # Proves the test is about the missing header: without this the middleware would have refused
    # the body and the streaming limit would never be exercised.
    assert "content-length" not in {key.lower() for key in upload.request.headers}
    assert upload.status_code == 413, upload.text
    assert upload.json()["error"]["code"] == "payload_too_large"

    imported = api.request(
        "POST",
        "/api/v1/boards/import",
        content=_chunked(oversized),
        headers={"Content-Type": "application/zip"},
    )
    assert imported.status_code == 413, imported.text

    mcp = api.request(
        "POST",
        "/mcp",
        content=_chunked(oversized),
        headers={"Content-Type": "application/json"},
    )
    assert mcp.status_code == 413, mcp.text


def test_mcp_authenticates_before_reading_the_body(client: TestClient) -> None:
    # A parse error would prove the body was read first; an unauthorised answer means the actor is
    # resolved before anything is parsed or buffered.
    response = client.post(
        "/mcp", content=b"{not-json", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 401, response.text


def test_an_archive_member_cannot_expand_past_the_limit(api: Api) -> None:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", " " * (2 * 1024 * 1024))
        archive.writestr("board.sqlite", b"not-a-database")
    response = api.request(
        "POST",
        "/api/v1/boards/import",
        content=buffer.getvalue(),
        headers={"Content-Type": "application/zip"},
    )
    assert response.status_code == 422, response.text
    assert "larger than this installation accepts" in response.text
