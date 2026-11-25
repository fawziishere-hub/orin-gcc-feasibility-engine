"""The one path every candidate walks: parse → route → cost → outreach → persist."""
from __future__ import annotations

import hashlib
from typing import Any

from ..calculator import calculate, resolve_rule, select_route
from ..models import CandidateSimulation, Entity, Route
from .llm_parser import parse_candidate

ROUTE_LABEL_EN = {
    Route.LOCAL_TRANSFER: "a local visa transfer",
    Route.NEW_WORK_PERMIT: "a newly sponsored work permit",
    Route.CERCLI_EOR: "Cercli's employer-of-record service",
}
ROUTE_LABEL_AR = {
    Route.LOCAL_TRANSFER: "نقل الكفالة داخل الدولة",
    Route.NEW_WORK_PERMIT: "إصدار تأشيرة عمل جديدة",
    Route.CERCLI_EOR: "التوظيف من خلال Cercli كصاحب عمل بديل",
}


SENIORITY_LABEL_EN = {
    "junior": "junior", "mid": "mid-level", "senior": "senior",
    "staff/principal": "staff-level", "director": "director",
}
SENIORITY_LABEL_AR = {
    "junior": "المبتدئ", "mid": "المتوسط", "senior": "الأول",
    "staff/principal": "الخبير", "director": "الإداري",
}


def build_outreach(parsed: dict[str, Any], cost: dict[str, Any], route: str) -> tuple[str, str]:
    """Deterministic bilingual copy used when the LLM does not supply its own."""
    first_name = (parsed.get("full_name") or "there").split()[0]
    city = (parsed.get("current_city") or "the region").title()
    seniority = parsed.get("seniority", "mid")
    monthly = f"{float(cost['monthly']['total_usd']):,.0f}"
    days = cost["time_to_start_days"]

    english = (
        f"Hi {first_name}, Orin reviewed your profile for the "
        f"{SENIORITY_LABEL_EN.get(seniority, seniority)} role in {city}. "
        f"The compliant route is {ROUTE_LABEL_EN[route]} — roughly ${monthly}/month on the "
        f"employer side, with a start in about {days} days. "
        "Worth a quick 20-minute call this week?"
    )
    arabic = (
        f"مرحباً {first_name}، راجع فريق Orin ملفك للمنصب "
        f"{SENIORITY_LABEL_AR.get(seniority, seniority)} في {city}. "
        f"المسار الأنسب هو {ROUTE_LABEL_AR[route]}، بتكلفة شهرية تقديرية على صاحب العمل "
        f"تبلغ {monthly} دولار أمريكي، وبدء العمل خلال {days} يوماً تقريباً. "
        "هل يناسبك مكالمة سريعة هذا الأسبوع؟"
    )
    return english, arabic


FOOTER_LABEL_EN = {
    Route.LOCAL_TRANSFER: "local visa transfer",
    Route.NEW_WORK_PERMIT: "new work permit",
    Route.CERCLI_EOR: "Cercli employer of record",
}


def compliance_footer(cost: dict[str, Any], route: str) -> tuple[str, str]:
    """One factual line appended to model-written copy. Built only from calculator output."""
    monthly = f"{float(cost['monthly']['total_usd']):,.0f}"
    days = cost["time_to_start_days"]
    english = (
        f"Route: {FOOTER_LABEL_EN[route]} · "
        f"starts in ~{days} days · ~${monthly}/month employer cost."
    )
    arabic = (
        f"المسار: {ROUTE_LABEL_AR[route]} · بدء العمل خلال {days} يوماً · "
        f"التكلفة التقديرية على صاحب العمل {monthly} دولار أمريكي شهرياً."
    )
    return english, arabic


def enrich_and_calculate(
    raw_profile: str,
    target_entity: str,
    requested_route: str | None = None,
) -> dict[str, Any]:
    """Pure orchestration: LLM reads the profile, deterministic code does the rest."""
    rule = resolve_rule(target_entity)
    eor_rule = resolve_rule(Entity.CERCLI_EOR_REMOTE)

    parsed = parse_candidate(raw_profile, target_entity)
    route, reasons = select_route(rule, parsed, requested_route)
    cost = calculate(rule, eor_rule, parsed["estimated_monthly_base_usd"], route)
    cost["reasons"] = reasons
    cost["quota_risk_level"] = rule.quota_risk_level
    cost["quota_risk_note"] = rule.quota_risk_note

    # Outreach: keep the model's warmth, then staple on the facts it could not know.
    # Route/days/cost only exist after calculation, so they are appended from
    # calculator output — never written by the LLM.
    template_en, template_ar = build_outreach(parsed, cost, route)
    footer_en, footer_ar = compliance_footer(cost, route)

    if parsed.get("outreach_en"):
        parsed["outreach_en"] = f"{parsed['outreach_en']}\n\n{footer_en}"
    else:
        parsed["outreach_en"] = template_en

    if parsed.get("outreach_ar"):
        parsed["outreach_ar"] = f"{parsed['outreach_ar']}\n\n{footer_ar}"
    else:
        parsed["outreach_ar"] = template_ar

    return {
        "target_entity": target_entity,
        "parsed": parsed,
        "route": route,
        "cost_breakdown": cost,
        "time_to_start_days": cost["time_to_start_days"],
        "monthly_employer_cost_usd": cost["monthly"]["total_usd"],
        "upfront_cost_usd": cost["upfront"]["total_usd"],
        "outreach_en": parsed["outreach_en"],
        "outreach_ar": parsed["outreach_ar"],
        "llm_source": parsed.get("source", "heuristic-mock"),
    }


def batch_key(batch_id: str, raw_profile: str, target_entity: str) -> str:
    digest = hashlib.sha256(f"{raw_profile.strip()}|{target_entity}".encode()).hexdigest()[:24]
    return f"{batch_id}:{digest}"


def persist(
    result: dict[str, Any],
    raw_profile: str,
    batch_id: str = "adhoc",
) -> CandidateSimulation:
    """Idempotent upsert — replaying the same profile + entity never duplicates."""
    simulation, _ = CandidateSimulation.objects.update_or_create(
        batch_key=batch_key(batch_id, raw_profile, result["target_entity"]),
        defaults={
            "batch_id": batch_id,
            "raw_profile": raw_profile,
            "target_entity": result["target_entity"],
            "parsed": result["parsed"],
            "route": result["route"],
            "cost_breakdown": result["cost_breakdown"],
            "monthly_employer_cost_usd": result["monthly_employer_cost_usd"],
            "upfront_cost_usd": result["upfront_cost_usd"],
            "time_to_start_days": result["time_to_start_days"],
            "outreach_en": result["outreach_en"],
            "outreach_ar": result["outreach_ar"],
            "llm_source": result["llm_source"],
        },
    )
    return simulation


def run_candidate(
    raw_profile: str,
    target_entity: str,
    batch_id: str = "adhoc",
    refresh: bool = False,
) -> CandidateSimulation:
    """Cached by (profile, entity) so demo re-runs cost nothing.

    `refresh=True` forces a fresh LLM call (and a real charge).
    """
    if not refresh:
        cached = CandidateSimulation.objects.filter(
            batch_key=batch_key(batch_id, raw_profile, target_entity)
        ).first()
        if cached is not None:
            return cached
    result = enrich_and_calculate(raw_profile, target_entity)
    return persist(result, raw_profile, batch_id=batch_id)
