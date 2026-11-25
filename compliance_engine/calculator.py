"""Deterministic GCC feasibility math.

Everything money- or deadline-related lives here as plain Python. The LLM is
only ever allowed to *read* a profile; it never produces a number that reaches
a client. Given the same rule row + profile facts, this module is pure and
side-effect free, which is what makes it unit-testable and auditable.
"""
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from .models import CountryComplianceRule, Entity, QuotaRisk, Route

ZERO = Decimal("0.00")
ROUTE_DAY_FACTOR = {
    # Existing-visa transfers skip the ministry/permit queue almost entirely.
    Route.LOCAL_TRANSFER: Decimal("0.4"),
    Route.NEW_WORK_PERMIT: Decimal("1.0"),
}
DEFAULT_EOR_DAYS = 10


def money(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _pct(base: Decimal, pct: Any) -> Decimal:
    return money(base * Decimal(str(pct)) / Decimal("100"))


def resolve_rule(entity_code: str) -> CountryComplianceRule:
    """Fetch a rule row, raising a clear error rather than guessing defaults."""
    try:
        return CountryComplianceRule.objects.get(entity_code=entity_code)
    except CountryComplianceRule.DoesNotExist as exc:
        raise LookupError(
            f"No compliance rule for '{entity_code}'. Run: manage.py seed_gcc_rules"
        ) from exc


def select_route(
    rule: CountryComplianceRule,
    parsed: dict[str, Any],
    requested: str | None = None,
) -> tuple[str, list[str]]:
    """Pick LOCAL_TRANSFER / NEW_WORK_PERMIT / CERCLI_EOR from parsed facts.

    Order of precedence: explicit request → EOR-only entity → local transfer →
    new permit abroad, downgraded to EOR when the jurisdiction blocks quotas.
    """
    reasons: list[str] = []

    if requested:
        if requested not in Route.values:
            raise ValueError(f"Unknown route '{requested}'. Expected one of {Route.values}.")
        if requested == Route.LOCAL_TRANSFER and not parsed.get("in_target_country"):
            raise ValueError("LOCAL_TRANSFER requires the candidate to already be in-country.")
        return requested, [f"Route explicitly requested by recruiter: {requested}."]

    if rule.entity_code == Entity.CERCLI_EOR_REMOTE:
        return Route.CERCLI_EOR, [
            "Target entity is Cercli EOR — no local entity or work permit is needed."
        ]

    in_country = bool(parsed.get("in_target_country"))
    transferable = bool(parsed.get("transferable_visa"))

    if in_country and transferable:
        return Route.LOCAL_TRANSFER, [
            f"Candidate already holds a transferable permit in {rule.city}.",
            "No new ministry quota is consumed.",
        ]
    if in_country:
        return Route.NEW_WORK_PERMIT, [
            f"Candidate is in {rule.city} but the current permit is not transferable.",
            "A new work permit must be sponsored by the entity.",
        ]

    if rule.quota_risk_level == QuotaRisk.HIGH:
        return Route.CERCLI_EOR, [
            f"Candidate must relocate to {rule.city}, and the entity's quota is high-risk.",
            "Cercli EOR is the fastest compliant path while the quota clears.",
        ]

    reasons.append(f"Candidate must relocate to {rule.city}; entity can sponsor a new permit.")
    if rule.quota_risk_level == QuotaRisk.MEDIUM:
        reasons.append(f"Watch the quota band: {rule.quota_risk_note}")
    return Route.NEW_WORK_PERMIT, reasons


def calculate(
    rule: CountryComplianceRule,
    eor_rule: CountryComplianceRule,
    monthly_base_usd: Any,
    route: str,
) -> dict[str, Any]:
    """Build the monthly + upfront employer cost breakdown for one route."""
    base = money(monthly_base_usd)
    if base <= ZERO:
        raise ValueError("monthly_base_usd must be positive.")

    if route == Route.CERCLI_EOR:
        pricing = eor_rule
    else:
        pricing = rule

    employer_social = _pct(base, pricing.employer_social_insurance_pct)
    gratuity = _pct(base, pricing.gratuity_monthly_accrual_pct)
    eor_fee = _pct(base, pricing.eor_management_fee_pct) if route == Route.CERCLI_EOR else ZERO
    monthly_total = money(base + employer_social + gratuity + eor_fee)

    if route == Route.NEW_WORK_PERMIT:
        visa_fee = money(rule.visa_permit_fee_usd)
        medical_fee = money(rule.medical_id_fee_usd)
    elif route == Route.LOCAL_TRANSFER:
        visa_fee = ZERO  # no new permit; residency is transferred
        medical_fee = money(rule.medical_id_fee_usd)
    else:
        visa_fee = ZERO  # bundled into the EOR fee
        medical_fee = ZERO
    upfront_total = money(visa_fee + medical_fee)

    if route == Route.CERCLI_EOR:
        days = DEFAULT_EOR_DAYS
    else:
        days = max(1, int(round(rule.avg_onboarding_days * ROUTE_DAY_FACTOR[route])))

    return {
        "route": route,
        "target_entity": rule.entity_code,
        "pricing_entity": pricing.entity_code,
        "monthly": {
            "base_salary_usd": str(base),
            "employer_social_insurance_usd": str(employer_social),
            "gratuity_accrual_usd": str(gratuity),
            "eor_management_fee_usd": str(eor_fee),
            "total_usd": str(monthly_total),
            "employer_markup_pct": str(
                money((monthly_total - base) / base * Decimal("100"))
            ),
        },
        "upfront": {
            "visa_permit_usd": str(visa_fee),
            "medical_id_usd": str(medical_fee),
            "eor_setup_usd": "0.00",
            "total_usd": str(upfront_total),
        },
        "annual_employer_cost_usd": str(money(monthly_total * 12 + upfront_total)),
        "time_to_start_days": days,
    }
