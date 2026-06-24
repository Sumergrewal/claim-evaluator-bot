"""Tests for `GET /api/members`.

The route is trivial — list all members — but it's the dropdown
source for the frontend's member filter and submit form, so we pin
the shape and the seed-derived count.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_list_members_returns_every_seeded_member(api_client: TestClient) -> None:
    response = api_client.get("/api/members")
    assert response.status_code == 200

    payload = response.json()
    assert {m["id"] for m in payload} == {"M-001", "M-002", "M-003"}


def test_list_members_returns_id_and_name_only(api_client: TestClient) -> None:
    response = api_client.get("/api/members")
    payload = response.json()
    for member in payload:
        assert set(member.keys()) == {"id", "name"}


def test_list_members_is_ordered_by_id(api_client: TestClient) -> None:
    response = api_client.get("/api/members")
    ids = [m["id"] for m in response.json()]
    assert ids == sorted(ids)
