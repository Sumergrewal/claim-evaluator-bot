"""Tests for the startup batch (`adjudicate_all_pending`).

What this layer must guarantee:

- Every pending line item is adjudicated on the first run.
- The order matches `(claim.submitted_at, line_item.id)` so the
  engine's YTD accumulators see chronologically-correct totals.
- Already-decided line items are skipped — re-adjudication is a
  reviewer path, not the engine's path.
- A second run is a no-op (returns `[]`, writes nothing).
- Against the real seed YAML, every seeded line item — including
  the ones whose claim already has `paid_at` set — ends with a
  current decision row before the function returns.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.adjudication.startup import adjudicate_all_pending
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
from app.persistence.seed import seed_if_empty

# --- helpers --------------------------------------------------------------


def _seed_member_policy_and_consult_rules(session: Session) -> None:
    """Member 'M1' on a $500-deductible policy that covers consults with a $25 copay."""
    session.add(MemberModel.from_domain(Member(id="M1", name="Alice")))
    session.add(
        PolicyModel.from_domain(
            Policy(
                id="P1",
                member_id="M1",
                name="BasicPlan",
                effective_date=date(2026, 1, 1),
                termination_date=date(2026, 12, 31),
                annual_deductible=Decimal("500.00"),
            )
        )
    )
    session.add(
        CoverageRuleModel.from_domain(
            CoverageRule(
                id="R-COV",
                policy_id="P1",
                service_type="consult",
                kind=RuleKind.SERVICE_COVERED,
                parameters={},
            )
        )
    )
    session.add(
        CoverageRuleModel.from_domain(
            CoverageRule(
                id="R-COPAY",
                policy_id="P1",
                service_type="consult",
                kind=RuleKind.COPAY,
                parameters={"amount": "25.00"},
            )
        )
    )
    session.flush()


def _add_pending_consult(
    session: Session,
    *,
    cid: str,
    lid: str,
    service_date: date,
    submitted_at: datetime,
    charged: Decimal,
) -> None:
    session.add(
        ClaimModel.from_domain(
            Claim(
                id=cid,
                member_id="M1",
                provider_name="x",
                service_date=service_date,
                submitted_at=submitted_at,
                paid_at=None,
            )
        )
    )
    session.flush()
    session.add(
        LineItemModel.from_domain(
            LineItem(
                id=lid,
                claim_id=cid,
                service_type="consult",
                service_description="x",
                charged_amount=charged,
                preauth_ref=None,
                status=LineItemStatus.PENDING,
            )
        )
    )


# --- basic behaviour ------------------------------------------------------


def test_adjudicate_all_pending_returns_empty_on_clean_db(
    session: Session,
) -> None:
    assert adjudicate_all_pending(session) == []


def test_adjudicate_all_pending_decides_every_pending_line_item(
    session: Session,
) -> None:
    _seed_member_policy_and_consult_rules(session)
    _add_pending_consult(
        session,
        cid="C1", lid="L1",
        service_date=date(2026, 2, 1),
        submitted_at=datetime(2026, 2, 1, 9, 0),
        charged=Decimal("100.00"),
    )
    _add_pending_consult(
        session,
        cid="C2", lid="L2",
        service_date=date(2026, 3, 1),
        submitted_at=datetime(2026, 3, 1, 9, 0),
        charged=Decimal("100.00"),
    )
    session.flush()

    decided = adjudicate_all_pending(session)

    assert decided == ["L1", "L2"]
    for lid in ("L1", "L2"):
        current = repo.get_current_decision_for_line_item(session, lid)
        assert current is not None
        # Both fell inside the $500 deductible, so both are member-pay.
        assert current.outcome is DecisionOutcome.APPROVED
        assert current.payable_amount == Decimal("0.00")
    # Statuses were flipped from PENDING.
    assert session.get(LineItemModel, "L1").status is LineItemStatus.APPROVED
    assert session.get(LineItemModel, "L2").status is LineItemStatus.APPROVED


def test_adjudicate_all_pending_is_a_noop_on_second_run(
    session: Session,
) -> None:
    _seed_member_policy_and_consult_rules(session)
    _add_pending_consult(
        session,
        cid="C1", lid="L1",
        service_date=date(2026, 2, 1),
        submitted_at=datetime(2026, 2, 1, 9, 0),
        charged=Decimal("100.00"),
    )
    session.flush()

    first = adjudicate_all_pending(session)
    second = adjudicate_all_pending(session)

    assert first == ["L1"]
    assert second == []
    # Exactly one decision row exists — no superseder.
    history = repo.list_decisions_for_line_item(session, "L1")
    assert len(history) == 1


def test_adjudicate_all_pending_skips_already_decided_items(
    session: Session,
) -> None:
    """Line items that aren't PENDING (e.g. left over from a prior run
    where the engine already decided them) must not be reprocessed.
    """
    _seed_member_policy_and_consult_rules(session)
    _add_pending_consult(
        session,
        cid="C1", lid="L1",
        service_date=date(2026, 2, 1),
        submitted_at=datetime(2026, 2, 1, 9, 0),
        charged=Decimal("100.00"),
    )
    session.flush()
    # Pretend a prior batch already decided L1: flip its status.
    session.get(LineItemModel, "L1").status = LineItemStatus.APPROVED
    session.flush()

    _add_pending_consult(
        session,
        cid="C2", lid="L2",
        service_date=date(2026, 3, 1),
        submitted_at=datetime(2026, 3, 1, 9, 0),
        charged=Decimal("100.00"),
    )
    session.flush()

    decided = adjudicate_all_pending(session)
    assert decided == ["L2"]
    # L1 still has no decision row (we didn't write one), and L2 does.
    assert repo.get_current_decision_for_line_item(session, "L1") is None
    assert repo.get_current_decision_for_line_item(session, "L2") is not None


# --- ordering matters for accumulator math -------------------------------


def test_adjudicate_all_pending_walks_in_submitted_at_order(
    session: Session,
) -> None:
    """Two claims for the same member; the earlier-submitted one uses
    the whole $500 deductible. The later one — *if* processed second —
    pays $25 copay only ($500 charged - $0 deductible-remaining = $500
    coverable, then $25 copay). If they were processed in the wrong
    order, the cheaper ($100) one would consume only $100 of deductible
    and the $500 one would see $400 remaining, giving a different
    split.
    """
    _seed_member_policy_and_consult_rules(session)
    # Insert in REVERSE submitted_at order to prove the repo's
    # ordering, not insertion order, drives the batch.
    _add_pending_consult(
        session,
        cid="C-LATE", lid="L-LATE",
        service_date=date(2026, 4, 1),
        submitted_at=datetime(2026, 4, 1, 9, 0),
        charged=Decimal("500.00"),
    )
    _add_pending_consult(
        session,
        cid="C-EARLY", lid="L-EARLY",
        service_date=date(2026, 2, 1),
        submitted_at=datetime(2026, 2, 1, 9, 0),
        charged=Decimal("500.00"),
    )
    session.flush()

    decided = adjudicate_all_pending(session)

    assert decided == ["L-EARLY", "L-LATE"]

    early = repo.get_current_decision_for_line_item(session, "L-EARLY")
    late = repo.get_current_decision_for_line_item(session, "L-LATE")
    assert early is not None
    assert late is not None

    # Early hit the deductible; member pays full $500, plan pays $0.
    assert early.payable_amount == Decimal("0.00")
    assert early.member_responsibility == Decimal("500.00")
    assert early.deductible_applied == Decimal("500.00")

    # Late saw the deductible exhausted; only the $25 copay falls on
    # the member. Plan pays $475.
    assert late.payable_amount == Decimal("475.00")
    assert late.member_responsibility == Decimal("25.00")
    assert late.deductible_applied == Decimal("0.00")


# --- integration with the real seed --------------------------------------


def test_adjudicate_all_pending_against_real_seed_decides_every_line_item(
    session: Session,
) -> None:
    """Real seed integration: load `data/*.yaml`, run the batch,
    assert no PENDING line items remain — including the ones on
    claims that already have `paid_at` set (C-BOB-001, C-CAROL-001).
    """
    seed_if_empty(session)
    session.flush()

    pending_before = repo.list_pending_line_item_ids(session)
    assert len(pending_before) > 0, "seed should plant pending line items"

    decided = adjudicate_all_pending(session)

    assert set(decided) == set(pending_before)
    assert repo.list_pending_line_item_ids(session) == []
    # Every decided line item has a current decision row.
    for lid in decided:
        assert repo.get_current_decision_for_line_item(session, lid) is not None


def test_adjudicate_all_pending_resolves_paid_at_claims(
    session: Session,
) -> None:
    """Specifically: the two seeded claims that carry `paid_at`
    (C-BOB-001 and C-CAROL-001 per `data/claims.yaml`) end up with
    every line item decided, so the (paid_at set, line items pending)
    half-decided state the seed plants is gone by the time the
    function returns.
    """
    seed_if_empty(session)
    session.flush()

    adjudicate_all_pending(session)

    for paid_claim_id in ("C-BOB-001", "C-CAROL-001"):
        line_items = repo.list_line_items_for_claim(session, paid_claim_id)
        assert line_items, f"{paid_claim_id} should have line items"
        for li in line_items:
            assert li.status is not LineItemStatus.PENDING, (
                f"{li.id} on paid claim {paid_claim_id} still pending"
            )
            current = repo.get_current_decision_for_line_item(session, li.id)
            assert current is not None
