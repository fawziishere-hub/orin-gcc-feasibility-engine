"""Domain models: GCC hiring rules + candidate feasibility simulations.

All money is stored in USD. Rule values are illustrative planning defaults
(legal minima change — refresh them from the civil-service/ministry source
before quoting a client).
"""
from django.db import models


class Entity(models.TextChoices):
    UAE_DIFC = "UAE_DIFC", "UAE — DIFC (Dubai)"
    UAE_MAINLAND = "UAE_MAINLAND", "UAE — Mainland (MoHRE)"
    KSA_RIYADH = "KSA_RIYADH", "Saudi Arabia — Riyadh"
    QATAR_DOHA = "QATAR_DOHA", "Qatar — Doha"
    CERCLI_EOR_REMOTE = "CERCLI_EOR_REMOTE", "Cercli EOR (remote / no local entity)"


class Route(models.TextChoices):
    LOCAL_TRANSFER = "LOCAL_TRANSFER", "Local transfer (existing visa)"
    NEW_WORK_PERMIT = "NEW_WORK_PERMIT", "New work permit / sponsorship"
    CERCLI_EOR = "CERCLI_EOR", "Cercli employer of record"


class QuotaRisk(models.TextChoices):
    LOW = "LOW", "Low"
    MEDIUM = "MEDIUM", "Medium"
    HIGH = "HIGH", "High"


class CountryComplianceRule(models.Model):
    """Deterministic hiring facts for one jurisdiction. No LLM touches these."""

    entity_code = models.CharField(max_length=32, choices=Entity.choices, unique=True)
    country = models.CharField(max_length=64)
    city = models.CharField(max_length=64)
    currency = models.CharField(max_length=3, default="USD")

    visa_permit_fee_usd = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    medical_id_fee_usd = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    employer_social_insurance_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="Employer GOSI / DEWS / social-insurance rate on monthly base.",
    )
    gratuity_monthly_accrual_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="End-of-service accrual as % of monthly base.",
    )
    eor_management_fee_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="Cercli EOR service fee as % of monthly base (EOR routes only).",
    )
    avg_onboarding_days = models.PositiveSmallIntegerField(default=30)
    quota_risk_level = models.CharField(
        max_length=8, choices=QuotaRisk.choices, default=QuotaRisk.MEDIUM
    )
    quota_risk_note = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["entity_code"]

    def __str__(self) -> str:
        return f"{self.get_entity_code_display()} ({self.entity_code})"


class CandidateSimulation(models.Model):
    """One enriched candidate → one feasible route → one costed offer."""

    batch_key = models.CharField(
        max_length=128, unique=True,
        help_text="Idempotency key: batch_id + hash(raw_profile + target_entity).",
    )
    batch_id = models.CharField(max_length=64, db_index=True)
    raw_profile = models.TextField()
    target_entity = models.CharField(max_length=32, choices=Entity.choices)

    parsed = models.JSONField(default=dict)
    route = models.CharField(max_length=24, choices=Route.choices)
    cost_breakdown = models.JSONField(default=dict)

    monthly_employer_cost_usd = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    upfront_cost_usd = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    time_to_start_days = models.PositiveSmallIntegerField(default=0)

    outreach_en = models.TextField(blank=True)
    outreach_ar = models.TextField(blank=True)
    llm_source = models.CharField(max_length=32, default="heuristic-mock")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        name = self.parsed.get("full_name") or "Candidate"
        return f"{name} → {self.target_entity} [{self.route}]"
