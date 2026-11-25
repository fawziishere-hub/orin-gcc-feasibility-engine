"""Strawberry GraphQL surface: one mutation to simulate, one query to read back."""
from __future__ import annotations

import strawberry
from strawberry.scalars import JSON

from .models import CandidateSimulation, CountryComplianceRule, Entity
from .services.pipeline import run_candidate


@strawberry.type
class MonthlyCost:
    base_salary_usd: str
    employer_social_insurance_usd: str
    gratuity_accrual_usd: str
    eor_management_fee_usd: str
    total_usd: str
    employer_markup_pct: str


@strawberry.type
class UpfrontCost:
    visa_permit_usd: str
    medical_id_usd: str
    eor_setup_usd: str
    total_usd: str


@strawberry.type
class Simulation:
    id: strawberry.ID
    batch_id: str
    raw_profile: str
    target_entity: str
    route: str
    parsed: JSON
    monthly: MonthlyCost
    upfront: UpfrontCost
    annual_employer_cost_usd: str
    time_to_start_days: int
    reasons: list[str]
    quota_risk_level: str
    quota_risk_note: str
    outreach_en: str
    outreach_ar: str
    llm_source: str
    created_at: str

    @classmethod
    def from_model(cls, sim: CandidateSimulation) -> "Simulation":
        cost = sim.cost_breakdown or {}
        monthly = cost.get("monthly", {})
        upfront = cost.get("upfront", {})
        return cls(
            id=str(sim.pk),
            batch_id=sim.batch_id,
            raw_profile=sim.raw_profile,
            target_entity=sim.target_entity,
            route=sim.route,
            parsed=sim.parsed,
            monthly=MonthlyCost(**monthly),
            upfront=UpfrontCost(**upfront),
            annual_employer_cost_usd=cost.get("annual_employer_cost_usd", "0.00"),
            time_to_start_days=sim.time_to_start_days,
            reasons=cost.get("reasons", []),
            quota_risk_level=cost.get("quota_risk_level", ""),
            quota_risk_note=cost.get("quota_risk_note", ""),
            outreach_en=sim.outreach_en,
            outreach_ar=sim.outreach_ar,
            llm_source=sim.llm_source,
            created_at=sim.created_at.isoformat(),
        )


@strawberry.type
class ComplianceRule:
    entity_code: str
    country: str
    city: str
    visa_permit_fee_usd: str
    medical_id_fee_usd: str
    employer_social_insurance_pct: str
    gratuity_monthly_accrual_pct: str
    eor_management_fee_pct: str
    avg_onboarding_days: int
    quota_risk_level: str
    quota_risk_note: str

    @classmethod
    def from_model(cls, rule: CountryComplianceRule) -> "ComplianceRule":
        return cls(
            entity_code=rule.entity_code,
            country=rule.country,
            city=rule.city,
            visa_permit_fee_usd=str(rule.visa_permit_fee_usd),
            medical_id_fee_usd=str(rule.medical_id_fee_usd),
            employer_social_insurance_pct=str(rule.employer_social_insurance_pct),
            gratuity_monthly_accrual_pct=str(rule.gratuity_monthly_accrual_pct),
            eor_management_fee_pct=str(rule.eor_management_fee_pct),
            avg_onboarding_days=rule.avg_onboarding_days,
            quota_risk_level=rule.quota_risk_level,
            quota_risk_note=rule.quota_risk_note,
        )


@strawberry.type
class Query:
    @strawberry.field
    def simulations(self, limit: int = 10) -> list[Simulation]:
        return [Simulation.from_model(s) for s in CandidateSimulation.objects.all()[:limit]]

    @strawberry.field
    def compliance_rules(self) -> list[ComplianceRule]:
        return [ComplianceRule.from_model(r) for r in CountryComplianceRule.objects.all()]


@strawberry.type
class Mutation:
    @strawberry.mutation(name="simulateCandidateCompliance")
    def simulate_candidate_compliance(
        self, raw_profile: str, target_entity: str, refresh: bool = False
    ) -> Simulation:
        if target_entity not in Entity.values:
            raise ValueError(f"Unknown target_entity. Expected one of {Entity.values}.")
        if not raw_profile or not raw_profile.strip():
            raise ValueError("Profile text is empty — paste a candidate profile first.")
        simulation = run_candidate(raw_profile, target_entity, refresh=refresh)
        return Simulation.from_model(simulation)


schema = strawberry.Schema(query=Query, mutation=Mutation)
