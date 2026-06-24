"""Human-readable descriptions of coverage rules for API / UI tooltips."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.domain.entities import CoverageRule, RuleKind


def _service_label(service_type: str) -> str:
    return service_type.replace("_", " ")


def describe_coverage_rule(rule: CoverageRule, policy_name: str) -> str:
    """One-line explanation of what a coverage rule does."""
    service = _service_label(rule.service_type)
    params: dict[str, Any] = rule.parameters

    match rule.kind:
        case RuleKind.SERVICE_COVERED:
            return (
                f"{policy_name}: {service} is covered — the plan may pay "
                f"for this service when other rules pass."
            )
        case RuleKind.SERVICE_EXCLUDED:
            return (
                f"{policy_name}: {service} is explicitly excluded. "
                f"Claims for this service are denied at the coverage phase."
            )
        case RuleKind.PREAUTH_REQUIRED:
            return (
                f"{policy_name}: {service} requires prior authorization. "
                f"The line item must include a preauth reference or it goes "
                f"to needs review."
            )
        case RuleKind.ANNUAL_LIMIT:
            cap = params.get("cap_amount", "?")
            period = str(params.get("period", "calendar_year")).replace("_", " ")
            return (
                f"{policy_name}: plan-paid total for {service} is capped at "
                f"${cap} per {period}. Amounts over the cap are member-paid."
            )
        case RuleKind.COPAY:
            amount = params.get("amount", "?")
            return (
                f"{policy_name}: flat ${amount} copay per visit for {service} "
                f"(member cost-sharing after deductible and limits)."
            )
        case RuleKind.COINSURANCE:
            pct = params.get("member_pct", "?")
            return (
                f"{policy_name}: member pays {pct}% of the coverable amount "
                f"for {service} (after deductible and limits)."
            )
        case _:
            return f"{policy_name}: {rule.kind.value} rule for {service}."


def format_rule_parameters(rule: CoverageRule) -> str:
    """Compact parameter summary for tooltip detail line."""
    if not rule.parameters:
        return "No parameters"
    parts: list[str] = []
    for key, value in sorted(rule.parameters.items()):
        if isinstance(value, Decimal):
            parts.append(f"{key}={value}")
        else:
            parts.append(f"{key}={value!r}")
    return ", ".join(parts)
