"""Tests for `GET /api/claims` and `GET /api/claims/{claim_id}`.

The fixture (`api_client`) builds the same DB the production app
would on first launch: seed YAML loaded, every pending line item
adjudicated. Tests are behavioural — they assert on derived
adjudication state, totals, line-item shape, and the structured
explanation produced by the engine, not on raw HTTP minutiae.

Claim-state coverage matrix (drawn from `data/claims.yaml` and the
policies in `data/policies.yaml`):

- approved              C-ALICE-001 / 002 / 003 / 004 / 005,
                        C-BOB-002, C-CAROL-004
- paid                  C-BOB-001, C-CAROL-001
- partially_approved    C-CAROL-002
- under_review          C-CAROL-003, C-BOB-003
- denied                C-ALICE-006

Every state has at least one assertion below.
"""

from __future__ import annotations

from collections import Counter

from fastapi.testclient import TestClient

# --- List endpoint --------------------------------------------------------


def test_list_claims_returns_every_seeded_claim(api_client: TestClient) -> None:
    response = api_client.get("/api/claims")
    assert response.status_code == 200
    assert len(response.json()) == 13


def test_list_claims_returns_summary_shape(api_client: TestClient) -> None:
    response = api_client.get("/api/claims")
    row = response.json()[0]
    assert set(row.keys()) == {
        "id",
        "member_id",
        "member_name",
        "provider_name",
        "service_date",
        "submitted_at",
        "paid_at",
        "adjudication_state",
        "totals",
    }
    assert set(row["totals"].keys()) == {
        "charged",
        "payable",
        "member_responsibility",
    }


def test_list_claims_denormalises_member_name(api_client: TestClient) -> None:
    response = api_client.get("/api/claims")
    by_id = {c["id"]: c for c in response.json()}
    assert by_id["C-ALICE-001"]["member_name"] == "Alice Anderson"
    assert by_id["C-BOB-001"]["member_name"] == "Bob Brown"
    assert by_id["C-CAROL-001"]["member_name"] == "Carol Chen"


def test_list_claims_orders_by_submitted_at(api_client: TestClient) -> None:
    response = api_client.get("/api/claims")
    submitted = [c["submitted_at"] for c in response.json()]
    assert submitted == sorted(submitted)


def test_list_claims_filter_by_member_returns_only_that_members_claims(
    api_client: TestClient,
) -> None:
    response = api_client.get("/api/claims", params={"member_id": "M-001"})
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 6
    assert all(c["member_id"] == "M-001" for c in payload)


def test_list_claims_filter_each_member_matches_expected_counts(
    api_client: TestClient,
) -> None:
    expected = {"M-001": 6, "M-002": 3, "M-003": 4}
    for member_id, count in expected.items():
        response = api_client.get(
            "/api/claims", params={"member_id": member_id}
        )
        assert response.status_code == 200, member_id
        assert len(response.json()) == count, member_id


def test_list_claims_filter_unknown_member_returns_404(
    api_client: TestClient,
) -> None:
    response = api_client.get(
        "/api/claims", params={"member_id": "M-DOES-NOT-EXIST"}
    )
    assert response.status_code == 404
    assert "M-DOES-NOT-EXIST" in response.json()["detail"]


def test_list_claims_carries_every_derived_state(
    api_client: TestClient,
) -> None:
    """The list view is what the UI reads to colour each row; every
    state the engine and lifecycle produce must reach this surface.
    """
    response = api_client.get("/api/claims")
    states = Counter(c["adjudication_state"] for c in response.json())
    assert states["approved"] == 7
    assert states["paid"] == 2
    assert states["partially_approved"] == 1
    assert states["under_review"] == 2
    assert states["denied"] == 1


def test_list_claims_paid_claim_has_state_paid_with_charged_total(
    api_client: TestClient,
) -> None:
    response = api_client.get("/api/claims")
    bob1 = next(c for c in response.json() if c["id"] == "C-BOB-001")
    assert bob1["adjudication_state"] == "paid"
    assert bob1["paid_at"] is not None
    assert bob1["totals"]["charged"] == "300.00"


def test_list_claims_partial_claim_totals_match_per_line_split(
    api_client: TestClient,
) -> None:
    """C-CAROL-002: $150 filling (covered with $40 copay -> plan $110,
    member $40) + $200 whitening (excluded -> plan $0, member $200).
    """
    response = api_client.get("/api/claims")
    carol2 = next(c for c in response.json() if c["id"] == "C-CAROL-002")
    assert carol2["adjudication_state"] == "partially_approved"
    assert carol2["totals"]["charged"] == "350.00"
    assert carol2["totals"]["payable"] == "110.00"
    assert carol2["totals"]["member_responsibility"] == "240.00"


# --- Detail endpoint ------------------------------------------------------


def test_get_claim_unknown_id_returns_404(api_client: TestClient) -> None:
    response = api_client.get("/api/claims/C-NOPE")
    assert response.status_code == 404
    assert "C-NOPE" in response.json()["detail"]


def test_get_claim_detail_carries_line_items_and_audit_timeline(
    api_client: TestClient,
) -> None:
    """One line item -> one `line_item.decided` audit event, with the
    current decision and structured explanation embedded.
    """
    response = api_client.get("/api/claims/C-ALICE-001")
    assert response.status_code == 200
    detail = response.json()

    assert detail["member_name"] == "Alice Anderson"
    assert len(detail["line_items"]) == 1

    line_item = detail["line_items"][0]
    assert line_item["service_type"] == "general_consultation"
    assert line_item["status"] == "approved"
    assert line_item["current_decision"] is not None
    assert line_item["current_decision"]["outcome"] == "approved"
    assert line_item["current_decision"]["explanation"]["steps"][0]["phase"] == (
        "eligibility"
    )

    assert len(detail["audit_events"]) == 1
    assert detail["audit_events"][0]["event_type"] == "line_item.decided"
    assert detail["audit_events"][0]["entity_type"] == "line_item"


def test_get_claim_detail_for_denied_explains_with_terminating_step(
    api_client: TestClient,
) -> None:
    response = api_client.get("/api/claims/C-ALICE-006")
    detail = response.json()
    assert detail["adjudication_state"] == "denied"

    line_item = detail["line_items"][0]
    assert line_item["status"] == "denied"
    explanation = line_item["current_decision"]["explanation"]
    assert explanation["outcome"] == "denied"

    terminating = [s for s in explanation["steps"] if s.get("terminating")]
    assert len(terminating) == 1
    assert terminating[0]["phase"] == "coverage"
    assert terminating[0]["result"] == "fail"


def test_get_claim_detail_for_needs_review_shows_gate_step(
    api_client: TestClient,
) -> None:
    response = api_client.get("/api/claims/C-CAROL-003")
    detail = response.json()
    assert detail["adjudication_state"] == "under_review"

    line_item = detail["line_items"][0]
    assert line_item["status"] == "needs_review"
    explanation = line_item["current_decision"]["explanation"]
    assert explanation["outcome"] == "needs_review"

    terminating = [s for s in explanation["steps"] if s.get("terminating")]
    assert len(terminating) == 1
    assert terminating[0]["phase"] == "gates"
    assert terminating[0]["result"] == "needs_review"


def test_get_claim_detail_partial_claim_has_mixed_line_item_outcomes(
    api_client: TestClient,
) -> None:
    response = api_client.get("/api/claims/C-CAROL-002")
    detail = response.json()
    assert detail["adjudication_state"] == "partially_approved"
    assert len(detail["line_items"]) == 2

    outcomes = sorted(
        li["current_decision"]["outcome"] for li in detail["line_items"]
    )
    assert outcomes == ["approved", "denied"]
    assert len(detail["audit_events"]) == 2


def test_get_claim_detail_paid_claim_keeps_paid_state_and_carries_decision(
    api_client: TestClient,
) -> None:
    """C-BOB-001 has `paid_at` set in the seed; the startup adjudication
    batch fills its line item's decision before the first HTTP request.
    The drill-down must show both: paid lifecycle state AND the
    structured decision.
    """
    response = api_client.get("/api/claims/C-BOB-001")
    detail = response.json()
    assert detail["adjudication_state"] == "paid"
    assert detail["paid_at"] is not None

    line_item = detail["line_items"][0]
    assert line_item["status"] == "approved"
    assert line_item["current_decision"] is not None
    explanation = line_item["current_decision"]["explanation"]
    assert explanation["outcome"] == "approved"


def test_get_claim_detail_money_amounts_serialise_as_strings(
    api_client: TestClient,
) -> None:
    response = api_client.get("/api/claims/C-ALICE-001")
    line_item = response.json()["line_items"][0]
    assert isinstance(line_item["charged_amount"], str)
    assert isinstance(line_item["payable_amount"], str)
    assert isinstance(
        line_item["current_decision"]["payable_amount"], str
    )
    assert isinstance(
        line_item["current_decision"]["deductible_applied"], str
    )


def test_get_claim_detail_response_includes_detail_only_fields(
    api_client: TestClient,
) -> None:
    detail = api_client.get("/api/claims/C-ALICE-001").json()
    assert "line_items" in detail
    assert "audit_events" in detail
    assert isinstance(detail["line_items"], list)
    assert isinstance(detail["audit_events"], list)


def test_list_claims_marks_under_review_claim(api_client: TestClient) -> None:
    response = api_client.get("/api/claims")
    carol3 = next(c for c in response.json() if c["id"] == "C-CAROL-003")
    assert carol3["adjudication_state"] == "under_review"


def test_list_claims_marks_fully_denied_claim(api_client: TestClient) -> None:
    response = api_client.get("/api/claims")
    alice6 = next(c for c in response.json() if c["id"] == "C-ALICE-006")
    assert alice6["adjudication_state"] == "denied"


def test_get_claim_detail_approved_claim_explanation_includes_cost_sharing_phases(
    api_client: TestClient,
) -> None:
    """C-ALICE-002: deductible already partially met on earlier claims,
    so this follow-up consult should show both `deductible` and
    `cost_sharing` steps on the wire — not just terminal coverage paths.
    """
    detail = api_client.get("/api/claims/C-ALICE-002").json()
    steps = detail["line_items"][0]["current_decision"]["explanation"]["steps"]
    phases = {s["phase"] for s in steps}
    assert "deductible" in phases
    assert "cost_sharing" in phases
    assert detail["adjudication_state"] == "approved"


def test_post_claim_response_matches_subsequent_get_detail(
    api_client: TestClient,
) -> None:
    post = api_client.post("/api/claims", json=_submit_body()).json()
    get = api_client.get(f"/api/claims/{post['id']}").json()
    assert get == post


def test_post_claim_partially_approved_when_one_line_covered_one_excluded(
    api_client: TestClient,
) -> None:
    """Carol's DENTAL plan: `filling` covered, `cosmetic_whitening` excluded.
    One POST with both should derive `partially_approved`.
    """
    response = api_client.post(
        "/api/claims",
        json=_submit_body(
            member_id="M-003",
            line_items=[
                {
                    "service_type": "filling",
                    "service_description": "Composite filling",
                    "charged_amount": "150.00",
                },
                {
                    "service_type": "cosmetic_whitening",
                    "service_description": "Whitening kit",
                    "charged_amount": "200.00",
                },
            ],
        ),
    )
    detail = response.json()
    assert detail["adjudication_state"] == "partially_approved"
    outcomes = {li["status"] for li in detail["line_items"]}
    assert outcomes == {"approved", "denied"}


def test_post_claim_preauthed_mri_passes_gates_and_is_approved(
    api_client: TestClient,
) -> None:
    response = api_client.post(
        "/api/claims",
        json=_submit_body(
            line_items=[
                {
                    "service_type": "mri",
                    "service_description": "MRI left knee",
                    "charged_amount": "1500.00",
                    "preauth_ref": "PRE-TEST-001",
                }
            ]
        ),
    )
    detail = response.json()
    assert detail["adjudication_state"] == "approved"

    explanation = detail["line_items"][0]["current_decision"]["explanation"]
    gate_steps = [s for s in explanation["steps"] if s["phase"] == "gates"]
    assert len(gate_steps) == 1
    assert gate_steps[0]["result"] == "pass"


def test_get_claim_detail_ledger_invariant_holds_per_line_item(
    api_client: TestClient,
) -> None:
    """Every adjudicated line item satisfies
    `payable + member_responsibility == charged` (the engine's
    `EngineResult` post-init invariant). Same check at the wire layer
    catches any rounding regression in JSON serialisation.
    """
    response = api_client.get("/api/claims")
    from decimal import Decimal

    for summary in response.json():
        detail = api_client.get(f"/api/claims/{summary['id']}").json()
        for li in detail["line_items"]:
            payable = Decimal(li["payable_amount"])
            member = Decimal(li["member_responsibility"])
            charged = Decimal(li["charged_amount"])
            assert payable + member == charged, summary["id"]


# --- POST submit endpoint -------------------------------------------------


_DEFAULT_LINE_ITEMS = [
    {
        "service_type": "general_consultation",
        "service_description": "Office visit",
        "charged_amount": "300.00",
    }
]


def _submit_body(
    *,
    member_id: str = "M-001",
    provider_name: str = "Test Clinic",
    service_date: str = "2026-06-01",
    line_items: list[dict] | None = None,
) -> dict:
    return {
        "member_id": member_id,
        "provider_name": provider_name,
        "service_date": service_date,
        "line_items": (
            _DEFAULT_LINE_ITEMS if line_items is None else line_items
        ),
    }


def test_post_claim_returns_201_with_adjudicated_detail(
    api_client: TestClient,
) -> None:
    response = api_client.post("/api/claims", json=_submit_body())
    assert response.status_code == 201

    detail = response.json()
    assert detail["member_name"] == "Alice Anderson"
    assert detail["provider_name"] == "Test Clinic"
    assert detail["adjudication_state"] in {
        "approved",
        "denied",
        "under_review",
        "partially_approved",
    }
    assert len(detail["line_items"]) == 1
    assert detail["line_items"][0]["current_decision"] is not None
    assert detail["line_items"][0]["current_decision"]["explanation"][
        "steps"
    ][0]["phase"] == "eligibility"


def test_post_claim_generates_server_side_ids(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/claims",
        json=_submit_body(
            line_items=[
                {
                    "service_type": "general_consultation",
                    "service_description": "A",
                    "charged_amount": "100.00",
                },
                {
                    "service_type": "general_consultation",
                    "service_description": "B",
                    "charged_amount": "100.00",
                },
            ]
        ),
    )
    detail = response.json()
    assert detail["id"].startswith("C-")
    li_ids = [li["id"] for li in detail["line_items"]]
    assert all(li_id.startswith("L-") for li_id in li_ids)
    assert li_ids == sorted(li_ids), "line item ids must sort in submission order"
    assert len(set(li_ids)) == len(li_ids)


def test_post_claim_preserves_line_item_order_in_response(
    api_client: TestClient,
) -> None:
    response = api_client.post(
        "/api/claims",
        json=_submit_body(
            line_items=[
                {
                    "service_type": "general_consultation",
                    "service_description": "first",
                    "charged_amount": "50.00",
                },
                {
                    "service_type": "general_consultation",
                    "service_description": "second",
                    "charged_amount": "60.00",
                },
                {
                    "service_type": "general_consultation",
                    "service_description": "third",
                    "charged_amount": "70.00",
                },
            ]
        ),
    )
    descriptions = [
        li["service_description"] for li in response.json()["line_items"]
    ]
    assert descriptions == ["first", "second", "third"]


def test_post_claim_persists_so_subsequent_get_finds_it(
    api_client: TestClient,
) -> None:
    create = api_client.post("/api/claims", json=_submit_body()).json()
    listing = api_client.get("/api/claims").json()
    assert any(c["id"] == create["id"] for c in listing)

    detail = api_client.get(f"/api/claims/{create['id']}").json()
    assert detail["id"] == create["id"]
    assert detail["line_items"][0]["id"] == create["line_items"][0]["id"]


def test_post_claim_unknown_member_returns_404(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/claims", json=_submit_body(member_id="M-NOPE")
    )
    assert response.status_code == 404
    assert "M-NOPE" in response.json()["detail"]


def test_post_claim_writes_member_submitted_then_system_decided_events(
    api_client: TestClient,
) -> None:
    """The embedded audit timeline must show the originating member
    action first, then one system-issued decision per line item.
    """
    response = api_client.post(
        "/api/claims",
        json=_submit_body(
            line_items=[
                {
                    "service_type": "general_consultation",
                    "service_description": "X",
                    "charged_amount": "100.00",
                },
                {
                    "service_type": "general_consultation",
                    "service_description": "Y",
                    "charged_amount": "100.00",
                },
            ]
        ),
    )
    events = response.json()["audit_events"]
    assert [e["event_type"] for e in events] == [
        "claim.submitted",
        "line_item.decided",
        "line_item.decided",
    ]
    assert events[0]["actor"] == "member"
    assert events[0]["entity_type"] == "claim"
    assert events[1]["actor"] == "system"
    assert events[1]["entity_type"] == "line_item"


def test_post_claim_excluded_service_returns_denied_with_terminating_step(
    api_client: TestClient,
) -> None:
    """Alice's BASIC plan excludes `bariatric_surgery`. The engine
    short-circuits to `denied` in the coverage phase; the response
    must already carry that decision.
    """
    response = api_client.post(
        "/api/claims",
        json=_submit_body(
            line_items=[
                {
                    "service_type": "bariatric_surgery",
                    "service_description": "procedure",
                    "charged_amount": "12000.00",
                }
            ]
        ),
    )
    detail = response.json()
    assert detail["adjudication_state"] == "denied"

    line_item = detail["line_items"][0]
    assert line_item["status"] == "denied"
    explanation = line_item["current_decision"]["explanation"]
    terminating = [s for s in explanation["steps"] if s.get("terminating")]
    assert len(terminating) == 1
    assert terminating[0]["phase"] == "coverage"
    assert terminating[0]["result"] == "fail"


def test_post_claim_missing_preauth_returns_under_review(
    api_client: TestClient,
) -> None:
    """Alice's BASIC plan requires preauth for `mri`. Submitting one
    without a `preauth_ref` should land the claim in `under_review`
    via the engine's gates phase.
    """
    response = api_client.post(
        "/api/claims",
        json=_submit_body(
            line_items=[
                {
                    "service_type": "mri",
                    "service_description": "MRI right knee",
                    "charged_amount": "1500.00",
                }
            ]
        ),
    )
    detail = response.json()
    assert detail["adjudication_state"] == "under_review"

    line_item = detail["line_items"][0]
    assert line_item["status"] == "needs_review"
    explanation = line_item["current_decision"]["explanation"]
    terminating = [s for s in explanation["steps"] if s.get("terminating")]
    assert terminating[0]["phase"] == "gates"
    assert terminating[0]["result"] == "needs_review"


def test_post_claim_service_date_outside_policy_window_is_eligibility_denied(
    api_client: TestClient,
) -> None:
    """Policies are seeded 2026-01-01 to 2026-12-31. A claim dated
    2027 should be `denied` via the engine's eligibility phase, not
    rejected with a 4xx — the engine owns this case so the wire shape
    stays consistent with "rejected by rules" outcomes.
    """
    response = api_client.post(
        "/api/claims", json=_submit_body(service_date="2027-03-01")
    )
    assert response.status_code == 201

    detail = response.json()
    assert detail["adjudication_state"] == "denied"
    explanation = detail["line_items"][0]["current_decision"]["explanation"]
    terminating = [s for s in explanation["steps"] if s.get("terminating")]
    assert terminating[0]["phase"] == "eligibility"
    assert terminating[0]["result"] == "fail"


def test_post_claim_rejects_empty_line_items_with_422(
    api_client: TestClient,
) -> None:
    response = api_client.post(
        "/api/claims", json=_submit_body(line_items=[])
    )
    assert response.status_code == 422


def test_post_claim_rejects_negative_charged_amount_with_422(
    api_client: TestClient,
) -> None:
    response = api_client.post(
        "/api/claims",
        json=_submit_body(
            line_items=[
                {
                    "service_type": "general_consultation",
                    "service_description": "X",
                    "charged_amount": "-5.00",
                }
            ]
        ),
    )
    assert response.status_code == 422


def test_post_claim_rejects_unknown_field_with_422(
    api_client: TestClient,
) -> None:
    body = _submit_body()
    body["mystery_field"] = "boom"
    response = api_client.post("/api/claims", json=body)
    assert response.status_code == 422


def test_post_claim_rejects_missing_member_id_with_422(
    api_client: TestClient,
) -> None:
    body = _submit_body()
    del body["member_id"]
    response = api_client.post("/api/claims", json=body)
    assert response.status_code == 422


def test_post_claim_response_ledger_invariant_holds(
    api_client: TestClient,
) -> None:
    """`payable + member_responsibility == charged` must hold at the
    wire layer for every line item in the POST response, including
    `denied` (where `payable` is `0`).
    """
    from decimal import Decimal

    for body in (
        _submit_body(),
        _submit_body(
            line_items=[
                {
                    "service_type": "bariatric_surgery",
                    "service_description": "x",
                    "charged_amount": "5000.00",
                }
            ]
        ),
        _submit_body(
            line_items=[
                {
                    "service_type": "mri",
                    "service_description": "x",
                    "charged_amount": "1200.00",
                }
            ]
        ),
    ):
        detail = api_client.post("/api/claims", json=body).json()
        for li in detail["line_items"]:
            payable = Decimal(li["payable_amount"])
            member = Decimal(li["member_responsibility"])
            charged = Decimal(li["charged_amount"])
            assert payable + member == charged


def test_post_claim_intra_claim_accumulator_visible_in_response(
    api_client: TestClient,
) -> None:
    """Two physiotherapy line items on Alice in a single claim that
    together cross the $1000/yr cap: the first should be fully
    coverable, the second should show over-limit member-pay. Verifying
    via the wire shape that intra-claim accumulator updates flow into
    the second line item's explanation.
    """
    from decimal import Decimal

    response = api_client.post(
        "/api/claims",
        json=_submit_body(
            line_items=[
                {
                    "service_type": "physiotherapy",
                    "service_description": "PT 1",
                    "charged_amount": "800.00",
                },
                {
                    "service_type": "physiotherapy",
                    "service_description": "PT 2",
                    "charged_amount": "600.00",
                },
            ]
        ),
    )
    detail = response.json()
    assert detail["adjudication_state"] == "approved"

    # Alice's deductible is $500, then $300 of PT-1 is post-deductible
    # coverable (cap $1000 with $0 used). PT-2 has $200 remaining cap;
    # the other $400 is over-limit member-pay.
    pt1, pt2 = detail["line_items"]
    pt2_steps = pt2["current_decision"]["explanation"]["steps"]
    limits_step = next(s for s in pt2_steps if s["phase"] == "limits")
    assert limits_step["result"] == "applied"
    assert Decimal(limits_step["amount"]) > Decimal("0")
