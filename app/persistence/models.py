"""SQLAlchemy ORM models with explicit domain ↔ ORM translation.

One model per entity in `app/domain/entities.py`. Translation lives at
the boundary: `from_domain(...)` builds an ORM row from a domain
entity; `to_domain(...)` does the reverse. Repositories return domain
objects, never ORM rows — the rest of the codebase is unaware these
classes exist.

Money is stored as `Decimal` via `Numeric(12, 2)`. Coverage-rule
parameters and decision explanations are JSON; money values inside
those JSON blobs are kept as quoted strings so `Decimal` round-trip
stays exact (see the seed-data decision in `docs/decisions.md`).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Enum, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
from app.persistence.database import Base

MONEY = Numeric(12, 2)


class MemberModel(Base):
    __tablename__ = "members"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)

    policies: Mapped[list[PolicyModel]] = relationship(back_populates="member")
    claims: Mapped[list[ClaimModel]] = relationship(back_populates="member")

    def to_domain(self) -> Member:
        return Member(id=self.id, name=self.name)

    @classmethod
    def from_domain(cls, m: Member) -> MemberModel:
        return cls(id=m.id, name=m.name)


class PolicyModel(Base):
    __tablename__ = "policies"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    effective_date: Mapped[date] = mapped_column(nullable=False)
    termination_date: Mapped[date | None] = mapped_column(nullable=True)
    annual_deductible: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    member: Mapped[MemberModel] = relationship(back_populates="policies")
    rules: Mapped[list[CoverageRuleModel]] = relationship(back_populates="policy")

    def to_domain(self) -> Policy:
        return Policy(
            id=self.id,
            member_id=self.member_id,
            name=self.name,
            effective_date=self.effective_date,
            termination_date=self.termination_date,
            annual_deductible=self.annual_deductible,
        )

    @classmethod
    def from_domain(cls, p: Policy) -> PolicyModel:
        return cls(
            id=p.id,
            member_id=p.member_id,
            name=p.name,
            effective_date=p.effective_date,
            termination_date=p.termination_date,
            annual_deductible=p.annual_deductible,
        )


class CoverageRuleModel(Base):
    __tablename__ = "coverage_rules"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    policy_id: Mapped[str] = mapped_column(ForeignKey("policies.id"), nullable=False)
    service_type: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[RuleKind] = mapped_column(
        Enum(RuleKind, name="rule_kind"), nullable=False
    )
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    policy: Mapped[PolicyModel] = relationship(back_populates="rules")

    def to_domain(self) -> CoverageRule:
        return CoverageRule(
            id=self.id,
            policy_id=self.policy_id,
            service_type=self.service_type,
            kind=self.kind,
            parameters=dict(self.parameters),
        )

    @classmethod
    def from_domain(cls, r: CoverageRule) -> CoverageRuleModel:
        return cls(
            id=r.id,
            policy_id=r.policy_id,
            service_type=r.service_type,
            kind=r.kind,
            parameters=dict(r.parameters),
        )


class ClaimModel(Base):
    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), nullable=False)
    provider_name: Mapped[str] = mapped_column(String, nullable=False)
    service_date: Mapped[date] = mapped_column(nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(nullable=True)

    member: Mapped[MemberModel] = relationship(back_populates="claims")
    line_items: Mapped[list[LineItemModel]] = relationship(
        back_populates="claim",
        order_by="LineItemModel.id",
    )

    def to_domain(self) -> Claim:
        return Claim(
            id=self.id,
            member_id=self.member_id,
            provider_name=self.provider_name,
            service_date=self.service_date,
            submitted_at=self.submitted_at,
            paid_at=self.paid_at,
        )

    @classmethod
    def from_domain(cls, c: Claim) -> ClaimModel:
        return cls(
            id=c.id,
            member_id=c.member_id,
            provider_name=c.provider_name,
            service_date=c.service_date,
            submitted_at=c.submitted_at,
            paid_at=c.paid_at,
        )


class LineItemModel(Base):
    __tablename__ = "line_items"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), nullable=False)
    service_type: Mapped[str] = mapped_column(String, nullable=False)
    service_description: Mapped[str] = mapped_column(String, nullable=False)
    charged_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    preauth_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[LineItemStatus] = mapped_column(
        Enum(LineItemStatus, name="line_item_status"), nullable=False
    )

    claim: Mapped[ClaimModel] = relationship(back_populates="line_items")
    decisions: Mapped[list[AdjudicationDecisionModel]] = relationship(
        back_populates="line_item",
        order_by="AdjudicationDecisionModel.decided_at",
    )

    def to_domain(
        self,
        payable_amount: Decimal | None = None,
        member_responsibility: Decimal | None = None,
    ) -> LineItem:
        """Translate to domain.

        Derived amounts come from the line item's current
        `AdjudicationDecision`; the repository looks the current
        decision up and passes the amounts in. They default to `None`
        so callers that don't need them (e.g. line items not yet
        adjudicated) can ignore the kwargs.
        """
        return LineItem(
            id=self.id,
            claim_id=self.claim_id,
            service_type=self.service_type,
            service_description=self.service_description,
            charged_amount=self.charged_amount,
            preauth_ref=self.preauth_ref,
            status=self.status,
            payable_amount=payable_amount,
            member_responsibility=member_responsibility,
        )

    @classmethod
    def from_domain(cls, li: LineItem) -> LineItemModel:
        return cls(
            id=li.id,
            claim_id=li.claim_id,
            service_type=li.service_type,
            service_description=li.service_description,
            charged_amount=li.charged_amount,
            preauth_ref=li.preauth_ref,
            status=li.status,
        )


class AdjudicationDecisionModel(Base):
    __tablename__ = "adjudication_decisions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    line_item_id: Mapped[str] = mapped_column(
        ForeignKey("line_items.id"), nullable=False
    )
    decided_at: Mapped[datetime] = mapped_column(nullable=False)
    decided_by: Mapped[str] = mapped_column(String, nullable=False)
    outcome: Mapped[DecisionOutcome] = mapped_column(
        Enum(DecisionOutcome, name="decision_outcome"), nullable=False
    )
    payable_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    member_responsibility: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    explanation: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    supersedes_id: Mapped[str | None] = mapped_column(
        ForeignKey("adjudication_decisions.id"), nullable=True
    )

    line_item: Mapped[LineItemModel] = relationship(back_populates="decisions")

    def to_domain(self) -> AdjudicationDecision:
        return AdjudicationDecision(
            id=self.id,
            line_item_id=self.line_item_id,
            decided_at=self.decided_at,
            decided_by=self.decided_by,
            outcome=self.outcome,
            payable_amount=self.payable_amount,
            member_responsibility=self.member_responsibility,
            explanation=dict(self.explanation),
            supersedes_id=self.supersedes_id,
        )

    @classmethod
    def from_domain(cls, d: AdjudicationDecision) -> AdjudicationDecisionModel:
        return cls(
            id=d.id,
            line_item_id=d.line_item_id,
            decided_at=d.decided_at,
            decided_by=d.decided_by,
            outcome=d.outcome,
            payable_amount=d.payable_amount,
            member_responsibility=d.member_responsibility,
            explanation=dict(d.explanation),
            supersedes_id=d.supersedes_id,
        )


class DisputeModel(Base):
    __tablename__ = "disputes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    line_item_id: Mapped[str] = mapped_column(
        ForeignKey("line_items.id"), nullable=False
    )
    filed_at: Mapped[datetime] = mapped_column(nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[DisputeStatus] = mapped_column(
        Enum(DisputeStatus, name="dispute_status"), nullable=False
    )
    resolution_note: Mapped[str | None] = mapped_column(String, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(nullable=True)

    def to_domain(self) -> Dispute:
        return Dispute(
            id=self.id,
            line_item_id=self.line_item_id,
            filed_at=self.filed_at,
            reason=self.reason,
            status=self.status,
            resolution_note=self.resolution_note,
            resolved_at=self.resolved_at,
        )

    @classmethod
    def from_domain(cls, d: Dispute) -> DisputeModel:
        return cls(
            id=d.id,
            line_item_id=d.line_item_id,
            filed_at=d.filed_at,
            reason=d.reason,
            status=d.status,
            resolution_note=d.resolution_note,
            resolved_at=d.resolved_at,
        )


class AuditEventModel(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[str] = mapped_column(String, nullable=False)
    actor: Mapped[str] = mapped_column(String, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    def to_domain(self) -> AuditEvent:
        return AuditEvent(
            id=self.id,
            event_type=self.event_type,
            entity_type=self.entity_type,
            entity_id=self.entity_id,
            actor=self.actor,
            occurred_at=self.occurred_at,
            payload=dict(self.payload),
        )

    @classmethod
    def from_domain(cls, e: AuditEvent) -> AuditEventModel:
        return cls(
            id=e.id,
            event_type=e.event_type,
            entity_type=e.entity_type,
            entity_id=e.entity_id,
            actor=e.actor,
            occurred_at=e.occurred_at,
            payload=dict(e.payload),
        )
