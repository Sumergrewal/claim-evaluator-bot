"""Tests for the engine's value types and the money helper.

Pure tests — no DB, no HTTP. The engine pipeline (next module) leans
on these invariants, so any drift here should fail loud before
anything downstream sees it.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.adjudication.types import (
    EngineResult,
    ExplanationStep,
    PhaseName,
    StepResult,
    quantize_money,
)
from app.domain.entities import DecisionOutcome

# --- quantize_money: banker's rounding ------------------------------------


def test_quantize_money_rounds_half_to_even_down_at_zero() -> None:
    # 0.005 is the canonical midpoint case; banker's picks the even
    # neighbour (0.00, last digit 0) over the odd one (0.01).
    assert quantize_money(Decimal("0.005")) == Decimal("0.00")


def test_quantize_money_rounds_half_to_even_up_at_two_cents() -> None:
    # 0.015 midpoint; even neighbour is 0.02.
    assert quantize_money(Decimal("0.015")) == Decimal("0.02")


def test_quantize_money_keeps_exact_two_place_values_unchanged() -> None:
    assert quantize_money(Decimal("12.34")) == Decimal("12.34")


def test_quantize_money_rounds_extra_precision_normally_when_not_a_midpoint() -> None:
    # 100.456 is not a midpoint; the next digit (6) breaks the tie up.
    assert quantize_money(Decimal("100.456")) == Decimal("100.46")


# --- ExplanationStep.to_json ----------------------------------------------


def test_explanation_step_serialises_minimal_shape_with_null_rule_id() -> None:
    step = ExplanationStep(
        phase=PhaseName.ELIGIBILITY,
        result=StepResult.PASS,
        note="Policy active on service_date",
    )
    assert step.to_json() == {
        "phase": "eligibility",
        "rule_id": None,
        "result": "pass",
        "note": "Policy active on service_date",
    }


def test_explanation_step_emits_amount_as_quoted_string_when_present() -> None:
    step = ExplanationStep(
        phase=PhaseName.DEDUCTIBLE,
        result=StepResult.APPLIED,
        note="applied remaining $30 of annual deductible",
        amount=Decimal("30.00"),
    )
    payload = step.to_json()
    assert payload["amount"] == "30.00"
    assert payload["result"] == "applied"


def test_explanation_step_omits_terminating_key_when_false() -> None:
    step = ExplanationStep(
        phase=PhaseName.COVERAGE,
        result=StepResult.PASS,
        note="covered",
        rule_id="R-1",
    )
    assert "terminating" not in step.to_json()


def test_explanation_step_emits_terminating_true_on_fail() -> None:
    step = ExplanationStep(
        phase=PhaseName.COVERAGE,
        result=StepResult.FAIL,
        note="bariatric_surgery is excluded",
        rule_id="R-BASIC-009",
        terminating=True,
    )
    assert step.to_json()["terminating"] is True


def test_explanation_step_quantizes_amount_using_bankers_rounding() -> None:
    # Coinsurance math frequently produces three-decimal intermediates;
    # the step's serialiser is the chokepoint that rounds them.
    step = ExplanationStep(
        phase=PhaseName.COST_SHARING,
        result=StepResult.APPLIED,
        note="20% coinsurance",
        amount=Decimal("16.005"),
    )
    assert step.to_json()["amount"] == "16.00"


# --- EngineResult: ledger invariant ---------------------------------------


def test_engine_result_rejects_amounts_that_do_not_sum_to_charged() -> None:
    with pytest.raises(ValueError, match="must equal charged_amount"):
        EngineResult(
            outcome=DecisionOutcome.APPROVED,
            charged_amount=Decimal("100.00"),
            payable_amount=Decimal("70.00"),
            member_responsibility=Decimal("20.00"),
            steps=(),
            narrative="x",
        )


def test_engine_result_rejects_negative_payable_amount() -> None:
    with pytest.raises(ValueError, match="payable_amount must be non-negative"):
        EngineResult(
            outcome=DecisionOutcome.APPROVED,
            charged_amount=Decimal("100.00"),
            payable_amount=Decimal("-1.00"),
            member_responsibility=Decimal("101.00"),
            steps=(),
            narrative="x",
        )


def test_engine_result_rejects_negative_deductible_applied() -> None:
    with pytest.raises(ValueError, match="deductible_applied must be non-negative"):
        EngineResult(
            outcome=DecisionOutcome.APPROVED,
            charged_amount=Decimal("100.00"),
            payable_amount=Decimal("80.00"),
            member_responsibility=Decimal("20.00"),
            steps=(),
            narrative="x",
            deductible_applied=Decimal("-0.01"),
        )


def test_engine_result_deductible_applied_defaults_to_zero() -> None:
    r = EngineResult(
        outcome=DecisionOutcome.DENIED,
        charged_amount=Decimal("100.00"),
        payable_amount=Decimal("0.00"),
        member_responsibility=Decimal("100.00"),
        steps=(),
        narrative="Denied: x.",
    )
    assert r.deductible_applied == Decimal("0.00")


def test_engine_result_accepts_balanced_amounts() -> None:
    r = EngineResult(
        outcome=DecisionOutcome.APPROVED,
        charged_amount=Decimal("100.00"),
        payable_amount=Decimal("75.00"),
        member_responsibility=Decimal("25.00"),
        steps=(),
        narrative="Plan pays $75 of $100 charged.",
    )
    assert r.outcome is DecisionOutcome.APPROVED


def test_engine_result_to_explanation_json_matches_documented_shape() -> None:
    steps = (
        ExplanationStep(
            phase=PhaseName.COVERAGE,
            result=StepResult.PASS,
            note="general_consultation is covered",
            rule_id="R-1",
        ),
        ExplanationStep(
            phase=PhaseName.DEDUCTIBLE,
            result=StepResult.APPLIED,
            note="applied remaining $30 deductible",
            amount=Decimal("30.00"),
        ),
        ExplanationStep(
            phase=PhaseName.COST_SHARING,
            result=StepResult.APPLIED,
            note="$25 copay",
            rule_id="R-2",
            amount=Decimal("25.00"),
        ),
    )
    r = EngineResult(
        outcome=DecisionOutcome.APPROVED,
        charged_amount=Decimal("120.00"),
        payable_amount=Decimal("65.00"),
        member_responsibility=Decimal("55.00"),
        steps=steps,
        narrative=(
            "Covered under General Consultation. Applied remaining $30 "
            "deductible and $25 visit copay. Plan pays $65 of $120 charged."
        ),
    )
    payload = r.to_explanation_json()

    assert payload["outcome"] == "approved"
    assert payload["charged_amount"] == "120.00"
    assert payload["payable_amount"] == "65.00"
    assert payload["member_responsibility"] == "55.00"
    assert payload["narrative"].startswith("Covered under General Consultation.")
    assert [s["phase"] for s in payload["steps"]] == [
        "coverage",
        "deductible",
        "cost_sharing",
    ]
    assert payload["steps"][1]["amount"] == "30.00"
    assert payload["steps"][2]["amount"] == "25.00"


def test_engine_result_denial_serialises_with_terminating_fail_step() -> None:
    steps = (
        ExplanationStep(
            phase=PhaseName.COVERAGE,
            result=StepResult.FAIL,
            note="bariatric_surgery is excluded under BASIC",
            rule_id="R-BASIC-009",
            terminating=True,
        ),
    )
    r = EngineResult(
        outcome=DecisionOutcome.DENIED,
        charged_amount=Decimal("20000.00"),
        payable_amount=Decimal("0.00"),
        member_responsibility=Decimal("20000.00"),
        steps=steps,
        narrative="Denied: bariatric_surgery is excluded under BASIC.",
    )
    payload = r.to_explanation_json()
    assert payload["outcome"] == "denied"
    assert payload["steps"][0]["terminating"] is True
    assert payload["steps"][0]["result"] == "fail"
