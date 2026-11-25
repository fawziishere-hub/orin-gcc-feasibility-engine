"""Seed the five deterministic GCC hiring rule rows (idempotent)."""
from django.core.management.base import BaseCommand

from compliance_engine.models import CountryComplianceRule, Entity, QuotaRisk

RULES = [
    {
        "entity_code": Entity.UAE_DIFC,
        "country": "United Arab Emirates",
        "city": "Dubai (DIFC)",
        "visa_permit_fee_usd": 1200,
        "medical_id_fee_usd": 550,
        "employer_social_insurance_pct": 5.83,
        "gratuity_monthly_accrual_pct": 5.83,
        "eor_management_fee_pct": 0,
        "avg_onboarding_days": 30,
        "quota_risk_level": QuotaRisk.LOW,
        "quota_risk_note": "DIFC entities carry no Emiratisation quota, but DEWS workplace "
                           "savings (≈5.83% employer) applies to every employee.",
        "notes": "DIFC employment law; 21 days' gratuity per year of basic for the first 5 years.",
    },
    {
        "entity_code": Entity.UAE_MAINLAND,
        "country": "United Arab Emirates",
        "city": "Dubai (Mainland)",
        "visa_permit_fee_usd": 1400,
        "medical_id_fee_usd": 600,
        "employer_social_insurance_pct": 0,
        "gratuity_monthly_accrual_pct": 5.83,
        "eor_management_fee_pct": 0,
        "avg_onboarding_days": 35,
        "quota_risk_level": QuotaRisk.MEDIUM,
        "quota_risk_note": "MoHRE quota is tied to the Emiratisation ratio; free-zone to "
                           "mainland transfers need ministry approval.",
        "notes": "No GOSI for expatriate private-sector staff; Emirati hires attract 12.5% GPSSA.",
    },
    {
        "entity_code": Entity.KSA_RIYADH,
        "country": "Saudi Arabia",
        "city": "Riyadh",
        "visa_permit_fee_usd": 900,
        "medical_id_fee_usd": 400,
        "employer_social_insurance_pct": 2.0,
        "gratuity_monthly_accrual_pct": 2.78,
        "eor_management_fee_pct": 0,
        "avg_onboarding_days": 45,
        "quota_risk_level": QuotaRisk.HIGH,
        "quota_risk_note": "Nitaqat band must stay Green; Red/Orange entities cannot issue "
                           "new expatriate visas until the Saudisation ratio improves.",
        "notes": "GOSI: 2% occupational hazard for expats (11.75% total for Saudi nationals). "
                 "Gratuity ≈ one third of a month's wage per year.",
    },
    {
        "entity_code": Entity.QATAR_DOHA,
        "country": "Qatar",
        "city": "Doha",
        "visa_permit_fee_usd": 1100,
        "medical_id_fee_usd": 450,
        "employer_social_insurance_pct": 0,
        "gratuity_monthly_accrual_pct": 4.8,
        "eor_management_fee_pct": 0,
        "avg_onboarding_days": 40,
        "quota_risk_level": QuotaRisk.MEDIUM,
        "quota_risk_note": "Labour-ministry quota is per CR activity; sponsorship transfer "
                           "requires a no-objection certificate.",
        "notes": "Three weeks' gratuity per year of service; no social insurance for expats.",
    },
    {
        "entity_code": Entity.CERCLI_EOR_REMOTE,
        "country": "Remote (Cercli entity)",
        "city": "Remote",
        "visa_permit_fee_usd": 0,
        "medical_id_fee_usd": 0,
        "employer_social_insurance_pct": 0,
        "gratuity_monthly_accrual_pct": 0,
        "eor_management_fee_pct": 12.0,
        "avg_onboarding_days": 10,
        "quota_risk_level": QuotaRisk.LOW,
        "quota_risk_note": "No local entity, visa or quota required — Cercli is the legal "
                           "employer of record.",
        "notes": "Statutory costs (gratuity, insurance, permits) bundled into the EOR fee.",
    },
]


class Command(BaseCommand):
    help = "Create or refresh the GCC compliance rules used by the feasibility engine."

    def handle(self, *args, **options):
        for payload in RULES:
            entity_code = payload["entity_code"]
            CountryComplianceRule.objects.update_or_create(
                entity_code=entity_code, defaults=payload
            )
            self.stdout.write(f"  seeded {entity_code}")
        self.stdout.write(self.style.SUCCESS(f"Seeded {len(RULES)} GCC compliance rules."))
