"""Tests for the SQLAlchemy models' domain ↔ ORM translation.

Round-trip every entity, then assert that the interesting type
contracts hold: enums stay enums, Decimals stay Decimals (no float
drift), datetimes are naive UTC (matching the convention locked in
on `app/domain/entities.py`).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.domain.entities import (
    AdjudicationDecision,
    AuditEvent,
    Claim,
    CoverageRule,
    DecisionOutcome,
    Dispute,
    DisputeStatus,
    LineItem,
    LineItemStatus,
    Member,
    Policy,
    RuleKind,
)
from app.persistence.models import (
    AdjudicationDecisionModel,
    AuditEventModel,
    ClaimModel,
    CoverageRuleModel,
    DisputeModel,
    LineItemModel,
    MemberModel,
    PolicyModel,
)


def _read_session(engine: Engine) -> Session:
    factory = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )
    return factory()


def test_member_roundtrip(session: Session, engine: Engine) -> None:
    m = Member(id="M1", name="Alice")
    session.add(MemberModel.from_domain(m))
    session.commit()

    with _read_session(engine) as s:
        assert s.get(MemberModel, "M1").to_domain() == m


def test_policy_roundtrip_preserves_decimal_precision(
    session: Session, engine: Engine
) -> None:
    p = Policy(
        id="P1",
        member_id="M1",
        name="x",
        effective_date=date(2026, 1, 1),
        termination_date=date(2026, 12, 31),
        annual_deductible=Decimal("500.00"),
    )
    session.add(MemberModel.from_domain(Member(id="M1", name="A")))
    session.add(PolicyModel.from_domain(p))
    session.commit()

    with _read_session(engine) as s:
        round_tripped = s.get(PolicyModel, "P1").to_domain()
    assert round_tripped == p
    assert isinstance(round_tripped.annual_deductible, Decimal)


def test_coverage_rule_roundtrip_preserves_enum_and_json(
    session: Session, engine: Engine
) -> None:
    session.add(MemberModel.from_domain(Member(id="M1", name="A")))
    session.add(
        PolicyModel.from_domain(
            Policy(
                id="P1",
                member_id="M1",
                name="x",
                effective_date=date(2026, 1, 1),
                termination_date=date(2026, 12, 31),
                annual_deductible=Decimal("0.00"),
            )
        )
    )
    session.flush()
    rule = CoverageRule(
        id="R1",
        policy_id="P1",
        service_type="physio",
        kind=RuleKind.ANNUAL_LIMIT,
        parameters={"cap_amount": "1000.00", "period": "calendar_year"},
    )
    session.add(CoverageRuleModel.from_domain(rule))
    session.commit()

    with _read_session(engine) as s:
        round_tripped = s.get(CoverageRuleModel, "R1").to_domain()
    assert round_tripped == rule
    assert isinstance(round_tripped.kind, RuleKind)


def test_claim_roundtrip_preserves_naive_utc_datetime(
    session: Session, engine: Engine
) -> None:
    session.add(MemberModel.from_domain(Member(id="M1", name="A")))
    session.flush()
    c = Claim(
        id="C1",
        member_id="M1",
        provider_name="x",
        service_date=date(2026, 6, 1),
        submitted_at=datetime(2026, 6, 1, 9, 30),
        paid_at=None,
    )
    session.add(ClaimModel.from_domain(c))
    session.commit()

    with _read_session(engine) as s:
        round_tripped = s.get(ClaimModel, "C1").to_domain()
    assert round_tripped == c
    assert round_tripped.submitted_at.tzinfo is None


def test_decision_roundtrip(session: Session, engine: Engine) -> None:
    now = datetime(2026, 6, 1)
    session.add(MemberModel.from_domain(Member(id="M1", name="A")))
    session.add(
        ClaimModel.from_domain(
            Claim(
                id="C1",
                member_id="M1",
                provider_name="x",
                service_date=date(2026, 6, 1),
                submitted_at=now,
                paid_at=None,
            )
        )
    )
    session.add(
        LineItemModel.from_domain(
            LineItem(
                id="L1",
                claim_id="C1",
                service_type="x",
                service_description="x",
                charged_amount=Decimal("100.00"),
                preauth_ref=None,
                status=LineItemStatus.APPROVED,
            )
        )
    )
    session.flush()
    d = AdjudicationDecision(
        id="D1",
        line_item_id="L1",
        decided_at=now,
        decided_by="system",
        outcome=DecisionOutcome.APPROVED,
        payable_amount=Decimal("80.00"),
        member_responsibility=Decimal("20.00"),
        explanation={"steps": [{"phase": "coverage", "result": "pass"}]},
    )
    session.add(AdjudicationDecisionModel.from_domain(d))
    session.commit()

    with _read_session(engine) as s:
        round_tripped = s.get(AdjudicationDecisionModel, "D1").to_domain()
    assert round_tripped == d
    assert isinstance(round_tripped.outcome, DecisionOutcome)


def test_dispute_and_audit_event_roundtrip(
    session: Session, engine: Engine
) -> None:
    now = datetime(2026, 6, 1)
    session.add(MemberModel.from_domain(Member(id="M1", name="A")))
    session.add(
        ClaimModel.from_domain(
            Claim(
                id="C1",
                member_id="M1",
                provider_name="x",
                service_date=date(2026, 6, 1),
                submitted_at=now,
                paid_at=None,
            )
        )
    )
    session.add(
        LineItemModel.from_domain(
            LineItem(
                id="L1",
                claim_id="C1",
                service_type="x",
                service_description="x",
                charged_amount=Decimal("100.00"),
                preauth_ref=None,
                status=LineItemStatus.APPROVED,
            )
        )
    )
    session.flush()
    d = Dispute(
        id="DI1",
        line_item_id="L1",
        filed_at=now,
        reason="x",
        status=DisputeStatus.OPEN,
    )
    ev = AuditEvent(
        id="A1",
        event_type="claim.submitted",
        entity_type="claim",
        entity_id="C1",
        actor="system",
        occurred_at=now,
        payload={"foo": "bar"},
    )
    session.add(DisputeModel.from_domain(d))
    session.add(AuditEventModel.from_domain(ev))
    session.commit()

    with _read_session(engine) as s:
        assert s.get(DisputeModel, "DI1").to_domain() == d
        assert s.get(AuditEventModel, "A1").to_domain() == ev
