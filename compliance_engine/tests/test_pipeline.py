"""End-to-end: seeded rules → parser → calculator → GraphQL → Celery idempotency."""
import json

import pytest
from django.core.management import call_command
from django.test import Client

from compliance_engine.models import CandidateSimulation, Route
from compliance_engine.services import pipeline
from compliance_engine.services.llm_parser import clean_name, heuristic_parse
from compliance_engine.services.pipeline import enrich_and_calculate, run_candidate
from compliance_engine.tasks import process_orin_shortlist_batch

pytestmark = pytest.mark.django_db

DUBAI_PROFILE = (
    "Name: Omar Haddad\nSenior Backend Engineer, based in Dubai Marina, UAE. "
    "Valid UAE visa, transferable with immediate join. AED 32,000 per month."
)
ABROAD_PROFILE = (
    "Name: Yusuf Demir\nPlatform/DevOps Lead Engineer, based in Istanbul, Turkey. "
    "Open to relocate, needs a work permit. USD 8,500 per month."
)

MUTATION = """
mutation ($raw: String!, $entity: String!) {
  simulateCandidateCompliance(rawProfile: $raw, targetEntity: $entity) {
    route timeToStartDays outreachEn outreachAr parsed monthly { totalUsd } upfront { totalUsd }
  }
}
"""


@pytest.fixture
def seeded():
    call_command("seed_gcc_rules", verbosity=0)


def post(client, query, variables):
    response = client.post(
        "/graphql", data=json.dumps({"query": query, "variables": variables}),
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert "errors" not in body, body["errors"]
    return body["data"]


def test_graphql_mutation_routes_local_candidate_to_transfer(seeded):
    data = post(Client(), MUTATION, {"raw": DUBAI_PROFILE, "entity": "UAE_DIFC"})
    result = data["simulateCandidateCompliance"]

    assert result["route"] == Route.LOCAL_TRANSFER
    assert result["upfront"]["totalUsd"] == "550.00"  # medical only, no new permit
    assert result["parsed"]["in_target_country"] is True
    assert result["outreachEn"] and result["outreachAr"]
    assert CandidateSimulation.objects.count() == 1


def test_graphql_mutation_falls_back_to_eor_when_quota_blocks_sponsorship(seeded):
    data = post(Client(), MUTATION, {"raw": ABROAD_PROFILE, "entity": "KSA_RIYADH"})
    result = data["simulateCandidateCompliance"]

    assert result["route"] == Route.CERCLI_EOR
    assert result["upfront"]["totalUsd"] == "0.00"
    assert result["timeToStartDays"] == 10


def test_model_outreach_gets_calculated_footer(seeded, monkeypatch):
    """Option A: the LLM writes the warmth, the calculator writes the facts."""
    model_output = {
        "full_name": "Omar Haddad",
        "current_city": "dubai",
        "current_country": "uae",
        "in_target_country": True,
        "transferable_visa": True,
        "seniority": "senior",
        "estimated_monthly_base_usd": 8713.41,
        "salary_confidence": "llm",
        "signals": ["In Dubai", "Transferable visa"],
        "outreach_en": "Hi Omar, we loved your payments work — can we talk?",
        "outreach_ar": "مرحباً عمر، أعجبنا عملك في المدفوعات — هل نتحدث؟",
        "source": "deepinfra",
    }
    monkeypatch.setattr(
        "compliance_engine.services.pipeline.parse_candidate",
        lambda raw, entity: dict(model_output),
    )

    result = enrich_and_calculate(DUBAI_PROFILE, "UAE_DIFC")
    cost = result["cost_breakdown"]

    assert result["route"] == Route.LOCAL_TRANSFER
    assert result["outreach_en"].startswith("Hi Omar, we loved")
    # footer comes from the calculator, not the model
    assert "Route: local visa transfer" in result["outreach_en"]
    assert f"~${float(cost['monthly']['total_usd']):,.0f}/month" in result["outreach_en"]
    assert result["outreach_ar"].startswith("مرحباً عمر")
    assert "المسار: نقل الكفالة داخل الدولة" in result["outreach_ar"]


def test_blank_profile_is_rejected(seeded):
    response = Client().post(
        "/graphql",
        data=json.dumps({"query": MUTATION, "variables": {"raw": "   ", "entity": "UAE_DIFC"}}),
        content_type="application/json",
    )
    body = response.json()
    assert "errors" in body
    assert "empty" in body["errors"][0]["message"].lower()
    assert CandidateSimulation.objects.count() == 0


def test_repeat_runs_are_served_from_cache(seeded, monkeypatch):
    calls = []
    original = pipeline.parse_candidate

    def counting_parser(raw, entity):
        calls.append(1)
        return original(raw, entity)

    monkeypatch.setattr("compliance_engine.services.pipeline.parse_candidate", counting_parser)

    first = run_candidate(DUBAI_PROFILE, "UAE_DIFC", batch_id="demo")
    again = run_candidate(DUBAI_PROFILE, "UAE_DIFC", batch_id="demo")
    assert first.pk == again.pk
    assert len(calls) == 1  # cached — no second parse, no second LLM charge

    refreshed = run_candidate(DUBAI_PROFILE, "UAE_DIFC", batch_id="demo", refresh=True)
    assert len(calls) == 2
    assert refreshed.pk == first.pk  # upsert, not duplicate


def test_placeholder_names_are_replaced():
    assert clean_name("Name:") is None
    assert clean_name("unknown") is None
    assert clean_name("Omar Haddad") == "Omar Haddad"
    assert heuristic_parse("Name:", "UAE_DIFC")["full_name"] == "Candidate"


def test_batch_task_is_idempotent(seeded):
    payload = {"batch_id": "batch-001", "profiles": [DUBAI_PROFILE, ABROAD_PROFILE],
               "target_entity": "UAE_DIFC"}

    first = process_orin_shortlist_batch(**payload)
    second = process_orin_shortlist_batch(**payload)

    assert first["processed"] == 2 and second["processed"] == 2
    assert CandidateSimulation.objects.filter(batch_id="batch-001").count() == 2
