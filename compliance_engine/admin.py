from django.contrib import admin

from .models import CandidateSimulation, CountryComplianceRule


@admin.register(CountryComplianceRule)
class CountryComplianceRuleAdmin(admin.ModelAdmin):
    list_display = ("entity_code", "city", "avg_onboarding_days", "quota_risk_level", "updated_at")
    list_filter = ("quota_risk_level",)


@admin.register(CandidateSimulation)
class CandidateSimulationAdmin(admin.ModelAdmin):
    list_display = ("batch_id", "target_entity", "route", "monthly_employer_cost_usd", "created_at")
    list_filter = ("route", "target_entity")
    search_fields = ("raw_profile", "batch_id")
    readonly_fields = ("batch_key", "parsed", "cost_breakdown")
