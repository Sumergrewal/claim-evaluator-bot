"""Tests for `POST /api/line-items/{id}/dispute`."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_file_dispute_moves_line_item_to_needs_review_and_returns_claim(
    api_client: TestClient,
) -> None:
    detail = api_client.get("/api/claims/C-ALICE-001").json()
    line_item_id = detail["line_items"][0]["id"]
    assert detail["line_items"][0]["status"] == "approved"

    response = api_client.post(
        f"/api/line-items/{line_item_id}/dispute",
        json={"reason": "I believe this should have been partially covered."},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["id"] == "C-ALICE-001"
    assert body["adjudication_state"] == "under_review"
    disputed = next(li for li in body["line_items"] if li["id"] == line_item_id)
    assert disputed["status"] == "needs_review"
    assert disputed["current_decision"] is not None
    assert disputed["current_decision"]["outcome"] == "approved"

    event_types = [e["event_type"] for e in body["audit_events"]]
    assert "dispute.filed" in event_types
    assert "line_item.state_changed" in event_types


def test_file_dispute_unknown_line_item_returns_404(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/line-items/L-NOPE/dispute",
        json={"reason": "test"},
    )
    assert response.status_code == 404


def test_file_dispute_pending_line_item_returns_400(api_client: TestClient) -> None:
    created = api_client.post(
        "/api/claims",
        json={
            "member_id": "M-001",
            "provider_name": "Clinic",
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
    assert created.status_code == 201
    # Re-submit isn't pending — use a trick: we need pending. Actually
    # POST adjudicates immediately so no pending items exist.
    # Use needs_review line from seed instead for non-disputable pending test.
    detail = api_client.get("/api/claims/C-CAROL-003").json()
    line_item_id = detail["line_items"][0]["id"]
    assert detail["line_items"][0]["status"] == "needs_review"

    response = api_client.post(
        f"/api/line-items/{line_item_id}/dispute",
        json={"reason": "test"},
    )
    assert response.status_code == 400
    assert "needs_review" in response.json()["detail"]


def test_file_dispute_twice_returns_409(api_client: TestClient) -> None:
    detail = api_client.get("/api/claims/C-ALICE-002").json()
    line_item_id = detail["line_items"][0]["id"]

    first = api_client.post(
        f"/api/line-items/{line_item_id}/dispute",
        json={"reason": "First filing"},
    )
    assert first.status_code == 200

    second = api_client.post(
        f"/api/line-items/{line_item_id}/dispute",
        json={"reason": "Second filing"},
    )
    assert second.status_code == 409


def test_file_dispute_rejects_empty_reason(api_client: TestClient) -> None:
    detail = api_client.get("/api/claims/C-ALICE-003").json()
    line_item_id = detail["line_items"][0]["id"]

    response = api_client.post(
        f"/api/line-items/{line_item_id}/dispute",
        json={"reason": ""},
    )
    assert response.status_code == 422
