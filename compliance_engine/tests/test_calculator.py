"""Deterministic math tests — no DB, no network, no LLM."""
from decimal import Decimal

import pytest

from compliance_engine.calculator import calculate, select_route
from compliance_engine.models import CountryComplianceRule, Entity, QuotaRisk, Route


def rule(entity_code, *, visa=1400, medical=600, social="5.83", gratuity="5.83",
         eor_fee="0", days=30, risk=QuotaRisk.LOW):
    """Unsaved model instance — keeps these tests pure."""
    return CountryComplianceRule(
        entity_code=entity_code,
        country="United Arab Emirates",
        city="Dubai",
        visa_permit_fee_usd=Decimal(str(visa)),
        medical_id_fee_usd=Decimal(str(medical)),
        employer_social_insurance_pct=Decimal(str(social)),
        gratuity_monthly_accrual_pct=Decimal(str(gratuity)),
        eor_management_fee_pct=Decimal(str(eor_fee)),
        avg_onboarding_days=days,
        quota_risk_level=risk,
        quota_risk_note="Band applies.",
    )


EOR_RULE = rule(
    Entity.CERCLI_EOR_REMOTE, visa=0, medical=0, social="0",
    gratuity="0", eor_fee="12", days=10,
)


def test_local_transfer_skips_permit_fee_and_compresses_timeline():
    dubai = rule(Entity.UAE_DIFC, days=30)
    parsed = {"in_target_country": True, "transferable_visa": True}

    route, reasons = select_route(dubai, parsed)
    cost = calculate(dubai, EOR_RULE, "10000", route)

    assert route == Route.LOCAL_TRANSFER
    assert cost["upfront"]["visa_permit_usd"] == "0.00"
    assert cost["upfront"]["medical_id_usd"] == "600.00"
    assert cost["upfront"]["total_usd"] == "600.00"
    assert cost["time_to_start_days"] == 12  # 40% of a 30-day onboarding
    assert cost["monthly"]["total_usd"] == "11166.00"  # 10000 + 583 + 583
    assert reasons


def test_relocation_sponsors_new_permit_with_full_upfront():
    dubai = rule(Entity.UAE_DIFC, days=35)
    parsed = {"in_target_country": False, "transferable_visa": False}

    route, _ = select_route(dubai, parsed)
    cost = calculate(dubai, EOR_RULE, "10000", route)

    assert route == Route.NEW_WORK_PERMIT
    assert cost["upfront"]["visa_permit_usd"] == "1400.00"
    assert cost["upfront"]["total_usd"] == "2000.00"
    assert cost["time_to_start_days"] == 35
    assert cost["monthly"]["total_usd"] == "11166.00"


def test_high_quota_risk_abroad_falls_back_to_eor():
    riyadh = rule(Entity.KSA_RIYADH, social="2.00", gratuity="2.78", risk=QuotaRisk.HIGH)
    parsed = {"in_target_country": False, "transferable_visa": False}

    route, reasons = select_route(riyadh, parsed)
    cost = calculate(riyadh, EOR_RULE, "10000", route)

    assert route == Route.CERCLI_EOR
    assert cost["pricing_entity"] == Entity.CERCLI_EOR_REMOTE
    assert cost["upfront"]["total_usd"] == "0.00"  # permits bundled into the EOR fee
    assert cost["monthly"]["eor_management_fee_usd"] == "1200.00"
    assert cost["monthly"]["total_usd"] == "11200.00"
    assert cost["time_to_start_days"] == 10
    assert any("high-risk" in reason for reason in reasons)


def test_eor_entity_always_routes_to_eor_even_when_in_country():
    remote = rule(Entity.CERCLI_EOR_REMOTE, visa=0, medical=0, social="0",
                  gratuity="0", eor_fee="12", days=10)
    parsed = {"in_target_country": True, "transferable_visa": True}

    route, _ = select_route(remote, parsed)

    assert route == Route.CERCLI_EOR


def test_explicit_request_is_honoured_but_validated():
    dubai = rule(Entity.UAE_DIFC)
    abroad = {"in_target_country": False, "transferable_visa": False}

    route, _ = select_route(dubai, abroad, requested=Route.CERCLI_EOR)
    assert route == Route.CERCLI_EOR

    with pytest.raises(ValueError, match="requires the candidate to already be in-country"):
        select_route(dubai, abroad, requested=Route.LOCAL_TRANSFER)

    with pytest.raises(ValueError, match="Unknown route"):
        select_route(dubai, abroad, requested="MOON_BASE")


def test_currency_rounding_and_non_positive_base():
    dubai = rule(Entity.UAE_DIFC, social="5.83", gratuity="5.83")
    cost = calculate(dubai, EOR_RULE, "8713.41", Route.NEW_WORK_PERMIT)

    # 8713.41 * 5.83% = 507.9917... → half-up to 507.99 each
    assert cost["monthly"]["employer_social_insurance_usd"] == "507.99"
    assert cost["monthly"]["gratuity_accrual_usd"] == "507.99"
    assert cost["monthly"]["total_usd"] == "9729.39"
    assert cost["annual_employer_cost_usd"] == "118752.68"  # 9729.39*12 + 2000

    with pytest.raises(ValueError, match="must be positive"):
        calculate(dubai, EOR_RULE, "0", Route.NEW_WORK_PERMIT)
