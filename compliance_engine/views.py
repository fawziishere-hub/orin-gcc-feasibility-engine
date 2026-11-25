from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render

from .models import CandidateSimulation, CountryComplianceRule


def index(request):
    rules = [
        {"entity_code": rule.entity_code, "label": rule.get_entity_code_display()}
        for rule in CountryComplianceRule.objects.all()
    ]
    return render(request, "index.html", {"rules": rules})


def health(request):
    """Reports DB status instead of 500ing, so a broken deploy is self-diagnosing.

    Only the exception class is exposed — never the message, which can contain
    host and user names.
    """
    payload = {
        "status": "ok",
        "service": "orin-gcc-feasibility",
        "llm_configured": bool(settings.DEEPINFRA_API_KEY),
        "celery_eager": settings.CELERY_TASK_ALWAYS_EAGER,
        "database_engine": connection.settings_dict.get("ENGINE", "unknown"),
    }
    try:
        payload["simulations_stored"] = CandidateSimulation.objects.count()
        payload["rules_seeded"] = CountryComplianceRule.objects.count()
    except Exception as exc:  # noqa: BLE001 — this endpoint must not 500
        name = type(exc).__name__
        payload.update(
            status="degraded",
            # OperationalError = cannot reach the server; anything else is a
            # reachable database that is missing schema (migrations not run).
            database="unreachable" if name == "OperationalError" else "schema_missing",
            error=name,
        )
        return JsonResponse(payload, status=503)
    return JsonResponse(payload)
