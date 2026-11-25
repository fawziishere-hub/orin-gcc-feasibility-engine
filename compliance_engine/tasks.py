"""Celery entrypoints. Eager locally, real workers on Redis/ECS in production."""
import logging

from celery import shared_task

from .models import CandidateSimulation
from .services.pipeline import run_candidate

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def process_orin_shortlist_batch(self, batch_id: str, profiles: list[str], target_entity: str) -> dict:
    """Enrich + cost a shortlist. Idempotent: re-running a batch updates in place."""
    processed, failed = 0, 0
    for index, raw_profile in enumerate(profiles):
        try:
            simulation = run_candidate(raw_profile, target_entity, batch_id=batch_id)
            processed += 1
            logger.info(
                "batch=%s item=%s route=%s monthly=%s",
                batch_id, index, simulation.route, simulation.monthly_employer_cost_usd,
            )
        except Exception as exc:  # noqa: BLE001 — one bad profile must not sink the batch
            failed += 1
            logger.exception("batch=%s item=%s failed: %s", batch_id, index, exc)

    total = CandidateSimulation.objects.filter(batch_id=batch_id).count()
    return {
        "batch_id": batch_id,
        "submitted": len(profiles),
        "processed": processed,
        "failed": failed,
        "stored_total": total,
    }
