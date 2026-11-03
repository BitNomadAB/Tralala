"""LoopHistoryService on the in-memory fakes: finalization writes one hashed, self-contained
snapshot and completes the Loop, a second finalization returns the same record, and the legacy
import stores a reference that is never a Loop."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.core.context import ActorContext
from app.core.errors import Conflict, Forbidden, NotFound
from app.db.generated.board import AttachmentsRow
from app.schemas.loops import LegacyImportRequest
from app.services.loop_history import (
    LEGACY_LABEL,
    LoopHistoryService,
    canonical,
    fts_query,
)
from tests.unit.fakes.board import (
    BOARD_ID,
    BoardState,
    FakeBoardChecks,
    FakeBoardUnitOfWork,
    card_row,
    list_row,
    loop_row,
)

NOW = "2026-11-03T10:00:00Z"
LOOP = "loop-a"
ADA = ActorContext(
    actor_id="actor-1", actor_type="user", actor_name="Ada", scopes=frozenset({"boards:write"})
)
BOT = ActorContext(
    actor_id="bot", actor_type="agent", actor_name="Bot", scopes=frozenset({"boards:write"})
)


@dataclass
class Files:
    root: Path

    def attachments_dir(self, board_id: str) -> Path:
        return self.root / board_id


@dataclass
class Index:
    fts: bool = False

    def fts_available(self, board_id: str) -> bool:
        del board_id
        return self.fts


class Ids:
    def __init__(self) -> None:
        self.issued = 0

    def __call__(self) -> str:
        self.issued += 1
        return f"id-{self.issued}"


def make(
    tmp_path: Path, *, fts: bool = False
) -> tuple[LoopHistoryService, BoardState, FakeBoardUnitOfWork]:
    state = BoardState()
    state.loops[LOOP] = loop_row(LOOP, stage="qa")
    state.lists["list-a"] = list_row("list-a", LOOP, 1)
    state.cards["card-1"] = card_row("card-1", "list-a", LOOP)
    store = FakeBoardUnitOfWork(state)
    service = LoopHistoryService(
        FakeBoardChecks(), store, Files(tmp_path), Index(fts), clock=lambda: NOW, new_id=Ids()
    )
    return service, state, store


def finalize(
    service: LoopHistoryService, store: FakeBoardUnitOfWork, **extra: str | None
) -> dict[str, object]:
    with store.writer(BOARD_ID) as repos:
        return service.finalize(
            repos,
            LOOP,
            actor=ADA,
            qa_approval_id=extra.get("qa_approval_id", "approval-1"),
            attestation={"by": "Ada"},
            board_id=BOARD_ID,
        )


def test_finalization_needs_an_accepted_qa(tmp_path: Path) -> None:
    service, state, store = make(tmp_path)
    with pytest.raises(Conflict) as refused:
        finalize(service, store, qa_approval_id=None)
    assert refused.value.code == "qa_incomplete"
    assert state.history == {}


def test_finalization_completes_the_loop_with_a_hashed_snapshot(tmp_path: Path) -> None:
    service, state, store = make(tmp_path)
    before = state.loops[LOOP].version
    record = finalize(service, store)
    loop = state.loops[LOOP]
    (stored,) = state.history.values()
    assert (loop.stage, loop.completed_at, loop.history_id) == ("completed", NOW, stored.id)
    assert loop.version == before + 1
    assert stored.content_hash == hashlib.sha256(stored.envelope_json.encode()).hexdigest()
    envelope = json.loads(stored.envelope_json)
    assert envelope["loop"]["completed_at"] == NOW
    assert envelope["qa_attestation"] == {"by": "Ada"}
    assert [ticket["id"] for ticket in envelope["delivery"]["tickets"]] == ["card-1"]
    assert record["envelope"] == envelope
    assert "envelope_json" not in record
    assert "search_text" not in record
    assert [entry.action for entry in state.activity] == ["loop.completed"]


def test_a_second_finalization_returns_the_same_record(tmp_path: Path) -> None:
    service, state, store = make(tmp_path)
    first = finalize(service, store)
    second = finalize(service, store)
    assert first["id"] == second["id"]
    assert len(state.history) == 1


def attachment(
    state: BoardState, attachment_id: str, data: bytes, *, sha: str | None = None
) -> None:
    state.attachments[attachment_id] = AttachmentsRow(
        id=attachment_id,
        card_id="card-1",
        discussion_id=None,
        message_id=None,
        original_filename=f"{attachment_id}.txt",
        stored_filename=f"stored-{attachment_id}",
        content_type="text/plain",
        size_bytes=len(data),
        sha256=sha or hashlib.sha256(data).hexdigest(),
        uploaded_by_actor_id="actor-1",
        created_at=NOW,
        deleted_at=None,
    )


def test_evidence_is_embedded_only_when_its_bytes_match_and_the_manifest_says_so(
    tmp_path: Path,
) -> None:
    service, state, store = make(tmp_path)
    directory = tmp_path / BOARD_ID
    directory.mkdir()
    (directory / "stored-good").write_bytes(b"good")
    (directory / "stored-tampered").write_bytes(b"changed")
    attachment(state, "good", b"good")
    attachment(state, "tampered", b"original")
    finalize(service, store)
    inclusion = {row.filename: row.inclusion for row in state.artifacts}
    assert inclusion == {"good.txt": "included", "tampered.txt": "excluded"}
    (stored,) = state.history.values()
    manifest = json.loads(stored.envelope_json)["assets"]["manifest"]
    assert {entry["filename"]: entry["inclusion"] for entry in manifest} == inclusion
    # The hash is of the final text, after the manifest was marked.
    assert stored.content_hash == hashlib.sha256(stored.envelope_json.encode()).hexdigest()


def test_existing_and_detail_read_the_stored_snapshot(tmp_path: Path) -> None:
    service, _, store = make(tmp_path)
    with pytest.raises(NotFound):
        service.existing(BOARD_ID, LOOP)
    record = finalize(service, store)
    assert service.existing(BOARD_ID, LOOP)["id"] == record["id"]
    assert service.detail(BOARD_ID, str(record["id"]))["artifacts"] == []
    with pytest.raises(NotFound):
        service.detail(BOARD_ID, "missing")


def test_search_finds_by_text_and_filters_by_source(tmp_path: Path) -> None:
    service, _, store = make(tmp_path)
    finalize(service, store)
    service.import_legacy(
        ADA, BOARD_ID, LegacyImportRequest(loop_name="Old project", raw_text="payment notes")
    )
    found = service.search(BOARD_ID, q="payment")
    assert (found["engine"], found["total"]) == ("like", 1)
    native = service.search(BOARD_ID, source_kind="native")
    assert native["total"] == 1
    everything = service.search(BOARD_ID, limit=1)
    assert (everything["total"], everything["has_more"]) == (2, True)


def test_search_uses_the_full_text_index_when_the_board_has_one(tmp_path: Path) -> None:
    service, _, _ = make(tmp_path, fts=True)
    service.import_legacy(ADA, BOARD_ID, LegacyImportRequest(loop_name="Old", raw_text="payments"))
    found = service.search(BOARD_ID, q="pay")
    assert (found["engine"], found["total"]) == ("fts5", 1)
    assert fts_query('say "hi" there') == '"say"* AND " hi "* AND "there"*'


def test_a_legacy_import_is_a_human_labelled_reference_and_replays_its_key(
    tmp_path: Path,
) -> None:
    service, state, _ = make(tmp_path)
    with pytest.raises(Forbidden):
        service.import_legacy(BOT, BOARD_ID, LegacyImportRequest(loop_name="x", raw_text="y"))
    request = LegacyImportRequest(
        loop_name="Old", raw_text="notes", reported_qa_status="passed", idempotency_key="k-1"
    )
    record, replayed = service.import_legacy(ADA, BOARD_ID, request)
    assert replayed is False
    assert record["label"] == LEGACY_LABEL
    assert record["warnings"] == [
        "No document content was supplied",
        "Reported QA status is source information, not a verified Tralala QA result",
    ]
    again, replayed = service.import_legacy(ADA, BOARD_ID, request)
    assert (again["id"], replayed) == (record["id"], True)
    assert len(state.history) == 1
    assert state.loops[LOOP].stage == "qa"


def test_canonical_json_is_stable() -> None:
    assert canonical({"b": 1, "a": [2]}) == '{"a":[2],"b":1}'
