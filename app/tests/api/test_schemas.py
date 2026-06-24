"""Tests for the API schemas in `app/api/schemas.py`.

Pure-Python: no DB session, no HTTP client. Each test names the
behaviour under test. The next step in phase 07 will exercise the
schemas end-to-end through `TestClient`; this file pins the
domain ↔ schema translation and the input-validation rules in
isolation so route-handler tests can focus on routing concerns.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.api.schemas import (
    AuditEventOut,
    ClaimDetailOut,
    ClaimSubmitIn,
    ClaimSummaryOut,
    ClaimTotalsOut,
    DecisionOut,
    ExplanationOut,
    ExplanationStepOut,
    LineItemOut,
    LineItemSubmitIn,
    MemberOut,
)
from app.domain.claim_state import ClaimAdjudicationState
from app.domain.entities import (
    AdjudicationDecision,
    AuditEvent,
    Claim,
    DecisionOutcome,
    LineItem,
    LineItemStatus,
    Member,
)

# --- Fixtures --------------------------------------------------------------


def _alice() -> Member:
    return Member(id="M-001", name="Alice Anderson")


def _claim(*, paid_at: datetime | None = None) -> Claim:
    return Claim(
        id="C-1",
        member_id="M-001",
        provider_name="Northside Family Clinic",
        service_date=date(2026, 2, 10),
        submitted_at=datetime(2026, 2, 11, 9, 30),
        paid_at=paid_at,
    )


def _line_item(
    *,
    id: str = "L-1",
    status: LineItemStatus = LineItemStatus.APPROVED,
    charged: str = "100.00",
    payable: str | None = "70.00",
    member: str | None = "30.00",
) -> LineItem:
    return LineItem(
        id=id,
        claim_id="C-1",
        service_type="general_consultation",
        service_description="Visit",
        charged_amount=Decimal(charged),
        preauth_ref=None,
        status=status,
        payable_amount=Decimal(payable) if payable is not None else None,
        member_responsibility=Decimal(member) if member is not None else None,
    )


def _approved_explanation_dict() -> dict:
    return {
        "outcome": "approved",
        "charged_amount": "100.00",
        "payable_amount": "70.00",
        "member_responsibility": "30.00",
        "steps": [
            {
                "phase": "eligibility",
                "rule_id": None,
                "result": "pass",
                "note": "policy POL-1 active on 2026-02-10",
            },
            {
                "phase": "coverage",
                "rule_id": "R-1",
                "result": "pass",
                "note": "general_consultation is covered",
            },
            {
                "phase": "deductible",
                "rule_id": None,
                "result": "applied",
                "note": "applied $30.00 of annual deductible",
                "amount": "30.00",
            },
        ],
        "narrative": "Covered. Plan pays $70.00 of $100.00 charged.",
    }


def _decision(
    *,
    line_item_id: str = "L-1",
    outcome: DecisionOutcome = DecisionOutcome.APPROVED,
    payable: str = "70.00",
    member: str = "30.00",
    deductible_applied: str = "30.00",
    supersedes_id: str | None = None,
) -> AdjudicationDecision:
    return AdjudicationDecision(
        id="D-1",
        line_item_id=line_item_id,
        decided_at=datetime(2026, 2, 11, 9, 35),
        decided_by="system",
        outcome=outcome,
        payable_amount=Decimal(payable),
        member_responsibility=Decimal(member),
        explanation=_approved_explanation_dict(),
        supersedes_id=supersedes_id,
        deductible_applied=Decimal(deductible_applied),
    )


# --- MemberOut -------------------------------------------------------------


def test_member_out_round_trips_from_domain() -> None:
    out = MemberOut.from_domain(_alice())
    assert out.id == "M-001"
    assert out.name == "Alice Anderson"


# --- ExplanationOut --------------------------------------------------------


def test_explanation_out_parses_engine_json_unchanged() -> None:
    out = ExplanationOut.model_validate(_approved_explanation_dict())
    assert out.outcome is DecisionOutcome.APPROVED
    assert out.charged_amount == "100.00"
    assert out.payable_amount == "70.00"
    assert out.member_responsibility == "30.00"
    assert out.narrative.startswith("Covered.")
    assert len(out.steps) == 3


def test_explanation_step_omits_optional_amount_and_terminating_when_absent() -> None:
    step = ExplanationStepOut.model_validate(
        {
            "phase": "eligibility",
            "rule_id": None,
            "result": "pass",
            "note": "policy P active",
        }
    )
    assert step.amount is None
    assert step.terminating is None


def test_explanation_step_carries_amount_and_terminating_when_present() -> None:
    step = ExplanationStepOut.model_validate(
        {
            "phase": "coverage",
            "rule_id": "R-X",
            "result": "fail",
            "note": "excluded",
            "terminating": True,
        }
    )
    assert step.result.value == "fail"
    assert step.terminating is True


# --- DecisionOut -----------------------------------------------------------


def test_decision_out_carries_full_explanation_from_domain() -> None:
    out = DecisionOut.from_domain(_decision())
    assert out.id == "D-1"
    assert out.outcome is DecisionOutcome.APPROVED
    assert out.payable_amount == Decimal("70.00")
    assert out.deductible_applied == Decimal("30.00")
    assert out.supersedes_id is None
    assert out.explanation.payable_amount == "70.00"
    assert out.explanation.steps[0].phase.value == "eligibility"


def test_decision_out_preserves_supersedes_chain() -> None:
    out = DecisionOut.from_domain(_decision(supersedes_id="D-0"))
    assert out.supersedes_id == "D-0"


# --- LineItemOut -----------------------------------------------------------


def test_line_item_out_without_current_decision_has_none_decision() -> None:
    out = LineItemOut.from_domain(
        _line_item(
            status=LineItemStatus.PENDING, payable=None, member=None
        ),
        current_decision=None,
    )
    assert out.status is LineItemStatus.PENDING
    assert out.payable_amount is None
    assert out.member_responsibility is None
    assert out.current_decision is None


def test_line_item_out_with_current_decision_embeds_full_decision() -> None:
    out = LineItemOut.from_domain(_line_item(), current_decision=_decision())
    assert out.current_decision is not None
    assert out.current_decision.id == "D-1"
    assert out.current_decision.explanation.outcome is DecisionOutcome.APPROVED
    assert out.payable_amount == Decimal("70.00")
    assert out.member_responsibility == Decimal("30.00")


# --- ClaimTotalsOut --------------------------------------------------------


def test_claim_totals_sums_only_line_items_with_decided_amounts() -> None:
    decided = _line_item()
    pending = _line_item(
        id="L-2", status=LineItemStatus.PENDING, payable=None, member=None
    )
    totals = ClaimTotalsOut.from_line_items([decided, pending])
    assert totals.charged == Decimal("200.00")
    assert totals.payable == Decimal("70.00")
    assert totals.member_responsibility == Decimal("30.00")


def test_claim_totals_empty_line_items_returns_zeros() -> None:
    totals = ClaimTotalsOut.from_line_items([])
    assert totals.charged == Decimal("0.00")
    assert totals.payable == Decimal("0.00")
    assert totals.member_responsibility == Decimal("0.00")


# --- ClaimSummaryOut -------------------------------------------------------


def test_claim_summary_derives_paid_state_when_paid_at_set() -> None:
    summary = ClaimSummaryOut.from_domain(
        claim=_claim(paid_at=datetime(2026, 3, 15)),
        member_name="Alice Anderson",
        line_items=[_line_item()],
    )
    assert summary.adjudication_state is ClaimAdjudicationState.PAID
    assert summary.member_name == "Alice Anderson"
    assert summary.totals.payable == Decimal("70.00")


def test_claim_summary_derives_submitted_state_when_all_pending() -> None:
    summary = ClaimSummaryOut.from_domain(
        claim=_claim(),
        member_name="Alice Anderson",
        line_items=[
            _line_item(
                status=LineItemStatus.PENDING, payable=None, member=None
            )
        ],
    )
    assert summary.adjudication_state is ClaimAdjudicationState.SUBMITTED


def test_claim_summary_derives_partially_approved_for_mixed_decisions() -> None:
    summary = ClaimSummaryOut.from_domain(
        claim=_claim(),
        member_name="Alice Anderson",
        line_items=[
            _line_item(),
            _line_item(
                id="L-2",
                status=LineItemStatus.DENIED,
                charged="50.00",
                payable="0.00",
                member="50.00",
            ),
        ],
    )
    assert (
        summary.adjudication_state
        is ClaimAdjudicationState.PARTIALLY_APPROVED
    )


def test_claim_summary_derives_under_review_when_any_line_needs_review() -> None:
    summary = ClaimSummaryOut.from_domain(
        claim=_claim(),
        member_name="Alice Anderson",
        line_items=[
            _line_item(),
            _line_item(
                id="L-2",
                status=LineItemStatus.NEEDS_REVIEW,
                charged="50.00",
                payable="0.00",
                member="50.00",
            ),
        ],
    )
    assert summary.adjudication_state is ClaimAdjudicationState.UNDER_REVIEW


def test_claim_summary_derives_denied_when_every_line_denied() -> None:
    summary = ClaimSummaryOut.from_domain(
        claim=_claim(),
        member_name="Alice Anderson",
        line_items=[
            _line_item(
                status=LineItemStatus.DENIED,
                payable="0.00",
                member="100.00",
            )
        ],
    )
    assert summary.adjudication_state is ClaimAdjudicationState.DENIED


def test_claim_summary_derives_approved_when_every_line_approved() -> None:
    summary = ClaimSummaryOut.from_domain(
        claim=_claim(),
        member_name="Alice Anderson",
        line_items=[_line_item()],
    )
    assert summary.adjudication_state is ClaimAdjudicationState.APPROVED


# --- ClaimDetailOut --------------------------------------------------------


def test_claim_detail_preserves_line_item_order_and_attaches_decisions() -> None:
    li_a = _line_item()
    li_b = _line_item(id="L-2", charged="50.00", payable="40.00", member="10.00")
    dec_b = _decision(line_item_id="L-2", payable="40.00", member="10.00")
    audit = AuditEvent(
        id="E-1",
        event_type="line_item.decided",
        entity_type="line_item",
        entity_id="L-1",
        actor="system",
        occurred_at=datetime(2026, 2, 11, 9, 35),
        payload={"outcome": "approved"},
    )

    detail = ClaimDetailOut.from_domain(
        claim=_claim(),
        member_name="Alice Anderson",
        line_items_with_decisions=[(li_a, _decision()), (li_b, dec_b)],
        audit_events=[audit],
    )
    assert [li.id for li in detail.line_items] == ["L-1", "L-2"]
    assert detail.line_items[1].current_decision is not None
    assert detail.line_items[1].current_decision.payable_amount == Decimal(
        "40.00"
    )
    assert detail.totals.charged == Decimal("150.00")
    assert detail.audit_events[0].event_type == "line_item.decided"


def test_claim_detail_handles_pending_line_item_without_decision() -> None:
    li_pending = _line_item(
        status=LineItemStatus.PENDING, payable=None, member=None
    )
    detail = ClaimDetailOut.from_domain(
        claim=_claim(),
        member_name="Alice Anderson",
        line_items_with_decisions=[(li_pending, None)],
        audit_events=[],
    )
    assert detail.line_items[0].current_decision is None
    assert detail.adjudication_state is ClaimAdjudicationState.SUBMITTED


# --- AuditEventOut ---------------------------------------------------------


def test_audit_event_out_copies_payload_dict() -> None:
    payload = {"outcome": "approved", "deductible_applied": "30.00"}
    event = AuditEvent(
        id="E-1",
        event_type="line_item.decided",
        entity_type="line_item",
        entity_id="L-1",
        actor="system",
        occurred_at=datetime(2026, 2, 11, 9, 35),
        payload=payload,
    )
    out = AuditEventOut.from_domain(event)
    assert out.payload == payload
    assert out.payload is not payload


# --- JSON serialisation ----------------------------------------------------


def test_decimal_fields_serialise_to_json_strings() -> None:
    payload = LineItemOut.from_domain(
        _line_item(), current_decision=_decision()
    ).model_dump(mode="json")
    assert payload["charged_amount"] == "100.00"
    assert payload["payable_amount"] == "70.00"
    assert payload["current_decision"]["deductible_applied"] == "30.00"


def test_explanation_money_strings_pass_through_unchanged() -> None:
    payload = ExplanationOut.model_validate(
        _approved_explanation_dict()
    ).model_dump(mode="json")
    assert payload["charged_amount"] == "100.00"
    assert payload["steps"][2]["amount"] == "30.00"


# --- Input validation: LineItemSubmitIn -----------------------------------


def test_line_item_submit_accepts_well_formed_body() -> None:
    item = LineItemSubmitIn.model_validate(
        {
            "service_type": "physiotherapy",
            "service_description": "PT visit",
            "charged_amount": "150.00",
            "preauth_ref": None,
        }
    )
    assert item.charged_amount == Decimal("150.00")


def test_line_item_submit_rejects_negative_charged_amount() -> None:
    with pytest.raises(ValidationError) as exc:
        LineItemSubmitIn.model_validate(
            {
                "service_type": "physiotherapy",
                "service_description": "PT visit",
                "charged_amount": "-5.00",
            }
        )
    assert "charged_amount" in str(exc.value)


def test_line_item_submit_rejects_empty_service_type() -> None:
    with pytest.raises(ValidationError):
        LineItemSubmitIn.model_validate(
            {
                "service_type": "",
                "service_description": "PT visit",
                "charged_amount": "10.00",
            }
        )


def test_line_item_submit_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError) as exc:
        LineItemSubmitIn.model_validate(
            {
                "service_type": "physiotherapy",
                "service_description": "PT visit",
                "charged_amount": "10.00",
                "unexpected": "field",
            }
        )
    assert "unexpected" in str(exc.value)


# --- Input validation: ClaimSubmitIn --------------------------------------


def test_claim_submit_accepts_well_formed_body() -> None:
    claim = ClaimSubmitIn.model_validate(
        {
            "member_id": "M-001",
            "provider_name": "Northside",
            "service_date": "2026-02-10",
            "line_items": [
                {
                    "service_type": "x",
                    "service_description": "y",
                    "charged_amount": "10.00",
                }
            ],
        }
    )
    assert claim.member_id == "M-001"
    assert claim.service_date == date(2026, 2, 10)
    assert len(claim.line_items) == 1


def test_claim_submit_rejects_empty_line_items() -> None:
    with pytest.raises(ValidationError) as exc:
        ClaimSubmitIn.model_validate(
            {
                "member_id": "M-001",
                "provider_name": "Northside",
                "service_date": "2026-02-10",
                "line_items": [],
            }
        )
    assert "line_items" in str(exc.value)


def test_claim_submit_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ClaimSubmitIn.model_validate(
            {
                "member_id": "M-001",
                "provider_name": "Northside",
                "service_date": "2026-02-10",
                "line_items": [
                    {
                        "service_type": "x",
                        "service_description": "y",
                        "charged_amount": "10.00",
                    }
                ],
                "secret_field": "boom",
            }
        )


def test_claim_submit_rejects_missing_member_id() -> None:
    with pytest.raises(ValidationError) as exc:
        ClaimSubmitIn.model_validate(
            {
                "provider_name": "Northside",
                "service_date": "2026-02-10",
                "line_items": [
                    {
                        "service_type": "x",
                        "service_description": "y",
                        "charged_amount": "10.00",
                    }
                ],
            }
        )
    assert "member_id" in str(exc.value)
