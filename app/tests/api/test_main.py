"""Smoke tests for the FastAPI app wiring (phase 07).

These are thin checks that the assembled app exposes the expected
surface and that scaffolding removed during phase 07 stays gone.
Route behaviour lives in the per-resource test modules.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_hello_endpoint_removed_returns_404(api_client: TestClient) -> None:
    response = api_client.get("/api/hello")
    assert response.status_code == 404


def test_openapi_lists_phase_07_routes(api_client: TestClient) -> None:
    schema = api_client.get("/openapi.json").json()
    paths = schema["paths"]
    assert "/api/members" in paths
    assert "/api/claims" in paths
    assert "/api/claims/{claim_id}" in paths
    assert "/api/claims/{claim_id}/audit" in paths
    assert "/api/line-items/{line_item_id}/audit" in paths
    assert "/api/hello" not in paths
