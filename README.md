# Orin — GCC Feasibility & Total-Cost Engine

A plug-in backend + demo UI for **Cercli** (Dubai-based MENA HR, ATS, EOR and payroll platform)
and **Orin**, its AI sourcing agent.

Given a candidate profile and a target entity, Orin answers the three questions a MENA recruiter
actually has to answer before a shortlist goes out:

1. **Can we hire this person, and on which route?** — local transfer, new work permit, or Cercli EOR.
2. **What does the employer really pay per month?** — base + GOSI/DEWS + end-of-service gratuity (+ EOR fee).
3. **What does it cost to start, and how long until they start?** — visa/permit, medical + Emirates ID, onboarding days.

Plus bilingual (English + Arabic) outreach copy ready to send.

---

## Design rule: the LLM reads, the code does the maths

| Layer | Owns |
|---|---|
| `services/llm_parser.py` | Reading the profile: location, work-auth signal, seniority, salary band, outreach copy |
| `calculator.py` | **Every number.** Pure `Decimal` Python, no model calls, fully unit-tested |
| `models.py` | `CountryComplianceRule` (seeded facts) + `CandidateSimulation` (audit trail) |
| `services/pipeline.py` | The single parse → route → cost → outreach → persist path |
| `schema.py` / `views.py` | GraphQL API + demo UI |
| `tasks.py` | Batch enrichment for an Orin shortlist |

A prompt-injected profile can change what the agent *says*. It can never change a costed number,
because the calculator only consumes seeded rule rows and re-derives everything.

Routes are chosen in `calculator.select_route` in a fixed precedence order:

```
abroad + jurisdiction at HIGH quota risk  → CERCLI_EOR       (no permit, 10 days)
in-country + transferable permit          → LOCAL_TRANSFER   (no permit fee, ~40% onboarding time)
in-country, no transferable permit        → NEW_WORK_PERMIT
must relocate, quota available            → NEW_WORK_PERMIT
target entity = CERCLI_EOR_REMOTE         → CERCLI_EOR
```

Seeded jurisdictions: `UAE_DIFC`, `UAE_MAINLAND`, `KSA_RIYADH`, `QATAR_DOHA`, `CERCLI_EOR_REMOTE`.

---

## Run it

```bash
python -m venv .venv && .venv\Scripts\activate      # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt                 # runtime + pytest
python manage.py migrate
python manage.py seed_gcc_rules
python manage.py runserver
```

Open <http://127.0.0.1:8000/> for the demo UI, <http://127.0.0.1:8000/graphql> for GraphiQL.

Deploying to Vercel? See **[DEPLOY.md](DEPLOY.md)** — it covers the two things that do not transfer
(no SQLite filesystem, no Celery workers) and the Neon setup that replaces them.

### Configuration

Create a `.env` file in the project root — it is git-ignored and entirely optional, since every
setting has a working default. Only these keys are read:

| Key | Default | Purpose |
|---|---|---|
| `DJANGO_SECRET_KEY` | dev value | Django secret |
| `DJANGO_DEBUG` | `1` | `0` in production enables WhiteNoise |
| `DATABASE_URL` | SQLite | Postgres/RDS in production |
| `REDIS_URL` | unset → eager Celery | Celery broker |
| `DEEPINFRA_API_KEY` | unset → mock parser | Orin profile parsing |
| `DEEPINFRA_BASE_URL` | `https://api.deepinfra.com/v1/openai` | OpenAI-compatible base |
| `DEEPINFRA_MODEL` | `meta-llama/Meta-Llama-3.1-70B-Instruct` | aliased server-side to Llama-3.3-Turbo |
| `LLM_TIMEOUT_SECONDS` | `60` | read timeout for one structured call |

Tests:

```bash
pytest        # 9 tests: pure calculator math + GraphQL end-to-end + task idempotency
```

### Zero-config by default

- **No `DEEPINFRA_API_KEY`?** The deterministic heuristic parser takes over — the demo still works
  and every number is still correct.
- **No `DATABASE_URL`?** SQLite.
- **No `REDIS_URL`?** Celery runs `CELERY_TASK_ALWAYS_EAGER=True`, so `.delay()` executes inline.
  Set `REDIS_URL` and the same call becomes a real queued task — no code change.

```bash
# with Redis running, the batch runs on a worker instead
celery -A orin_config worker -l info
```

---

## API

```graphql
mutation {
  simulateCandidateCompliance(
    rawProfile: "Name: Omar Haddad\nSenior Backend Engineer in Dubai Marina. Valid UAE visa, transferable. AED 32,000 per month."
    targetEntity: "UAE_DIFC"
  ) {
    route timeToStartDays quotaRiskLevel reasons llmSource
    monthly { baseSalaryUsd employerSocialInsuranceUsd gratuityAccrualUsd totalUsd }
    upfront { visaPermitUsd medicalIdUsd totalUsd }
    annualEmployerCostUsd outreachEn outreachAr
  }
}

query {
  simulations(limit: 10) { id route monthly { totalUsd } parsed }
  complianceRules { entityCode avgOnboardingDays quotaRiskLevel }
}
```

`GET /health` returns engine status (stored simulations, whether DeepInfra is configured, eager Celery).

Batch (Celery):

```python
from compliance_engine.tasks import process_orin_shortlist_batch
process_orin_shortlist_batch.delay("batch-2024-11", profiles, "UAE_DIFC")
```

Re-running a batch is idempotent: `batch_key = batch_id:sha256(profile|entity)`, so retries and
duplicate queue deliveries update rows rather than duplicating them.

---

## Plugging into Cercli's stack

The service is a normal Django app — it drops into the existing AWS deployment without a new runtime:

```
ALB → ECS (gunicorn, Django 5 + DRF + Strawberry)  → RDS Postgres   (DATABASE_URL)
                     ↓ .delay()                       ↘ ElastiCache Redis (REDIS_URL)
              Celery workers (process_orin_shortlist_batch)
                     ↓
              DeepInfra OpenAI-compatible API (DEEPINFRA_API_KEY, secrets manager)
```

1. **Postgres** — `DATABASE_URL=postgres://…` (RDS). Nothing else changes; JSONB stores `parsed`
   and `cost_breakdown` natively.
2. **Celery** — set `REDIS_URL`; mount `/graphql` and the ORM-backed tasks behind the existing API
   gateway or keep them internal to the Orin VPC service.
3. **LLM** — `DEEPINFRA_API_KEY` / `DEEPINFRA_MODEL` from secrets; swap the model without a deploy.
4. **Rules ownership** — compliance owns `CountryComplianceRule` rows (Django admin is already
   wired at `/admin/`), so legal can refresh fees and quota notes without shipping code.
5. **Multi-tenancy** — add a `tenant`/`company` FK to `CandidateSimulation` and filter by request
   context; the calculator is tenant-agnostic by design.
6. **Static** — `python manage.py collectstatic`; WhiteNoise is enabled when `DJANGO_DEBUG=0`.

### Where not to extend

Don't let the LLM produce the cost breakdown "for natural language", and don't tune route selection
by prompt. Both are audited numbers — extend `CountryComplianceRule` and `select_route` instead.

---

## Caveats

Rule figures are **illustrative planning defaults** (MoHRE, HRSD/Nitaqat, GOSI, DEWS, gratuity
accrual), not legal advice. Refresh them before quoting a client, and keep the paid-permit vs.
bundled-EOR distinction in mind when comparing routes.
