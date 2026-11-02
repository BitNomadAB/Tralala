from __future__ import annotations

import io
import json
import tarfile
import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from conftest import Api
from fastapi.testclient import TestClient
from test_loop_generation import _analysis_json

from app.services import repo_snapshot, runtime

SHA = "abc123def456abc123def456abc123def456abcd"


def _tarball(files: dict[str, bytes], *, prefix: str = "acme-app") -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path, payload in files.items():
            info = tarfile.TarInfo(f"{prefix}-{SHA}/{path}")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


class GitHub:
    """A GitHub stand-in: commits, the 302 to codeload, and the archive itself."""

    def __init__(
        self,
        archive: bytes | None = None,
        *,
        status: int = 200,
        redirect_to: str | None = None,
    ) -> None:
        self.archive = archive if archive is not None else _tarball({"README.md": b"# App\n"})
        self.status = status
        self.redirect_to = redirect_to
        self.requests: list[str] = []
        self.authorizations: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        self.authorizations.append(request.headers.get("authorization", ""))
        if url.endswith("/commits/main"):
            if self.status != 200:
                return httpx.Response(self.status, json={"message": "nope"})
            return httpx.Response(200, json={"sha": SHA})
        if "/tarball/" in url:
            location = self.redirect_to or f"https://codeload.github.com/acme/app/legacy.tar.gz/{SHA}"
            return httpx.Response(302, headers={"location": location})
        if url.startswith("https://codeload.github.com/"):
            return httpx.Response(200, content=self.archive)
        return httpx.Response(404, json={"message": "not found"})


@pytest.fixture()
def github(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., GitHub]]:
    def install(archive: bytes | None = None, **kwargs: Any) -> GitHub:
        handler = GitHub(archive, **kwargs)
        monkeypatch.setattr(repo_snapshot, "TRANSPORT", httpx.MockTransport(handler))
        return handler

    yield install
    monkeypatch.setattr(repo_snapshot, "TRANSPORT", None)


def _services(client: TestClient) -> Any:
    return client.app.state.services  # type: ignore[attr-defined]


def _linked_repository(api: Api, board_id: str, *, branch: str = "main") -> dict[str, Any]:
    repository = api.data(
        api.post(
            "/api/v1/repositories",
            json={
                "name": "acme app",
                "url": "https://github.com/acme/app",
                "branch": branch,
                "token": "ghp_repository_token_value",
            },
        )
    )
    api.data(api.patch(f"/api/v1/boards/{board_id}", json={"repository_ids": [repository["id"]]}))
    return repository


def test_a_snapshot_orders_the_files_an_analysis_needs_first(
    api: Api, client: TestClient, board: dict[str, Any], github: Callable[..., GitHub]
) -> None:
    _linked_repository(api, board["id"])
    archive = _tarball(
        {
            "src/deep/nested/module.py": b"def work():\n    return 1\n",
            "package.json": b'{"name":"app"}\n',
            "docs/guide.md": b"# Guide\n",
            "README.md": b"# App\n",
            "node_modules/left-pad/index.js": b"module.exports = 1\n",
            "package-lock.json": b"{}",
            "logo.png": b"\x89PNG\r\n\x1a\n\x00\x00",
            "blob.bin": b"\x00\x01\x02\x03",
        }
    )
    github(archive)

    entries = _services(client).repo_snapshot.for_board(board["id"])

    assert len(entries) == 1
    entry = entries[0]
    assert entry["commit_sha"] == SHA
    assert entry["branch"] == "main"
    assert entry["truncated"] is False
    assert entry["file_count"] == 4
    assert [item["path"] for item in entry["files"]] == [
        "README.md",
        "docs/guide.md",
        "package.json",
        "src/deep/nested/module.py",
    ]


def test_too_many_files_stop_at_the_cap(
    api: Api, client: TestClient, board: dict[str, Any], github: Callable[..., GitHub]
) -> None:
    _linked_repository(api, board["id"])
    github(_tarball({f"src/file_{index:03d}.py": b"x = 1\n" for index in range(250)}))

    entry = _services(client).repo_snapshot.for_board(board["id"])[0]

    assert entry["file_count"] == repo_snapshot.MAX_FILES
    assert entry["truncated"] is True


def test_too_much_text_stops_at_the_cap(
    api: Api, client: TestClient, board: dict[str, Any], github: Callable[..., GitHub]
) -> None:
    _linked_repository(api, board["id"])
    chunk = b"x" * 100_000
    github(_tarball({f"src/big_{index}.py": chunk for index in range(4)}))

    entry = _services(client).repo_snapshot.for_board(board["id"])[0]

    assert entry["truncated"] is True
    assert sum(item["bytes"] for item in entry["files"]) <= repo_snapshot.MAX_TEXT_BYTES


def test_an_archive_over_the_limit_is_refused(
    api: Api, client: TestClient, board: dict[str, Any], github: Callable[..., GitHub]
) -> None:
    _linked_repository(api, board["id"])
    github(b"\x1f\x8b" + b"0" * (repo_snapshot.ARCHIVE_MAX_BYTES + 1024))

    entry = _services(client).repo_snapshot.for_board(board["id"])[0]

    assert entry["error"] == "too_large"
    assert "files" not in entry


def test_a_redirect_away_from_codeload_is_refused(
    api: Api, client: TestClient, board: dict[str, Any], github: Callable[..., GitHub]
) -> None:
    _linked_repository(api, board["id"])
    github(redirect_to="https://evil.example.com/archive.tar.gz")

    entry = _services(client).repo_snapshot.for_board(board["id"])[0]

    assert entry["error"] == "redirect_refused"


@pytest.mark.parametrize(
    ("status", "expected"), [(401, "unauthorized"), (404, "not_found"), (429, "rate_limited")]
)
def test_a_refused_repository_becomes_an_entry_not_a_failure(
    api: Api,
    client: TestClient,
    board: dict[str, Any],
    github: Callable[..., GitHub],
    status: int,
    expected: str,
) -> None:
    _linked_repository(api, board["id"])
    github(status=status)

    entry = _services(client).repo_snapshot.for_board(board["id"])[0]

    assert entry["error"] == expected
    assert entry["name"] == "acme app"


def test_the_same_commit_produces_the_same_snapshot(
    api: Api, client: TestClient, board: dict[str, Any], github: Callable[..., GitHub]
) -> None:
    _linked_repository(api, board["id"])
    github(_tarball({"b.md": b"b", "a.md": b"a", "src/x.py": b"x = 1\n"}))
    service = _services(client).repo_snapshot

    first = service.for_board(board["id"])
    second = service.for_board(board["id"])

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_a_run_carries_the_snapshot_and_records_only_the_commit(
    api: Api,
    board: dict[str, Any],
    loop: dict[str, Any],
    github: Callable[..., GitHub],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The model sees the file content; the run record keeps the commit and the paths."""
    _linked_repository(api, board["id"])
    github(_tarball({"README.md": b"# App\n", "src/app.py": b"print('hello')\n"}))
    agent = api.data(
        api.post(
            "/api/v1/agents",
            json={
                "name": "Snapshot agent",
                "connection_type": "openai_compatible",
                "base_url": "http://127.0.0.1:8080/v1",
                "model": "test-model",
                "role_template_id": next(
                    role["id"]
                    for role in api.data(api.get("/api/v1/role-templates"))
                    if role["builtin_key"] == "qa_engineer"
                ),
            },
        )
    )
    assert agent["id"]
    base = f"/api/v1/boards/{board['id']}/loops/{loop['id']}"
    api.data(api.put(f"{base}/documents/info", json={"content": "Intent"}))

    seen: dict[str, Any] = {}

    def fake_call(settings: Any, agent_row: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        seen["system_prompt"] = kwargs.get("system_prompt", "")
        seen["messages"] = kwargs.get("messages", [])
        return {
            "ok": True,
            "error": None,
            "text": _analysis_json(),
            "model": "test-model",
            "usage": {},
        }

    with monkeypatch.context() as patch:
        patch.setattr(runtime, "call_completion", fake_call)
        started = api.data(api.post(f"{base}/generation-runs", json={"purpose": "analysis"}))
        run = _wait(api, f"{base}/generation-runs", started["id"])

    assert run["status"] == "completed", run

    user_message = seen["messages"][0]["content"]
    assert "Repository snapshot" in user_message
    assert "src/app.py" in user_message
    assert "print('hello')" in user_message
    assert "2 MB" in user_message and "200 files" in user_message
    # Framed as data, never as instructions.
    assert "untrusted" in user_message
    assert "untrusted" in seen["system_prompt"] or "data to analyse" in seen["system_prompt"]

    sources = run["source_revisions"]
    repositories = sources["repositories"]
    assert repositories == [
        {
            "id": repositories[0]["id"],
            "name": "acme app",
            "branch": "main",
            "commit_sha": SHA,
            "file_count": 2,
            "truncated": False,
        }
    ]
    # Contents and paths stay in the run's own record; the API never returns them.
    assert "files" not in repositories[0]
    assert "print('hello')" not in json.dumps(run)
    assert "ghp_repository_token_value" not in json.dumps(run)


def _wait(api: Api, url: str, run_id: str, *, attempts: int = 60) -> dict[str, Any]:
    for _ in range(attempts):
        run = api.data(api.get(f"{url}/{run_id}"))
        if run["status"] in {"completed", "failed", "cancelled"}:
            return run
        time.sleep(0.05)
    raise AssertionError("run did not finish")
