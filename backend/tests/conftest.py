from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        secret_key="test-secret-key-with-at-least-32-chars",
        bootstrap_username="admin",
        bootstrap_password="test-password",
        rate_limit_per_minute=100000,
        board_idle_close_seconds=1,
        enable_docs=True,
    )


class Api:
    """Thin test client that supplies CSRF headers and unwraps the response envelope."""

    def __init__(self, client: TestClient) -> None:
        self.client = client

    def _headers(self) -> dict[str, str]:
        csrf = self.client.cookies.get("tralala_csrf")
        return {"X-CSRF-Token": csrf} if csrf else {}

    def request(self, method: str, url: str, **kwargs: Any) -> Any:
        headers = {**self._headers(), **kwargs.pop("headers", {})}
        response = self.client.request(method, url, headers=headers, **kwargs)
        return response

    def get(self, url: str, **kwargs: Any) -> Any:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> Any:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> Any:
        return self.request("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> Any:
        return self.request("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> Any:
        return self.request("DELETE", url, **kwargs)

    def data(self, response: Any) -> Any:
        assert response.status_code < 400, response.text
        body = response.json()
        assert body["success"] is True, body
        return body["data"]


@pytest.fixture()
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def login(client: TestClient) -> TestClient:
    response = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "test-password"}
    )
    assert response.status_code == 200, response.text
    return client


@pytest.fixture()
def api(login: TestClient) -> Api:
    return Api(login)


@pytest.fixture()
def board(api: Api) -> dict[str, Any]:
    response = api.post("/api/v1/boards", json={"name": "Test board"})
    return api.data(response)


@pytest.fixture()
def board_lists(api: Api, board: dict[str, Any]) -> list[dict[str, Any]]:
    return api.data(api.get(f"/api/v1/boards/{board['id']}/lists"))
