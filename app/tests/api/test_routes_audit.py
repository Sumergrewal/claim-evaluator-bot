"""Tests for the dedicated audit endpoints.

The claim drill-down already embeds `audit_events[]`; these routes
exist so the UI can refresh only the timeline. Tests assert the
dedicated endpoints return the same data as the embedded slice (for
claims) and stay scoped correctly (for line items).
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_get_claim_audit_matches_embedded_timeline_on_detail(
    api_client: TestClient,
) -> None:
    detail = api_client.get("/api/claims/C-ALICE-001").json()
    audit = api_client.get("/api/claims/C-ALICE-001/audit").json()

    assert audit == detail["audit_events"]
    assert len(audit) == 1
    assert audit[0]["event_type"] == "line_item.decided"
    assert audit[0]["entity_type"] == "line_item"


def test_get_claim_audit_unknown_claim_returns_404(
    api_client: TestClient,
) -> None:
    response = api_client.get("/api/claims/C-NOPE/audit")
    assert response.status_code == 404
    assert "C-NOPE" in response.json()["detail"]


def test_get_claim_audit_multi_line_claim_includes_every_line_item_event(
    api_client: TestClient,
) -> None:
    """C-CAROL-002 has two line items; the merged timeline carries one
    `line_item.decided` per line, in chronological order.
    """
    audit = api_client.get("/api/claims/C-CAROL-002/audit").json()
    assert len(audit) == 2
    assert all(e["event_type"] == "line_item.decided" for e in audit)
    assert {e["entity_id"] for e in audit} == {
        "L-CAROL-002-1",
        "L-CAROL-002-2",
    }
    occurred = [e["occurred_at"] for e in audit]
    assert occurred == sorted(occurred)


def test_get_claim_audit_after_post_includes_submitted_then_decided(
    api_client: TestClient,
) -> None:
    create = api_client.post(
        "/api/claims",
        json={
            "member_id": "M-001",
            "provider_name": "Audit Clinic",
            "service_date": "2026-07-01",
            "line_items": [
                {
                    "service_type": "general_consultation",
                    "service_description": "Visit",
                    "charged_amount": "100.00",
                }
            ],
        },
    )
    claim_id = create.json()["id"]
    audit = api_client.get(f"/api/claims/{claim_id}/audit").json()

    assert [e["event_type"] for e in audit] == [
        "claim.submitted",
        "line_item.decided",
    ]
    assert audit[0]["actor"] == "member"
    assert audit[0]["entity_type"] == "claim"
    assert audit[1]["actor"] == "system"


def test_get_line_item_audit_returns_only_that_line_items_events(
    api_client: TestClient,
) -> None:
    audit = api_client.get("/api/line-items/L-CAROL-002-1/audit").json()
    assert len(audit) == 1
    assert audit[0]["entity_id"] == "L-CAROL-002-1"
    assert audit[0]["event_type"] == "line_item.decided"


def test_get_line_item_audit_does_not_include_sibling_line_items(
    api_client: TestClient,
) -> None:
    first = api_client.get("/api/line-items/L-CAROL-002-1/audit").json()
    second = api_client.get("/api/line-items/L-CAROL-002-2/audit").json()
    assert first[0]["entity_id"] == "L-CAROL-002-1"
    assert second[0]["entity_id"] == "L-CAROL-002-2"
    assert first != second


def test_get_line_item_audit_unknown_id_returns_404(
    api_client: TestClient,
) -> None:
    response = api_client.get("/api/line-items/L-NOPE/audit")
    assert response.status_code == 404
    assert "L-NOPE" in response.json()["detail"]


def test_get_line_item_audit_payload_carries_decision_fields(
    api_client: TestClient,
) -> None:
    audit = api_client.get("/api/line-items/L-ALICE-001-1/audit").json()
    payload = audit[0]["payload"]
    assert "outcome" in payload
    assert "decision_id" in payload
    assert "previous_status" in payload
    assert "new_status" in payload


def test_get_line_item_audit_matches_slice_of_claim_audit_timeline(
    api_client: TestClient,
) -> None:
    """The line-item endpoint must return exactly the events belonging
    to that line item from the merged claim timeline — no more, no less.
    """
    claim_audit = api_client.get("/api/claims/C-CAROL-002/audit").json()
    line_audit = api_client.get("/api/line-items/L-CAROL-002-1/audit").json()

    expected = [e for e in claim_audit if e["entity_id"] == "L-CAROL-002-1"]
    assert line_audit == expected


def test_get_claim_audit_event_shape_matches_schema(
    api_client: TestClient,
) -> None:
    audit = api_client.get("/api/claims/C-ALICE-001/audit").json()
    assert len(audit) >= 1
    for event in audit:
        assert set(event.keys()) == {
            "id",
            "event_type",
            "entity_type",
            "entity_id",
            "actor",
            "occurred_at",
            "payload",
        }
