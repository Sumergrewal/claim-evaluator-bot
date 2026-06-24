"""YAML seed loader.

Inserts raw entities (Member, Policy, CoverageRule, Claim, LineItem)
into the database from YAML files in `data/`. `AdjudicationDecision`
rows are never seeded — engine output is not seed data; the engine
fills them on the same startup (phase 06).

Two seed claims (C-BOB-001 and C-CAROL-001) carry `paid_at` so the
`paid` lifecycle state is visible on first launch. Their line items
are seeded `pending`; the engine adjudicates them before the first
HTTP request, so the intermediate "claim paid / line items pending"
state is never observable through the UI. See `derive_claim_state`
for the short-circuit that's compatible with this ordering.

Validation pipeline:

1. YAML parse (`yaml.safe_load`).
2. Pydantic models per file: shape, types, `Decimal` parsing, and a
   discriminated union on `kind` with per-kind parameter schemas.
3. Cross-entity invariants: referential integrity, id uniqueness,
   and "at most one cost-sharing rule per (policy, service_type)"
   from `docs/domain-model.md`.
4. Insertion in dependency order, all within the caller's
   transaction. The caller commits.

Any failure raises `SeedLoadError` with a message that names the
offending file or entity.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal, TypeVar

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.entities import (
    Claim,
    CoverageRule,
    LineItem,
    LineItemStatus,
    Member,
    Policy,
    RuleKind,
)
from app.persistence.models import (
    ClaimModel,
    CoverageRuleModel,
    LineItemModel,
    MemberModel,
    PolicyModel,
)

logger = logging.getLogger("app.seed")

DATA_DIR_DEFAULT: Path = Path(__file__).resolve().parents[2] / "data"


class SeedLoadError(Exception):
    """Raised on any seed-data file, validation, or integrity failure."""


@dataclass(frozen=True)
class SeedSummary:
    """Row counts written by a successful seed load."""

    members: int
    policies: int
    rules: int
    claims: int
    line_items: int


# --- Pydantic schemas (internal) ------------------------------------------

_STRICT: ConfigDict = ConfigDict(extra="forbid")


class _EmptyParams(BaseModel):
    """No-parameter rule kinds; rejects unknown keys."""

    model_config = _STRICT


class _ServiceCoveredRule(BaseModel):
    model_config = _STRICT
    id: str
    service_type: str
    kind: Literal["service_covered"]
    parameters: _EmptyParams

    def to_domain(self, policy_id: str) -> CoverageRule:
        return CoverageRule(
            id=self.id,
            policy_id=policy_id,
            service_type=self.service_type,
            kind=RuleKind.SERVICE_COVERED,
            parameters={},
        )


class _ServiceExcludedRule(BaseModel):
    model_config = _STRICT
    id: str
    service_type: str
    kind: Literal["service_excluded"]
    parameters: _EmptyParams

    def to_domain(self, policy_id: str) -> CoverageRule:
        return CoverageRule(
            id=self.id,
            policy_id=policy_id,
            service_type=self.service_type,
            kind=RuleKind.SERVICE_EXCLUDED,
            parameters={},
        )


class _PreauthRequiredRule(BaseModel):
    model_config = _STRICT
    id: str
    service_type: str
    kind: Literal["preauth_required"]
    parameters: _EmptyParams

    def to_domain(self, policy_id: str) -> CoverageRule:
        return CoverageRule(
            id=self.id,
            policy_id=policy_id,
            service_type=self.service_type,
            kind=RuleKind.PREAUTH_REQUIRED,
            parameters={},
        )


class _AnnualLimitParams(BaseModel):
    model_config = _STRICT
    cap_amount: Decimal
    period: Literal["calendar_year"]


class _AnnualLimitRule(BaseModel):
    model_config = _STRICT
    id: str
    service_type: str
    kind: Literal["annual_limit"]
    parameters: _AnnualLimitParams

    def to_domain(self, policy_id: str) -> CoverageRule:
        # Money stored as string per the seed-data decision; engine
        # parses Decimal at use-site.
        return CoverageRule(
            id=self.id,
            policy_id=policy_id,
            service_type=self.service_type,
            kind=RuleKind.ANNUAL_LIMIT,
            parameters={
                "cap_amount": str(self.parameters.cap_amount),
                "period": self.parameters.period,
            },
        )


class _CopayParams(BaseModel):
    model_config = _STRICT
    amount: Decimal


class _CopayRule(BaseModel):
    model_config = _STRICT
    id: str
    service_type: str
    kind: Literal["copay"]
    parameters: _CopayParams

    def to_domain(self, policy_id: str) -> CoverageRule:
        return CoverageRule(
            id=self.id,
            policy_id=policy_id,
            service_type=self.service_type,
            kind=RuleKind.COPAY,
            parameters={"amount": str(self.parameters.amount)},
        )


class _CoinsuranceParams(BaseModel):
    model_config = _STRICT
    member_pct: int = Field(ge=0, le=100)


class _CoinsuranceRule(BaseModel):
    model_config = _STRICT
    id: str
    service_type: str
    kind: Literal["coinsurance"]
    parameters: _CoinsuranceParams

    def to_domain(self, policy_id: str) -> CoverageRule:
        return CoverageRule(
            id=self.id,
            policy_id=policy_id,
            service_type=self.service_type,
            kind=RuleKind.COINSURANCE,
            parameters={"member_pct": self.parameters.member_pct},
        )


_RuleSeed = Annotated[
    _ServiceCoveredRule
    | _ServiceExcludedRule
    | _PreauthRequiredRule
    | _AnnualLimitRule
    | _CopayRule
    | _CoinsuranceRule,
    Field(discriminator="kind"),
]


class _MemberSeed(BaseModel):
    model_config = _STRICT
    id: str
    name: str

    def to_domain(self) -> Member:
        return Member(id=self.id, name=self.name)


class _PolicySeed(BaseModel):
    model_config = _STRICT
    id: str
    member_id: str
    name: str
    effective_date: date
    termination_date: date | None = None
    annual_deductible: Decimal
    rules: list[_RuleSeed]

    def to_domain(self) -> Policy:
        return Policy(
            id=self.id,
            member_id=self.member_id,
            name=self.name,
            effective_date=self.effective_date,
            termination_date=self.termination_date,
            annual_deductible=self.annual_deductible,
        )


class _LineItemSeed(BaseModel):
    model_config = _STRICT
    id: str
    service_type: str
    service_description: str
    charged_amount: Decimal
    preauth_ref: str | None = None

    def to_domain(self, claim_id: str) -> LineItem:
        return LineItem(
            id=self.id,
            claim_id=claim_id,
            service_type=self.service_type,
            service_description=self.service_description,
            charged_amount=self.charged_amount,
            preauth_ref=self.preauth_ref,
            status=LineItemStatus.PENDING,
        )


class _ClaimSeed(BaseModel):
    model_config = _STRICT
    id: str
    member_id: str
    provider_name: str
    service_date: date
    submitted_at: datetime
    paid_at: datetime | None = None
    line_items: list[_LineItemSeed]

    def to_domain(self) -> Claim:
        return Claim(
            id=self.id,
            member_id=self.member_id,
            provider_name=self.provider_name,
            service_date=self.service_date,
            submitted_at=self.submitted_at,
            paid_at=self.paid_at,
        )


# --- Public API ------------------------------------------------------------


def seed_if_empty(
    session: Session, *, data_dir: Path | None = None
) -> SeedSummary | None:
    """Idempotent wrapper: load seed data only when the DB has no policies.

    Returns the summary when seeding ran; `None` when skipped. Doesn't
    commit — the caller's transaction handles that.
    """
    if session.scalar(select(PolicyModel).limit(1)) is not None:
        logger.info("seed skipped: database already populated")
        return None
    return load_seed_data(session, data_dir=data_dir)


def load_seed_data(
    session: Session, *, data_dir: Path | None = None
) -> SeedSummary:
    """Validate the YAML files in `data_dir` and stage every row.

    Doesn't commit — the caller's transaction handles that. Raises
    `SeedLoadError` on any file, validation, or cross-entity failure.
    """
    directory = data_dir if data_dir is not None else DATA_DIR_DEFAULT
    logger.info("loading seed from %s", directory)

    members = _validate_file(directory / "members.yaml", _MemberSeed)
    policies = _validate_file(directory / "policies.yaml", _PolicySeed)
    claims = _validate_file(directory / "claims.yaml", _ClaimSeed)

    _check_referential_integrity(members, policies, claims)
    _check_cost_sharing_uniqueness(policies)
    _check_no_duplicate_ids(members, policies, claims)

    _insert_all(session, members, policies, claims)

    summary = SeedSummary(
        members=len(members),
        policies=len(policies),
        rules=sum(len(p.rules) for p in policies),
        claims=len(claims),
        line_items=sum(len(c.line_items) for c in claims),
    )
    logger.info(
        "seed loaded: %d members, %d policies, %d rules, %d claims, %d line items",
        summary.members,
        summary.policies,
        summary.rules,
        summary.claims,
        summary.line_items,
    )
    return summary


# --- Internals -------------------------------------------------------------

_T = TypeVar("_T", bound=BaseModel)


def _validate_file(path: Path, model: type[_T]) -> list[_T]:
    """Parse YAML at `path` and validate every entry against `model`."""
    try:
        with path.open() as f:
            raw = yaml.safe_load(f)
    except FileNotFoundError as e:
        raise SeedLoadError(f"Seed file not found: {path}") from e
    except yaml.YAMLError as e:
        raise SeedLoadError(f"Malformed YAML in {path}: {e}") from e

    if not isinstance(raw, list):
        raise SeedLoadError(
            f"Top level of {path} must be a list, got {type(raw).__name__}"
        )

    try:
        return [model.model_validate(entry) for entry in raw]
    except ValidationError as e:
        raise SeedLoadError(f"Validation failed for {path}:\n{e}") from e


def _check_referential_integrity(
    members: list[_MemberSeed],
    policies: list[_PolicySeed],
    claims: list[_ClaimSeed],
) -> None:
    member_ids = {m.id for m in members}
    for p in policies:
        if p.member_id not in member_ids:
            raise SeedLoadError(
                f"Policy {p.id} references unknown member {p.member_id}"
            )
    for c in claims:
        if c.member_id not in member_ids:
            raise SeedLoadError(
                f"Claim {c.id} references unknown member {c.member_id}"
            )


def _check_cost_sharing_uniqueness(policies: list[_PolicySeed]) -> None:
    """At most one cost-sharing rule (copay OR coinsurance, not both)
    per `(policy, service_type)`. Invariant from `docs/domain-model.md`.
    """
    cost_sharing = {"copay", "coinsurance"}
    for p in policies:
        seen: dict[str, list[tuple[str, str]]] = {}
        for r in p.rules:
            if r.kind in cost_sharing:
                seen.setdefault(r.service_type, []).append((r.id, r.kind))
        for svc, rules in seen.items():
            if len(rules) > 1:
                summary = ", ".join(f"{rid}({k})" for rid, k in rules)
                raise SeedLoadError(
                    f"Policy {p.id}: multiple cost-sharing rules on "
                    f"`{svc}` ({summary}); invariant requires at most one"
                )


def _check_no_duplicate_ids(
    members: list[_MemberSeed],
    policies: list[_PolicySeed],
    claims: list[_ClaimSeed],
) -> None:
    _assert_unique((m.id for m in members), "member")
    _assert_unique((p.id for p in policies), "policy")
    _assert_unique(
        (r.id for p in policies for r in p.rules), "coverage_rule"
    )
    _assert_unique((c.id for c in claims), "claim")
    _assert_unique(
        (li.id for c in claims for li in c.line_items), "line_item"
    )


def _assert_unique(ids: Iterable[str], entity_kind: str) -> None:
    seen: set[str] = set()
    for i in ids:
        if i in seen:
            raise SeedLoadError(f"Duplicate {entity_kind} id: {i}")
        seen.add(i)


def _insert_all(
    session: Session,
    members: list[_MemberSeed],
    policies: list[_PolicySeed],
    claims: list[_ClaimSeed],
) -> None:
    """Insert rows in dependency order, flushing between layers."""
    for m in members:
        session.add(MemberModel.from_domain(m.to_domain()))
    session.flush()

    for p in policies:
        session.add(PolicyModel.from_domain(p.to_domain()))
        for r in p.rules:
            session.add(CoverageRuleModel.from_domain(r.to_domain(p.id)))
    session.flush()

    for c in claims:
        session.add(ClaimModel.from_domain(c.to_domain()))
        for li in c.line_items:
            session.add(LineItemModel.from_domain(li.to_domain(c.id)))
    session.flush()


__all__ = (
    "DATA_DIR_DEFAULT",
    "SeedLoadError",
    "SeedSummary",
    "load_seed_data",
    "seed_if_empty",
)
