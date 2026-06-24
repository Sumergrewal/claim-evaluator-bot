"""Service-layer tests for `adjudicate_line_item`.

These exercise the boundary between the pure engine and the DB:
- decision row persisted with the correct outcome and amounts
- line item's stored `status` mirrors the decision
- exactly one audit event written per call, with the right payload
- non-pending line items are rejected
- accumulator state flows from one adjudication to the next, both
  within a single claim (intra-claim) and across claims (cross-claim)
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from app.adjudication.service import AdjudicationError, adjudicate_line_item
from app.domain.entities import (
    Claim,
    CoverageRule,
    DecisionOutcome,
    LineItem,
    LineItemStatus,
    Member,
    Policy,
    RuleKind,
)
from app.persistence import repositories as repo
from app.persistence.models import (
    ClaimModel,
    CoverageRuleModel,
    LineItemModel,
    MemberModel,
    PolicyModel,
)

_NOW = datetime(2026, 6, 1, 12, 0)


# --- helpers --------------------------------------------------------------


def _add_member(session: Session, mid: str = "M1") -> None:
    session.add(MemberModel.from_domain(Member(id=mid, name=f"Member {mid}")))


def _add_policy(
    session: Session,
    *,
    pid: str = "P1",
    mid: str = "M1",
    deductible: Decimal = Decimal("500.00"),
    name: str = "TestPlan",
) -> None:
    session.add(
        PolicyModel.from_domain(
            Policy(
                id=pid,
                member_id=mid,
                name=name,
                effective_date=date(2026, 1, 1),
                termination_date=date(2026, 12, 31),
                annual_deductible=deductible,
            )
        )
    )


def _add_rule(
    session: Session,
    kind: RuleKind,
    service_type: str,
    *,
    rid: str,
    pid: str = "P1",
    parameters: dict[str, object] | None = None,
) -> None:
    session.add(
        CoverageRuleModel.from_domain(
            CoverageRule(
                id=rid,
                policy_id=pid,
                service_type=service_type,
                kind=kind,
                parameters=parameters or {},
            )
        )
    )


def _add_claim(
    session: Session,
    *,
    cid: str = "C1",
    mid: str = "M1",
    service_date: date = date(2026, 3, 1),
) -> None:
    session.add(
        ClaimModel.from_domain(
            Claim(
                id=cid,
                member_id=mid,
                provider_name="Some Clinic",
                service_date=service_date,
                submitted_at=_NOW,
                paid_at=None,
            )
        )
    )


def _add_line_item(
    session: Session,
    *,
    lid: str,
    cid: str,
    service_type: str,
    charged: Decimal,
    preauth_ref: str | None = None,
) -> None:
    session.add(
        LineItemModel.from_domain(
            LineItem(
                id=lid,
                claim_id=cid,
                service_type=service_type,
                service_description="x",
                charged_amount=charged,
                preauth_ref=preauth_ref,
                status=LineItemStatus.PENDING,
            )
        )
    )


def _seed_basic_consult_setup(
    session: Session,
    *,
    deductible: Decimal = Decimal("500.00"),
) -> None:
    """Member + policy + 'consult covered with $25 copay' rules.

    Caller adds claims and line items on top.
    """
    _add_member(session)
    _add_policy(session, deductible=deductible)
    _add_rule(session, RuleKind.SERVICE_COVERED, "consult", rid="R-COV")
    _add_rule(
        session,
        RuleKind.COPAY,
        "consult",
        rid="R-COPAY",
        parameters={"amount": "25.00"},
    )
    session.flush()


# --- happy path -----------------------------------------------------------


def test_adjudicate_line_item_writes_decision_status_and_audit(
    session: Session,
) -> None:
    _seed_basic_consult_setup(session)
    _add_claim(session, cid="C1")
    _add_line_item(
        session,
        lid="L1",
        cid="C1",
        service_type="consult",
        charged=Decimal("400.00"),
    )
    session.flush()

    decision = adjudicate_line_item(session, "L1", now=_NOW)

    # Decision approved, deductible eats the entire $400 (copay capped at $0).
    assert decision.outcome is DecisionOutcome.APPROVED
    assert decision.payable_amount == Decimal("0.00")
    assert decision.member_responsibility == Decimal("400.00")
    assert decision.deductible_applied == Decimal("400.00")
    assert decision.supersedes_id is None
    # Decision id defaults to a fresh UUID hex.
    UUID(hex=decision.id)

    # Persisted: current decision matches the returned one.
    current = repo.get_current_decision_for_line_item(session, "L1")
    assert current is not None
    assert current.id == decision.id
    assert current.deductible_applied == Decimal("400.00")

    # Line item status mirrors the new outcome.
    li = repo.get_line_item(session, "L1")
    assert li is not None
    assert li.status is LineItemStatus.APPROVED
    assert li.payable_amount == Decimal("0.00")

    # One audit event with the full payload.
    events = repo.list_audit_events_for(session, "line_item", "L1")
    assert len(events) == 1
    ev = events[0]
    assert ev.event_type == "line_item.decided"
    assert ev.actor == "system"
    assert ev.payload["decision_id"] == decision.id
    assert ev.payload["outcome"] == "approved"
    assert ev.payload["previous_status"] == "pending"
    assert ev.payload["new_status"] == "approved"
    assert ev.payload["payable_amount"] == "0.00"
    assert ev.payload["member_responsibility"] == "400.00"
    assert ev.payload["deductible_applied"] == "400.00"
    assert ev.payload["supersedes_id"] is None


# --- denied path ----------------------------------------------------------


def test_adjudicate_line_item_writes_denied_decision_when_service_excluded(
    session: Session,
) -> None:
    _add_member(session)
    _add_policy(session, name="Basic Health 2026")
    _add_rule(
        session,
        RuleKind.SERVICE_EXCLUDED,
        "bariatric_surgery",
        rid="R-EXC",
    )
    session.flush()
    _add_claim(session, cid="C1", service_date=date(2026, 7, 1))
    _add_line_item(
        session,
        lid="L1",
        cid="C1",
        service_type="bariatric_surgery",
        charged=Decimal("20000.00"),
    )
    session.flush()

    decision = adjudicate_line_item(session, "L1", now=_NOW)

    assert decision.outcome is DecisionOutcome.DENIED
    assert decision.payable_amount == Decimal("0.00")
    assert decision.member_responsibility == Decimal("20000.00")
    assert decision.deductible_applied == Decimal("0.00")

    li = repo.get_line_item(session, "L1")
    assert li is not None
    assert li.status is LineItemStatus.DENIED

    events = repo.list_audit_events_for(session, "line_item", "L1")
    assert events[0].payload["new_status"] == "denied"


# --- needs_review path ----------------------------------------------------


def test_adjudicate_line_item_writes_needs_review_when_preauth_missing(
    session: Session,
) -> None:
    _add_member(session)
    _add_policy(session, deductible=Decimal("0.00"), name="Family Dental 2026")
    _add_rule(session, RuleKind.SERVICE_COVERED, "root_canal", rid="R-COV")
    _add_rule(
        session,
        RuleKind.PREAUTH_REQUIRED,
        "root_canal",
        rid="R-PRE",
    )
    _add_rule(
        session,
        RuleKind.COINSURANCE,
        "root_canal",
        rid="R-COIN",
        parameters={"member_pct": 30},
    )
    session.flush()
    _add_claim(session, cid="C1", service_date=date(2026, 6, 1))
    _add_line_item(
        session,
        lid="L1",
        cid="C1",
        service_type="root_canal",
        charged=Decimal("900.00"),
        preauth_ref=None,
    )
    session.flush()

    decision = adjudicate_line_item(session, "L1", now=_NOW)

    assert decision.outcome is DecisionOutcome.NEEDS_REVIEW
    assert decision.payable_amount == Decimal("0.00")
    assert decision.member_responsibility == Decimal("900.00")

    li = repo.get_line_item(session, "L1")
    assert li is not None
    assert li.status is LineItemStatus.NEEDS_REVIEW

    events = repo.list_audit_events_for(session, "line_item", "L1")
    assert events[0].payload["new_status"] == "needs_review"


# --- eligibility (no active policy) --------------------------------------


def test_adjudicate_line_item_denies_when_no_policy_active_on_service_date(
    session: Session,
) -> None:
    _add_member(session)
    # Policy only valid in 2025; claim is in 2026 → no active policy.
    session.add(
        PolicyModel.from_domain(
            Policy(
                id="P-OLD",
                member_id="M1",
                name="Old Plan",
                effective_date=date(2025, 1, 1),
                termination_date=date(2025, 12, 31),
                annual_deductible=Decimal("0.00"),
            )
        )
    )
    session.flush()
    _add_claim(session, cid="C1", service_date=date(2026, 3, 1))
    _add_line_item(
        session,
        lid="L1",
        cid="C1",
        service_type="consult",
        charged=Decimal("100.00"),
    )
    session.flush()

    decision = adjudicate_line_item(session, "L1", now=_NOW)

    assert decision.outcome is DecisionOutcome.DENIED
    assert decision.explanation["steps"][0]["phase"] == "eligibility"
    assert decision.explanation["steps"][0]["result"] == "fail"


# --- non-pending input ----------------------------------------------------


def test_adjudicate_line_item_rejects_already_decided_line_item(
    session: Session,
) -> None:
    _seed_basic_consult_setup(session)
    _add_claim(session, cid="C1")
    _add_line_item(
        session,
        lid="L1",
        cid="C1",
        service_type="consult",
        charged=Decimal("100.00"),
    )
    session.flush()

    adjudicate_line_item(session, "L1", now=_NOW)

    # Second call refuses — the line item is no longer pending.
    with pytest.raises(AdjudicationError, match="not pending"):
        adjudicate_line_item(session, "L1", now=_NOW)


def test_adjudicate_line_item_raises_when_line_item_missing(
    session: Session,
) -> None:
    with pytest.raises(AdjudicationError, match="not found"):
        adjudicate_line_item(session, "L-NOPE", now=_NOW)


# --- intra-claim accumulator flow ----------------------------------------


def test_adjudicate_intra_claim_accumulator_clips_second_line_item_at_cap(
    session: Session,
) -> None:
    """Mirrors C-CAROL-004: two crowns in one claim against a $750 cap.

    L1 ($600 charge): coverable $600, coinsurance 30% = $180 member,
    plan pays $420. Cap consumed: $420.

    L2 ($400 charge): cap remaining = $750 - $420 = $330, coverable
    $330, coinsurance 30% = $99 member, $70 over_limit. Plan pays
    $231, member pays $169. Without the in-session accumulator flow
    L2 would think the cap was still empty.
    """
    _add_member(session)
    _add_policy(session, deductible=Decimal("0.00"), name="Family Dental 2026")
    _add_rule(session, RuleKind.SERVICE_COVERED, "crown", rid="R-COV")
    _add_rule(
        session,
        RuleKind.ANNUAL_LIMIT,
        "crown",
        rid="R-LIM",
        parameters={"cap_amount": "750.00", "period": "calendar_year"},
    )
    _add_rule(
        session,
        RuleKind.COINSURANCE,
        "crown",
        rid="R-COIN",
        parameters={"member_pct": 30},
    )
    session.flush()
    _add_claim(session, cid="C1", service_date=date(2026, 6, 15))
    _add_line_item(
        session,
        lid="L1",
        cid="C1",
        service_type="crown",
        charged=Decimal("600.00"),
    )
    _add_line_item(
        session,
        lid="L2",
        cid="C1",
        service_type="crown",
        charged=Decimal("400.00"),
    )
    session.flush()

    d1 = adjudicate_line_item(session, "L1", now=_NOW)
    d2 = adjudicate_line_item(session, "L2", now=_NOW)

    assert d1.payable_amount == Decimal("420.00")
    assert d1.member_responsibility == Decimal("180.00")

    assert d2.payable_amount == Decimal("231.00")
    assert d2.member_responsibility == Decimal("169.00")


def test_adjudicate_intra_claim_deductible_accumulator_flows_across_line_items(
    session: Session,
) -> None:
    """Two consults in one claim against a $500 deductible.

    L1 ($300 charge): deductible takes $300, copay capped at $0.
    L2 ($300 charge): only $200 deductible remaining, takes $200,
    copay applies on the remaining $100 at $25.
    """
    _seed_basic_consult_setup(session)
    _add_claim(session, cid="C1")
    _add_line_item(
        session,
        lid="L1",
        cid="C1",
        service_type="consult",
        charged=Decimal("300.00"),
    )
    _add_line_item(
        session,
        lid="L2",
        cid="C1",
        service_type="consult",
        charged=Decimal("300.00"),
    )
    session.flush()

    d1 = adjudicate_line_item(session, "L1", now=_NOW)
    d2 = adjudicate_line_item(session, "L2", now=_NOW)

    assert d1.deductible_applied == Decimal("300.00")
    assert d1.payable_amount == Decimal("0.00")
    assert d1.member_responsibility == Decimal("300.00")

    assert d2.deductible_applied == Decimal("200.00")
    # $300 - $200 deductible - $25 copay = $75 plan-pay
    assert d2.payable_amount == Decimal("75.00")
    assert d2.member_responsibility == Decimal("225.00")


# --- cross-claim accumulator flow ----------------------------------------


def test_adjudicate_cross_claim_limit_accumulator_persists_between_calls(
    session: Session,
) -> None:
    """C-ALICE-003 then C-ALICE-004: physio cap $1000 consumed across
    two distinct claims for the same member.
    """
    _add_member(session)
    _add_policy(session, deductible=Decimal("0.00"))
    _add_rule(session, RuleKind.SERVICE_COVERED, "physio", rid="R-COV")
    _add_rule(
        session,
        RuleKind.ANNUAL_LIMIT,
        "physio",
        rid="R-LIM",
        parameters={"cap_amount": "1000.00", "period": "calendar_year"},
    )
    _add_rule(
        session,
        RuleKind.COINSURANCE,
        "physio",
        rid="R-COIN",
        parameters={"member_pct": 20},
    )
    session.flush()
    _add_claim(session, cid="C1", service_date=date(2026, 4, 20))
    _add_line_item(
        session,
        lid="L1",
        cid="C1",
        service_type="physio",
        charged=Decimal("800.00"),
    )
    _add_claim(session, cid="C2", service_date=date(2026, 6, 10))
    _add_line_item(
        session,
        lid="L2",
        cid="C2",
        service_type="physio",
        charged=Decimal("400.00"),
    )
    session.flush()

    d1 = adjudicate_line_item(session, "L1", now=_NOW)
    d2 = adjudicate_line_item(session, "L2", now=_NOW)

    # C1: $800 coverable, 20% = $160 member, $640 plan-pay. Cap used: $640.
    assert d1.payable_amount == Decimal("640.00")
    # C2: cap remaining $360. Coverable $360, 20% = $72 member,
    # $40 over_limit. Plan pays $288, member pays $112.
    assert d2.payable_amount == Decimal("288.00")
    assert d2.member_responsibility == Decimal("112.00")


# --- explanation persistence ---------------------------------------------


def test_adjudicate_line_item_persists_full_explanation_json(
    session: Session,
) -> None:
    _seed_basic_consult_setup(session, deductible=Decimal("0.00"))
    _add_claim(session, cid="C1")
    _add_line_item(
        session,
        lid="L1",
        cid="C1",
        service_type="consult",
        charged=Decimal("100.00"),
    )
    session.flush()

    decision = adjudicate_line_item(session, "L1", now=_NOW)

    explanation = decision.explanation
    assert explanation["outcome"] == "approved"
    assert explanation["charged_amount"] == "100.00"
    assert explanation["payable_amount"] == "75.00"
    assert explanation["member_responsibility"] == "25.00"
    assert [s["phase"] for s in explanation["steps"]] == [
        "eligibility",
        "coverage",
        "gates",
        "deductible",
        "limits",
        "cost_sharing",
    ]
    assert explanation["narrative"].startswith("Covered under consult.")
