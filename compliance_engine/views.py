from django.conf import settings
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
    return JsonResponse(
        {
            "status": "ok",
            "service": "orin-gcc-feasibility",
            "simulations_stored": CandidateSimulation.objects.count(),
            "llm_configured": bool(settings.DEEPINFRA_API_KEY),
            "celery_eager": settings.CELERY_TASK_ALWAYS_EAGER,
        }
    )
