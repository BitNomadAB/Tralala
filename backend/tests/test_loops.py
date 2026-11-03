"""Loop planning, delivery and history: the specification's acceptance scenarios."""

from __future__ import annotations

import uuid
from typing import Any

from conftest import Api


def _base(api: Api, board: dict[str, Any], loop: dict[str, Any]) -> str:
    return f"/api/v1/boards/{board['id']}/loops/{loop['id']}"


def _documents(api: Api, board: dict[str, Any], loop: dict[str, Any]) -> dict[str, Any]:
    return api.data(api.get(f"{_base(api, board, loop)}/documents"))


def _revisions(api: Api, board: dict[str, Any], loop: dict[str, Any], *kinds: str) -> dict:
    documents = _documents(api, board, loop)["documents"]
    return {kind: documents[kind]["current_revision_id"] for kind in kinds}


def _version(api: Api, board: dict[str, Any], loop: dict[str, Any]) -> int:
    return api.data(api.get(_base(api, board, loop)))["version"]


def _analysis_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "outcome": "Verify email addresses before sign-in",
        "scope": ["send a verification mail"],
        "non_goals": ["SMS verification"],
        "findings": [
            {
                "id": "F-01",
                "title": "Sign-in code can be reused",
                "category": "reuse",
                "technical_detail": "backend/app/services/auth.py",
                "plain_language": "The existing sign-in code can be extended.",
            },
            {
                "id": "F-02",
                "title": "No mail provider is configured",
                "category": "blocker",
                "technical_detail": "no transport in settings",
                "plain_language": (
                    "There is no way to send mail yet, so someone must choose a provider "
                    "before this can work."
                ),
            },
        ],
        "assumptions": ["Users own a working address"],
        "open_questions": ["Which provider?"],
        "options": ["Queue in app", "Third-party provider"],
        "recommendation": "Choose a provider first.",
        "verification": ["Unverified sign-in is rejected"],
        "sources": ["docs/architecture.md"],
        "repository_revision": "efb1585",
    }
    payload.update(overrides)
    return payload


def _submit_analysis(
    api: Api, board: dict[str, Any], loop: dict[str, Any], **overrides: Any
) -> None:
    api.data(
        api.post(
            f"{_base(api, board, loop)}/candidates",
            json={"kind": "analysis", "analysis": _analysis_payload(**overrides)},
        )
    )


def _approve_analysis(api: Api, board: dict[str, Any], loop: dict[str, Any]) -> dict[str, Any]:
    revisions = _revisions(api, board, loop, "info", "analysis_ai", "analysis")
    return api.data(
        api.post(
            f"{_base(api, board, loop)}/reviews/analysis",
            json={
                "decision": "approved",
                "version": _version(api, board, loop),
                "revisions": revisions,
            },
        )
    )


def _plan(
    *,
    phase_id: str,
    ticket_id: str,
    extra_phases: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    phases = [
        {
            "id": phase_id,
            "number": 1,
            "name": "Database update",
            "objective": "Store verification state",
            "tickets": [
                {
                    "id": ticket_id,
                    "title": "Add verification columns",
                    "instructions": "Add the columns and a migration.",
                    "acceptance_criteria": ["columns exist"],
                    "expected_evidence": ["migration revision"],
                }
            ],
        }
    ]
    phases.extend(extra_phases or [])
    return {"kind": "roadmap", "plan": {"summary": "Plan", "phases": phases}}


def _publish_plan(api: Api, board: dict[str, Any], loop: dict[str, Any], plan: dict) -> None:
    api.data(api.post(f"{_base(api, board, loop)}/candidates", json=plan))
    revisions = _revisions(
        api, board, loop, "info", "analysis_ai", "analysis", "roadmap_ai", "roadmap"
    )
    api.data(
        api.post(
            f"{_base(api, board, loop)}/reviews/roadmap",
            json={
                "decision": "approved",
                "version": _version(api, board, loop),
                "revisions": revisions,
            },
        )
    )


def _ready_loop(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    ticket_id = str(uuid.uuid4())
    api.data(
        api.put(
            f"{_base(api, board, loop)}/documents/info",
            json={"content": "Users must confirm their email address."},
        )
    )
    _submit_analysis(api, board, loop)
    _approve_analysis(api, board, loop)
    _publish_plan(
        api,
        board,
        loop,
        _plan(phase_id=str(uuid.uuid4()), ticket_id=ticket_id),
    )
    return ticket_id, api.data(api.get(f"{_base(api, board, loop)}/cards"))[0]


def _agent_headers(api: Api, scopes: list[str]) -> dict[str, str]:
    credential = api.data(
        api.post("/api/v1/credentials", json={"name": f"agent-{uuid.uuid4()}", "scopes": scopes})
    )
    return {"Authorization": f"Bearer {credential['token']}"}


# --- ownership --------------------------------------------------------------------


def test_a_board_holds_independent_loops(
    api: Api, board: dict[str, Any], loop: dict[str, Any], second_loop: dict[str, Any]
) -> None:
    first_lists = api.data(api.get(f"/api/v1/boards/{board['id']}/loops/{loop['id']}/lists"))
    second_lists = api.data(
        api.get(f"/api/v1/boards/{board['id']}/loops/{second_loop['id']}/lists")
    )
    assert {item["id"] for item in first_lists}.isdisjoint({item["id"] for item in second_lists})
    assert all(item["loop_id"] == loop["id"] for item in first_lists)

    ticket = api.data(
        api.post(
            f"{_base(api, board, loop)}/cards",
            json={"list_id": first_lists[0]["id"], "title": "Only in loop one"},
        )
    )
    assert api.data(api.get(f"{_base(api, board, second_loop)}/cards")) == []

    api.data(api.post(f"{_base(api, board, loop)}/cards/{ticket['id']}/archive"))
    crossed = api.post(
        f"{_base(api, board, loop)}/cards/{ticket['id']}/move",
        json={"version": 2, "list_id": second_lists[0]["id"], "position": 0},
    )
    assert crossed.status_code == 409
    assert crossed.json()["error"]["code"] == "loop_mismatch"


def test_loop_overview_cost_does_not_grow_with_the_number_of_loops(
    api: Api, board: dict[str, Any]
) -> None:
    """The board overview renders every Loop, so its statements must stay constant."""
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    counted = {"statements": 0}

    def count_statement(*_args: Any, **_kwargs: Any) -> None:
        counted["statements"] += 1

    event.listen(Engine, "before_cursor_execute", count_statement)
    try:
        loops_url = f"/api/v1/boards/{board['id']}/loops"
        api.data(api.post(loops_url, json={"name": "First"}))
        counted["statements"] = 0
        api.data(api.get(loops_url))
        small = counted["statements"]

        for index in range(18):
            api.data(api.post(loops_url, json={"name": f"Loop {index}"}))
        counted["statements"] = 0
        loops = api.data(api.get(loops_url))
        large = counted["statements"]
    finally:
        event.remove(Engine, "before_cursor_execute", count_statement)

    assert len(loops) == 19
    assert large <= small + 1, (small, large)
    assert large <= 15, large


def test_board_ticket_aggregate_names_the_owning_loop(
    api: Api, board: dict[str, Any], loop: dict[str, Any], second_loop: dict[str, Any]
) -> None:
    for owner, title in ((loop, "First ticket"), (second_loop, "Second ticket")):
        lists = api.data(api.get(f"{_base(api, board, owner)}/lists"))
        api.data(
            api.post(
                f"{_base(api, board, owner)}/cards",
                json={"list_id": lists[0]["id"], "title": title},
            )
        )

    tickets = api.data(api.get(f"/api/v1/boards/{board['id']}/tickets"))
    assert {ticket["title"]: ticket["loop_name"] for ticket in tickets} == {
        "First ticket": "Test loop",
        "Second ticket": "Second loop",
    }
    assert {ticket["loop_id"] for ticket in tickets} == {loop["id"], second_loop["id"]}
    assert all(ticket["loop_key"] for ticket in tickets)

    filtered = api.data(api.get(f"/api/v1/boards/{board['id']}/tickets", params={"q": "Second"}))
    assert [ticket["title"] for ticket in filtered] == ["Second ticket"]

    api.data(api.post(f"{_base(api, board, second_loop)}/archive"))
    remaining = api.data(api.get(f"/api/v1/boards/{board['id']}/tickets"))
    assert [ticket["title"] for ticket in remaining] == ["First ticket"]


def test_new_loop_starts_with_five_empty_documents(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    documents = _documents(api, board, loop)["documents"]
    assert set(documents) == {"info", "analysis_ai", "analysis", "roadmap_ai", "roadmap"}
    assert all(document["state"] == "empty" for document in documents.values())
    loop_row = api.data(api.get(_base(api, board, loop)))
    assert loop_row["stage"] == "draft"
    assert loop_row["plan"] is None
    assert api.data(api.get(f"{_base(api, board, loop)}/cards")) == []


def test_lists_of_another_loop_are_rejected(
    api: Api, board: dict[str, Any], loop: dict[str, Any], second_loop: dict[str, Any]
) -> None:
    foreign = api.data(api.get(f"/api/v1/boards/{board['id']}/loops/{second_loop['id']}/lists"))
    response = api.post(
        f"{_base(api, board, loop)}/cards",
        json={"list_id": foreign[0]["id"], "title": "Mismatch"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "loop_mismatch"


# --- documents and permissions ----------------------------------------------------


def test_a_worker_may_seed_info_before_planning(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    """A person and their agent agree the intent; the worker writes it while it is speculative."""
    headers = _agent_headers(api, ["loops:write"])
    response = api.put(
        f"{_base(api, board, loop)}/documents/info",
        json={"content": "Written by the worker, agreed with the developer"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    info = _documents(api, board, loop)["documents"]["info"]
    assert info["current_content"] == "Written by the worker, agreed with the developer"
    assert info["state"] == "ready_for_review"


def test_a_worker_cannot_change_info_once_planning_started(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    _ready_loop(api, board, loop)
    headers = _agent_headers(api, ["loops:write"])
    response = api.put(
        f"{_base(api, board, loop)}/documents/info",
        json={"content": "Requirements changed by an agent"},
        headers=headers,
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "human_action_required"
    assert _documents(api, board, loop)["documents"]["info"]["current_content"].startswith(
        "Users must confirm"
    )


def test_info_changes_make_approvals_and_execution_stale(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    _, card = _ready_loop(api, board, loop)
    api.data(
        api.put(
            f"{_base(api, board, loop)}/documents/info",
            json={"content": "Requirements changed after approval."},
        )
    )
    loop_row = api.data(api.get(_base(api, board, loop)))
    assert loop_row["stage"] == "replanning"
    assert loop_row["documents"]["analysis"]["state"] == "stale"
    assert loop_row["documents"]["roadmap"]["state"] == "stale"

    blocked = api.patch(
        f"{_base(api, board, loop)}/cards/{card['id']}",
        json={
            "version": api.data(api.get(f"{_base(api, board, loop)}/cards/{card['id']}"))[
                "version"
            ],
            "completed": True,
        },
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "plan_change_required"

    history = api.data(api.get(f"{_base(api, board, loop)}/documents/info/revisions"))
    assert len(history) == 2


def test_roadmap_needs_a_current_analysis_approval(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    api.data(api.put(f"{_base(api, board, loop)}/documents/info", json={"content": "Intent"}))
    _submit_analysis(api, board, loop)
    plan = _plan(phase_id=str(uuid.uuid4()), ticket_id=str(uuid.uuid4()))
    response = api.post(f"{_base(api, board, loop)}/candidates", json=plan)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "approval_required"


def test_analysis_keeps_plain_language_and_traceability(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    api.data(api.put(f"{_base(api, board, loop)}/documents/info", json={"content": "Intent"}))
    _submit_analysis(api, board, loop)
    human = _documents(api, board, loop)["documents"]["analysis"]["current_content"]
    assert "someone must choose a provider" in human
    assert "Traceability" in human
    assert "F-02" in human


def test_material_findings_need_plain_language(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    api.data(api.put(f"{_base(api, board, loop)}/documents/info", json={"content": "Intent"}))
    response = api.post(
        f"{_base(api, board, loop)}/candidates",
        json={
            "kind": "analysis",
            "analysis": _analysis_payload(
                findings=[
                    {
                        "id": "F-01",
                        "title": "Risk without explanation",
                        "category": "legal",
                        "technical_detail": "detail",
                        "plain_language": "   ",
                    }
                ]
            ),
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"]["finding_ids"] == ["F-01"]


def test_review_requires_the_exact_revisions(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    api.data(api.put(f"{_base(api, board, loop)}/documents/info", json={"content": "Intent"}))
    _submit_analysis(api, board, loop)
    revisions = _revisions(api, board, loop, "info", "analysis_ai", "analysis")
    api.data(
        api.put(
            f"{_base(api, board, loop)}/documents/info",
            json={"content": "Changed while reviewing"},
        )
    )
    stale = api.post(
        f"{_base(api, board, loop)}/reviews/analysis",
        json={
            "decision": "approved",
            "version": _version(api, board, loop),
            "revisions": revisions,
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "document_stale"


def test_agents_cannot_approve(api: Api, board: dict[str, Any], loop: dict[str, Any]) -> None:
    api.data(api.put(f"{_base(api, board, loop)}/documents/info", json={"content": "Intent"}))
    _submit_analysis(api, board, loop)
    revisions = _revisions(api, board, loop, "info", "analysis_ai", "analysis")
    headers = _agent_headers(api, ["boards:read", "cards:read"])
    response = api.post(
        f"{_base(api, board, loop)}/reviews/analysis",
        json={
            "decision": "approved",
            "version": _version(api, board, loop),
            "revisions": revisions,
        },
        headers=headers,
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "human_action_required"


# --- plans, identities and publication ---------------------------------------------


def test_plan_rejects_cycles_and_broken_references(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    api.data(api.put(f"{_base(api, board, loop)}/documents/info", json={"content": "Intent"}))
    _submit_analysis(api, board, loop)
    _approve_analysis(api, board, loop)

    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    cycle = {
        "kind": "roadmap",
        "plan": {
            "phases": [
                {
                    "id": str(uuid.uuid4()),
                    "number": 1,
                    "name": "One",
                    "tickets": [
                        {
                            "id": first,
                            "title": "A",
                            "instructions": "a",
                            "prerequisite_ticket_ids": [second],
                        },
                        {
                            "id": second,
                            "title": "B",
                            "instructions": "b",
                            "prerequisite_ticket_ids": [first],
                        },
                    ],
                }
            ]
        },
    }
    response = api.post(f"{_base(api, board, loop)}/candidates", json=cycle)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_dependency_graph"

    missing = {
        "kind": "roadmap",
        "plan": {
            "phases": [
                {
                    "id": str(uuid.uuid4()),
                    "number": 1,
                    "name": "One",
                    "tickets": [
                        {
                            "id": str(uuid.uuid4()),
                            "title": "A",
                            "instructions": "a",
                            "prerequisite_ticket_ids": [str(uuid.uuid4())],
                        }
                    ],
                }
            ]
        },
    }
    response = api.post(f"{_base(api, board, loop)}/candidates", json=missing)
    assert response.status_code == 422
    assert api.data(api.get(f"{_base(api, board, loop)}/cards")) == []


def test_unknown_human_action_is_rejected(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    api.data(api.put(f"{_base(api, board, loop)}/documents/info", json={"content": "Intent"}))
    _submit_analysis(api, board, loop)
    _approve_analysis(api, board, loop)
    plan = _plan(
        phase_id=str(uuid.uuid4()),
        ticket_id=str(uuid.uuid4()),
    )
    plan["plan"]["phases"][0]["tickets"][0].update(
        {"required_actor": "human", "human_action_reason": "", "human_instructions": ""}
    )
    response = api.post(f"{_base(api, board, loop)}/candidates", json=plan)
    assert response.status_code == 422


def test_ticket_keys_are_unique_and_stable(
    api: Api, board: dict[str, Any], loop: dict[str, Any], second_loop: dict[str, Any]
) -> None:
    for current in (loop, second_loop):
        api.data(
            api.put(f"{_base(api, board, current)}/documents/info", json={"content": "Intent"})
        )
        _submit_analysis(api, board, current)
        _approve_analysis(api, board, current)
    first_phase = str(uuid.uuid4())
    _publish_plan(
        api,
        board,
        loop,
        _plan(
            phase_id=first_phase,
            ticket_id=str(uuid.uuid4()),
            extra_phases=[
                {
                    "id": str(uuid.uuid4()),
                    "number": 2,
                    "name": "Database update",
                    "tickets": [{"id": str(uuid.uuid4()), "title": "Second", "instructions": "b"}],
                }
            ],
        ),
    )
    _publish_plan(
        api,
        board,
        second_loop,
        _plan(phase_id=str(uuid.uuid4()), ticket_id=str(uuid.uuid4())),
    )
    keys = [
        card["ticket_key"]
        for current in (loop, second_loop)
        for card in api.data(api.get(f"{_base(api, board, current)}/cards"))
    ]
    assert len(keys) == len(set(keys)) == 3
    first_key = keys[0]
    api.data(
        api.patch(
            f"{_base(api, board, loop)}",
            json={"version": _version(api, board, loop), "name": "Renamed loop"},
        )
    )
    renamed = [card["ticket_key"] for card in api.data(api.get(f"{_base(api, board, loop)}/cards"))]
    assert first_key in renamed


def test_publication_is_idempotent(api: Api, board: dict[str, Any], loop: dict[str, Any]) -> None:
    api.data(api.put(f"{_base(api, board, loop)}/documents/info", json={"content": "Intent"}))
    _submit_analysis(api, board, loop)
    approval = _approve_analysis(api, board, loop)
    plan = _plan(phase_id=str(uuid.uuid4()), ticket_id=str(uuid.uuid4()))
    api.data(api.post(f"{_base(api, board, loop)}/candidates", json=plan))
    revisions = _revisions(
        api, board, loop, "info", "analysis_ai", "analysis", "roadmap_ai", "roadmap"
    )
    body = {
        "decision": "approved",
        "version": _version(api, board, loop),
        "revisions": revisions,
    }
    first = api.data(api.post(f"{_base(api, board, loop)}/reviews/roadmap", json=body))
    assert first["scope"] == "roadmap"
    assert approval["decision"] == "approved"
    retry = api.post(f"{_base(api, board, loop)}/reviews/roadmap", json=body)
    assert retry.status_code == 409
    assert retry.json()["error"]["code"] == "version_conflict"
    cards = api.data(api.get(f"{_base(api, board, loop)}/cards"))
    assert len(cards) == 1


def test_readiness_shown_and_readiness_enforced_agree(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    """The endpoint and the completion transition must never disagree about a blocker."""
    second_phase = str(uuid.uuid4())
    first_ticket = str(uuid.uuid4())
    second_ticket = str(uuid.uuid4())
    api.data(
        api.put(
            f"{_base(api, board, loop)}/documents/info",
            json={"content": "Users must confirm their email address."},
        )
    )
    _submit_analysis(api, board, loop)
    _approve_analysis(api, board, loop)
    _publish_plan(
        api,
        board,
        loop,
        _plan(
            phase_id=str(uuid.uuid4()),
            ticket_id=first_ticket,
            extra_phases=[
                {
                    "id": second_phase,
                    "number": 2,
                    "name": "Second phase",
                    "objective": "Ship it",
                    "prerequisite_phase_ids": [],
                    "tickets": [
                        {
                            "id": second_ticket,
                            "title": "Publish the result",
                            "prerequisite_ticket_ids": [first_ticket],
                        }
                    ],
                }
            ],
        ),
    )
    cards = {card["id"]: card for card in api.data(api.get(f"{_base(api, board, loop)}/cards"))}
    readiness = api.data(api.get(f"{_base(api, board, loop)}/readiness"))
    blocked = next(
        item for item in readiness["items"] if item.get("card_id") == cards[second_ticket]["id"]
    )
    assert blocked["ready"] is False
    assert blocked["blockers"]

    attempt = api.patch(
        f"{_base(api, board, loop)}/cards/{cards[second_ticket]['id']}",
        json={"version": cards[second_ticket]["version"], "completed": True},
    )
    assert attempt.status_code == 409
    body = attempt.json()["error"]
    assert body["code"] == "ticket_blocked"
    assert body["details"]["blockers"] == blocked["blockers"]


def test_approved_ticket_scope_cannot_be_edited_through_a_card_endpoint(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    _, card = _ready_loop(api, board, loop)
    response = api.patch(
        f"{_base(api, board, loop)}/cards/{card['id']}",
        json={"version": card["version"], "description": "Silently widened scope"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "plan_change_required"


# --- readiness, human gates and completion ------------------------------------------


def test_human_gate_blocks_only_its_downstream_phase(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    api.data(api.put(f"{_base(api, board, loop)}/documents/info", json={"content": "Intent"}))
    _submit_analysis(api, board, loop)
    _approve_analysis(api, board, loop)
    phase1, phase2, phase3, phase6 = (str(uuid.uuid4()) for _ in range(4))
    gate_id = str(uuid.uuid4())
    plan = {
        "kind": "roadmap",
        "plan": {
            "phases": [
                {
                    "id": phase1,
                    "number": 1,
                    "name": "Prepare",
                    "tickets": [{"id": str(uuid.uuid4()), "title": "Prepare", "instructions": "p"}],
                },
                {
                    "id": phase2,
                    "number": 2,
                    "name": "Account setup",
                    "prerequisite_phase_ids": [phase1],
                    "tickets": [
                        {
                            "id": gate_id,
                            "title": "Open provider account",
                            "instructions": "n/a",
                            "required_actor": "human",
                            "execution_mode": "pre_phase_gate",
                            "human_action_reason": "Only a person can open the account",
                            "human_instructions": "Create the account and record the sender",
                        }
                    ],
                },
                {
                    "id": phase3,
                    "number": 3,
                    "name": "Delivery",
                    "tickets": [
                        {
                            "id": str(uuid.uuid4()),
                            "title": "Send mail",
                            "instructions": "s",
                        }
                    ],
                },
                {
                    "id": phase6,
                    "number": 6,
                    "name": "Launch",
                    "prerequisite_phase_ids": [phase3],
                    "prerequisite_ticket_ids": [gate_id],
                    "tickets": [
                        {
                            "id": str(uuid.uuid4()),
                            "title": "Announce",
                            "instructions": "a",
                            "prerequisite_ticket_ids": [gate_id],
                        }
                    ],
                },
            ]
        },
    }
    _publish_plan(api, board, loop, plan)
    readiness = api.data(api.get(f"{_base(api, board, loop)}/readiness"))
    phases = {phase["number"]: phase for phase in readiness["phases"]}
    gate = phases[2]["tickets"][0]
    assert gate["human_action_required"] is True
    assert gate["ready"] is True
    assert 6 in gate["downstream_phase_numbers"]
    assert phases[6]["state"] == "pending"
    assert phases[3]["state"] == "active"

    headers = _agent_headers(api, ["cards:write", "loops:write"])
    denied = api.post(
        f"{_base(api, board, loop)}/cards/{gate['card_id']}/confirm",
        json={"version": 1},
        headers=headers,
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "human_action_required"

    confirmed = api.data(
        api.post(
            f"{_base(api, board, loop)}/cards/{gate['card_id']}/confirm",
            json={"version": 1, "note": "Account created"},
        )
    )
    assert confirmed["completed_at"] is not None
    readiness = api.data(api.get(f"{_base(api, board, loop)}/readiness"))
    phases = {phase["number"]: phase for phase in readiness["phases"]}
    assert phases[2]["state"] == "complete"
    assert phases[3]["state"] == "active"


def test_moving_to_a_done_column_does_not_complete(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    _, card = _ready_loop(api, board, loop)
    lists = api.data(api.get(f"/api/v1/boards/{board['id']}/loops/{loop['id']}/lists"))
    done = next(item for item in lists if item["name"] == "Done")
    moved = api.data(
        api.post(
            f"{_base(api, board, loop)}/cards/{card['id']}/move",
            json={"version": card["version"], "list_id": done["id"], "position": 0},
        )
    )
    assert moved["completed_at"] is None
    archived = api.data(api.post(f"{_base(api, board, loop)}/cards/{card['id']}/archive"))
    assert archived["archived_at"] is not None
    loop_row = api.data(api.get(_base(api, board, loop)))
    assert loop_row["stage"] == "ready"


def test_blocked_tickets_cannot_be_completed(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    api.data(api.put(f"{_base(api, board, loop)}/documents/info", json={"content": "Intent"}))
    _submit_analysis(api, board, loop)
    _approve_analysis(api, board, loop)
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    plan = {
        "kind": "roadmap",
        "plan": {
            "phases": [
                {
                    "id": str(uuid.uuid4()),
                    "number": 1,
                    "name": "One",
                    "tickets": [
                        {"id": first, "title": "First", "instructions": "1"},
                        {
                            "id": second,
                            "title": "Second",
                            "instructions": "2",
                            "prerequisite_ticket_ids": [first],
                        },
                    ],
                }
            ]
        },
    }
    _publish_plan(api, board, loop, plan)
    cards = {card["title"]: card for card in api.data(api.get(f"{_base(api, board, loop)}/cards"))}
    blocked = api.patch(
        f"{_base(api, board, loop)}/cards/{cards['Second']['id']}",
        json={"version": cards["Second"]["version"], "completed": True},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "ticket_blocked"
    done = api.data(
        api.patch(
            f"{_base(api, board, loop)}/cards/{cards['First']['id']}",
            json={"version": cards["First"]["version"], "completed": True},
        )
    )
    assert done["completed_at"] is not None


# --- QA, completion and history ------------------------------------------------------


def _qa_instructions() -> dict[str, Any]:
    return {
        "summary": "Verify the change",
        "scenarios": [
            {
                "id": "QA-01",
                "title": "Happy path",
                "kind": "happy_path",
                "steps_ai": ["POST the endpoint"],
                "steps_human": ["Open the page", "Confirm the message"],
                "expected_result": "The message appears",
            },
            {
                "id": "QA-02",
                "title": "Failure path",
                "kind": "failure_path",
                "steps_ai": ["POST invalid input"],
                "steps_human": ["Submit invalid input"],
                "expected_result": "The input is rejected",
            },
        ],
    }


def _complete_delivery(api: Api, board: dict[str, Any], loop: dict[str, Any]) -> None:
    cards = api.data(api.get(f"{_base(api, board, loop)}/cards"))
    for card in cards:
        if card["kind"] == "ticket":
            api.data(
                api.patch(
                    f"{_base(api, board, loop)}/cards/{card['id']}",
                    json={"version": card["version"], "completed": True},
                )
            )


def test_acceptance_creates_one_qa_task_with_two_views(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    _ready_loop(api, board, loop)
    _complete_delivery(api, board, loop)
    body = {"version": _version(api, board, loop), "accepted": True, "qa_status": "not_tested"}
    api.data(api.post(f"{_base(api, board, loop)}/completion", json=body))
    again = api.post(
        f"{_base(api, board, loop)}/completion",
        json={**body, "version": _version(api, board, loop)},
    )
    assert again.status_code == 200
    assert again.json()["data"]["cycle_number"] == 1
    loop_row = api.data(api.get(_base(api, board, loop)))
    assert loop_row["stage"] == "awaiting_qa"
    assert loop_row["qa"]["open"] is True
    qa_cards = [
        card
        for card in api.data(api.get(f"{_base(api, board, loop)}/cards"))
        if card["kind"] == "qa"
    ]
    assert len(qa_cards) == 1
    assert qa_cards[0]["human_action_required"] is True

    api.data(api.put(f"{_base(api, board, loop)}/qa/instructions", json=_qa_instructions()))
    qa_card = [
        card
        for card in api.data(api.get(f"{_base(api, board, loop)}/cards"))
        if card["kind"] == "qa"
    ][0]
    assert "human view" in qa_card["description"]
    assert "agent view" in qa_card["description"]
    assert "QA-01" in qa_card["description"]


def test_only_a_human_accepts_qa_and_completion_is_atomic(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    _ready_loop(api, board, loop)
    _complete_delivery(api, board, loop)
    api.data(
        api.post(
            f"{_base(api, board, loop)}/completion",
            json={
                "version": _version(api, board, loop),
                "accepted": True,
                "qa_status": "not_tested",
            },
        )
    )
    api.data(api.put(f"{_base(api, board, loop)}/qa/instructions", json=_qa_instructions()))
    cycle = api.data(api.get(f"{_base(api, board, loop)}/qa"))
    headers = _agent_headers(api, ["loops:write", "loops:generate", "cards:write"])
    results = {
        "results": [
            {"scenario_id": "QA-01", "status": "passed", "evidence": "log"},
        ]
    }
    api.data(api.post(f"{_base(api, board, loop)}/qa/results", json=results, headers=headers))

    agent_accept = api.post(
        f"{_base(api, board, loop)}/qa/decision",
        json={
            "version": _version(api, board, loop),
            "cycle_id": cycle["id"],
            "decision": "accepted",
        },
        headers=headers,
    )
    assert agent_accept.status_code == 403
    assert agent_accept.json()["error"]["code"] == "human_action_required"

    incomplete = api.post(
        f"{_base(api, board, loop)}/qa/decision",
        json={
            "version": _version(api, board, loop),
            "cycle_id": cycle["id"],
            "decision": "accepted",
        },
    )
    assert incomplete.status_code == 409
    assert incomplete.json()["error"]["code"] == "qa_incomplete"

    api.data(
        api.post(
            f"{_base(api, board, loop)}/qa/results",
            json={"results": [{"scenario_id": "QA-02", "status": "passed"}]},
            headers=headers,
        )
    )
    finalized = api.data(
        api.post(
            f"{_base(api, board, loop)}/qa/decision",
            json={
                "version": _version(api, board, loop),
                "cycle_id": cycle["id"],
                "decision": "accepted",
            },
        )
    )
    assert finalized["source_kind"] == "native"
    loop_row = api.data(api.get(_base(api, board, loop)))
    assert loop_row["stage"] == "completed"
    assert loop_row["history_id"] is not None

    repeat = api.data(
        api.post(
            f"{_base(api, board, loop)}/qa/decision",
            json={
                "version": loop_row["version"],
                "cycle_id": cycle["id"],
                "decision": "accepted",
            },
        )
    )
    assert repeat["id"] == finalized["id"]


def test_completed_loop_is_read_only_everywhere(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    _, card = _ready_loop(api, board, loop)
    attachment = api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/attachments",
            params={"card_id": card["id"], "filename": "before.txt"},
            content=b"before completion",
            headers={"Content-Type": "text/plain"},
        )
    )
    _complete_delivery(api, board, loop)
    api.data(
        api.post(
            f"{_base(api, board, loop)}/completion",
            json={
                "version": _version(api, board, loop),
                "accepted": True,
                "qa_status": "passed",
                "attestation": {
                    "scope": "Manual smoke test",
                    "results": "All checks passed",
                },
            },
        )
    )
    comment = api.post(
        f"{_base(api, board, loop)}/cards/{card['id']}/comments",
        json={"content": "After completion"},
    )
    assert comment.status_code == 409
    assert comment.json()["error"]["code"] == "loop_read_only"
    lists = api.data(api.get(f"/api/v1/boards/{board['id']}/loops/{loop['id']}/lists"))
    archived = api.post(
        f"/api/v1/boards/{board['id']}/loops/{loop['id']}/lists/{lists[0]['id']}/archive"
    )
    assert archived.status_code == 409
    assert archived.json()["error"]["code"] == "loop_read_only"
    removed = api.delete(f"/api/v1/boards/{board['id']}/attachments/{attachment['id']}")
    assert removed.status_code == 409
    assert removed.json()["error"]["code"] == "loop_read_only"
    thread = api.post(
        f"/api/v1/boards/{board['id']}/discussions",
        json={"card_id": card["id"], "goal": "Can we still discuss this?"},
    )
    assert thread.status_code == 409
    assert thread.json()["error"]["code"] == "loop_read_only"
    history = api.data(api.get(f"/api/v1/boards/{board['id']}/history"))
    assert len(history) == 1
    assert history[0]["qa_status"] == "accepted"


def test_read_only_guard_covers_every_card_scoped_mutation(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    """One retrofit endpoint that forgets the guard must not slip through a per-endpoint test."""
    _, card = _ready_loop(api, board, loop)
    base = _base(api, board, loop)
    cards = f"{base}/cards/{card['id']}"
    board_url = f"/api/v1/boards/{board['id']}"
    comment = api.data(api.post(f"{cards}/comments", json={"content": "Before completion"}))
    checklist = api.data(api.post(f"{cards}/checklists", json={"title": "Before"}))
    item = api.data(
        api.post(f"{board_url}/checklists/{checklist['id']}/items", json={"text": "Before"})
    )
    attachment = api.data(
        api.post(
            f"{board_url}/attachments",
            params={"card_id": card["id"], "filename": "before.txt"},
            content=b"before completion",
            headers={"Content-Type": "text/plain"},
        )
    )
    lists = api.data(api.get(f"{base}/lists"))

    _complete_delivery(api, board, loop)
    api.data(
        api.post(
            f"{base}/completion",
            json={
                "version": _version(api, board, loop),
                "accepted": True,
                "qa_status": "passed",
                "attestation": {"scope": "smoke", "results": "passed"},
            },
        )
    )
    version = api.data(api.get(cards))["version"]

    attempts = {
        "card update": api.patch(cards, json={"version": version, "title": "After"}),
        "card move": api.post(
            f"{cards}/move",
            json={"version": version, "list_id": lists[0]["id"], "position": 0},
        ),
        "card archive": api.post(f"{cards}/archive"),
        "card confirm": api.post(f"{cards}/confirm", json={"version": version, "note": "done"}),
        "comment create": api.post(f"{cards}/comments", json={"content": "After"}),
        "comment update": api.patch(
            f"{board_url}/comments/{comment['id']}", json={"content": "After"}
        ),
        "comment delete": api.delete(f"{board_url}/comments/{comment['id']}"),
        "checklist create": api.post(f"{cards}/checklists", json={"title": "After"}),
        "checklist update": api.patch(
            f"{board_url}/checklists/{checklist['id']}", json={"title": "After"}
        ),
        "checklist delete": api.delete(f"{board_url}/checklists/{checklist['id']}"),
        "item create": api.post(
            f"{board_url}/checklists/{checklist['id']}/items", json={"text": "After"}
        ),
        "item update": api.patch(
            f"{board_url}/checklist-items/{item['id']}", json={"completed": True}
        ),
        "item delete": api.delete(f"{board_url}/checklist-items/{item['id']}"),
        "attachment upload": api.post(
            f"{board_url}/attachments",
            params={"card_id": card["id"], "filename": "after.txt"},
            content=b"after completion",
            headers={"Content-Type": "text/plain"},
        ),
        "attachment delete": api.delete(f"{board_url}/attachments/{attachment['id']}"),
        "discussion create": api.post(
            f"{board_url}/discussions",
            json={"card_id": card["id"], "goal": "After completion"},
        ),
    }
    rejected = {
        name: (response.status_code, response.json().get("error", {}).get("code"))
        for name, response in attempts.items()
    }
    assert rejected == {name: (409, "loop_read_only") for name in attempts}


def test_history_search_covers_decisions_and_ticket_keys(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    _, card = _ready_loop(api, board, loop)
    _complete_delivery(api, board, loop)
    api.data(
        api.post(
            f"{_base(api, board, loop)}/completion",
            json={
                "version": _version(api, board, loop),
                "accepted": True,
                "qa_status": "passed",
                "attestation": {"scope": "smoke", "results": "passed"},
            },
        )
    )
    found = api.data(
        api.get(f"/api/v1/boards/{board['id']}/history", params={"q": card["ticket_key"]})
    )
    assert len(found) == 1
    meta = api.get(
        f"/api/v1/boards/{board['id']}/history", params={"q": card["ticket_key"]}
    ).json()["meta"]
    assert meta["engine"] in {"fts5", "like"}
    detail = api.data(api.get(f"/api/v1/boards/{board['id']}/history/{found[0]['id']}"))
    assert detail["envelope"]["qa"]["results"] or detail["envelope"]["human_decisions"]
    assert detail["content_hash"]


def test_legacy_import_preserves_bytes_and_creates_no_tickets(
    api: Api, board: dict[str, Any]
) -> None:
    payload = {
        "loop_name": "Old planning notes",
        "source_project": "legacy-repo",
        "source_format": "ralph-prd",
        "reported_qa_status": "passed",
        "raw_text": "Phase 1: do the thing",
        "documents": {"info": "The original text, unchanged."},
        "idempotency_key": "legacy-1",
    }
    created = api.data(api.post(f"/api/v1/boards/{board['id']}/history/import", json=payload))
    assert created["source_kind"] == "imported_legacy"
    assert created["conformance"] == "legacy_unvalidated"
    assert created["qa_status"] == "unknown"
    assert created["label"]
    assert created["warnings"]
    envelope = created["envelope"]
    assert envelope["raw_text"] == payload["raw_text"]
    assert envelope["documents"][0]["content"] == payload["documents"]["info"]
    assert api.data(api.get(f"/api/v1/boards/{board['id']}/loops")) == []


def test_history_search_index_recovers_from_drift(api: Api, board: dict[str, Any]) -> None:
    """A restore or copy can leave the FTS index behind the table; startup rebuilds it."""
    from app.storage.schema.fts import ensure_fts

    api.data(
        api.post(
            f"/api/v1/boards/{board['id']}/history/import",
            json={
                "loop_name": "Indexed legacy",
                "raw_text": "Zebra crossing notes",
                "documents": {"info": "Only the searchable summary matters here."},
            },
        )
    )
    services = api.client.app.state.services
    engine = services.boards.open(board["id"])
    if not services.boards.fts_available(board["id"]):
        return
    with engine.begin() as conn:
        # The index side loses its rows while the content table keeps them.
        conn.exec_driver_sql("DELETE FROM loop_history_fts_docsize")
        assert (
            conn.exec_driver_sql("SELECT COUNT(*) FROM loop_history_fts_docsize").scalar_one() == 0
        )

    assert ensure_fts(engine) is True
    found = api.data(
        api.get(f"/api/v1/boards/{board['id']}/history", params={"q": "Zebra"})
    )
    assert [item["loop_name"] for item in found] == ["Indexed legacy"]


def test_qa_not_applicable_needs_a_human_decision(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    _ready_loop(api, board, loop)
    _complete_delivery(api, board, loop)
    api.data(
        api.post(
            f"{_base(api, board, loop)}/completion",
            json={
                "version": _version(api, board, loop),
                "accepted": True,
                "qa_status": "not_tested",
            },
        )
    )
    api.data(api.put(f"{_base(api, board, loop)}/qa/instructions", json=_qa_instructions()))
    cycle = api.data(api.get(f"{_base(api, board, loop)}/qa"))
    headers = _agent_headers(api, ["loops:write"])
    api.data(
        api.post(
            f"{_base(api, board, loop)}/qa/results",
            json={
                "results": [
                    {"scenario_id": "QA-01", "status": "passed"},
                    {"scenario_id": "QA-02", "status": "not_applicable", "reason": "Not shipped"},
                ]
            },
            headers=headers,
        )
    )
    blocked = api.post(
        f"{_base(api, board, loop)}/qa/decision",
        json={
            "version": _version(api, board, loop),
            "cycle_id": cycle["id"],
            "decision": "accepted",
        },
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["details"]["blockers"][0]["reason"] == (
        "not_applicable_requires_human_approval"
    )
    api.data(
        api.post(
            f"{_base(api, board, loop)}/qa/decision",
            json={
                "version": _version(api, board, loop),
                "cycle_id": cycle["id"],
                "decision": "accepted",
                "not_applicable_approvals": ["QA-02"],
            },
        )
    )


def test_reopening_a_prerequisite_invalidates_qa(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    _, card = _ready_loop(api, board, loop)
    _complete_delivery(api, board, loop)
    api.data(
        api.post(
            f"{_base(api, board, loop)}/completion",
            json={
                "version": _version(api, board, loop),
                "accepted": True,
                "qa_status": "not_tested",
            },
        )
    )
    current = api.data(api.get(f"{_base(api, board, loop)}/cards/{card['id']}"))
    reopened = api.data(
        api.patch(
            f"{_base(api, board, loop)}/cards/{card['id']}",
            json={"version": current["version"], "completed": False},
        )
    )
    assert reopened["completed_at"] is None
    loop_row = api.data(api.get(_base(api, board, loop)))
    assert loop_row["qa"] is None or loop_row["qa"]["open"] is False
    assert loop_row["stage"] in {"in_progress", "ready"}


# --- resetting a scope ------------------------------------------------------------


def test_resetting_an_analysis_clears_its_documents(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    """A reset is not a rejection: the approved text is retired, not sent back for changes."""
    api.data(
        api.put(
            f"{_base(api, board, loop)}/documents/info",
            json={"content": "Users must confirm their email address."},
        )
    )
    _submit_analysis(api, board, loop)
    _approve_analysis(api, board, loop)
    approved = _documents(api, board, loop)
    assert approved["documents"]["analysis"]["state"] == "approved"

    withdrawn = api.data(
        api.post(
            f"{_base(api, board, loop)}/reviews/analysis/reset",
            json={"version": _version(api, board, loop)},
        )
    )
    assert withdrawn["scope"] == "analysis"
    assert withdrawn["cleared"] == ["analysis_ai", "analysis"]

    documents = _documents(api, board, loop)
    for kind in ("analysis_ai", "analysis"):
        assert documents["documents"][kind]["current_content"] == ""
        assert documents["documents"][kind]["current_payload"] is None
        assert documents["documents"][kind]["state"] == "draft"
        assert documents["documents"][kind]["approved_revision_id"] is None
    assert documents["documents"]["info"]["current_content"].strip() != ""
    assert documents["approvals"] == {}
    loop_row = api.data(api.get(_base(api, board, loop)))
    assert loop_row["analysis_approval_id"] is None

    # Nothing downstream may proceed from an approval that no longer exists.
    refused = api.post(
        f"{_base(api, board, loop)}/candidates",
        json=_plan(phase_id=str(uuid.uuid4()), ticket_id=str(uuid.uuid4())),
    )
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "approval_required"


def test_resetting_a_roadmap_keeps_the_approved_analysis(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    _ready_loop(api, board, loop)
    withdrawn = api.data(
        api.post(
            f"{_base(api, board, loop)}/reviews/roadmap/reset",
            json={"version": _version(api, board, loop)},
        )
    )
    assert withdrawn["cleared"] == ["roadmap_ai", "roadmap"]
    documents = _documents(api, board, loop)
    assert documents["documents"]["roadmap"]["current_content"] == ""
    assert documents["documents"]["analysis"]["state"] == "approved"
    assert set(documents["approvals"]) == {"analysis"}
    loop_row = api.data(api.get(_base(api, board, loop)))
    assert loop_row["roadmap_approval_id"] is None


def test_reset_clears_a_draft_that_was_never_approved(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    """The button has to work before an approval exists, or there is no way back from a draft."""
    api.data(
        api.put(
            f"{_base(api, board, loop)}/documents/info",
            json={"content": "Users must confirm their email address."},
        )
    )
    _submit_analysis(api, board, loop)
    assert _documents(api, board, loop)["documents"]["analysis"]["state"] == "ready_for_review"

    reset = api.data(
        api.post(
            f"{_base(api, board, loop)}/reviews/analysis/reset",
            json={"version": _version(api, board, loop)},
        )
    )
    assert reset["approval_id"] is None
    assert reset["cleared"] == ["analysis_ai", "analysis"]
    documents = _documents(api, board, loop)
    for kind in ("analysis_ai", "analysis"):
        assert documents["documents"][kind]["current_content"] == ""
        assert documents["documents"][kind]["state"] == "draft"
    # A second reset has nothing left to clear.
    again = api.post(
        f"{_base(api, board, loop)}/reviews/analysis/reset",
        json={"version": _version(api, board, loop)},
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "nothing_to_reset"


def test_reset_refuses_a_stale_version(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    api.data(
        api.put(
            f"{_base(api, board, loop)}/documents/info",
            json={"content": "Users must confirm their email address."},
        )
    )
    _submit_analysis(api, board, loop)
    _approve_analysis(api, board, loop)
    response = api.post(
        f"{_base(api, board, loop)}/reviews/analysis/reset",
        json={"version": _version(api, board, loop) - 1},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "version_conflict"


def test_reset_is_human_only(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    api.data(
        api.put(
            f"{_base(api, board, loop)}/documents/info",
            json={"content": "Users must confirm their email address."},
        )
    )
    _submit_analysis(api, board, loop)
    _approve_analysis(api, board, loop)
    headers = _agent_headers(api, ["boards:read", "cards:read"])
    response = api.post(
        f"{_base(api, board, loop)}/reviews/analysis/reset",
        json={"version": _version(api, board, loop)},
        headers=headers,
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "human_action_required"

