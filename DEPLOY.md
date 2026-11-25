# Deploying to Vercel

Vercel can host this app, with two structural constraints you should know before starting:

| Cercli prod assumption | On Vercel | What we do |
|---|---|---|
| Long-running Celery workers + Redis | Not supported (no persistent processes) | `CELERY_TASK_ALWAYS_EAGER=True`; `process_orin_shortlist_batch` runs inline. The UI calls GraphQL directly, so the demo is unaffected. |
| Local/ECS disk for SQLite | Read-only, per-invocation filesystem | Postgres (Neon/Supabase) via `DATABASE_URL`. Settings **refuse to boot** on Vercel without it rather than pretend SQLite works. |
| One warm process, persistent DB connections | Cold starts, many short-lived instances | `conn_max_age=0`, server-side cursors disabled (pooler-safe). |

Anything with a real request queue or a worker should live on ECS/Lambda, not here.

## 1. Create the Neon database

1. Sign up at <https://neon.tech> → **New Project** (pick the region closest to your Vercel region).
2. Dashboard → **Connect** gives you two strings. You need both:

| Use | String | Note |
|---|---|---|
| App runtime → `DATABASE_URL` in Vercel | host contains **`-pooler`** | PgBouncer, safe for many short-lived lambdas |
| Migrations, run from your machine | host **without** `-pooler` | direct connection; DDL over a transaction pooler can misbehave |

Both look like:

```
postgresql://user:password@ep-xxx-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require
```

Copy them now — Neon shows the password once. Settings keep `sslmode=require` intact (it is merged
into `OPTIONS`, not overwritten) and set `CONN_MAX_AGE=0` plus
`DISABLE_SERVER_SIDE_CURSORS=True`, which is what makes a transaction pooler safe for Django.

## 2. Set environment variables in Vercel

Project → Settings → Environment Variables (Production + Preview):

| Variable | Value |
|---|---|
| `DATABASE_URL` | the pooled Postgres URL above |
| `DJANGO_SECRET_KEY` | long random string |
| `DJANGO_DEBUG` | `0` |
| `DEEPINFRA_API_KEY` | your key (never in the repo) |
| `DEEPINFRA_MODEL` | `deepseek-ai/DeepSeek-V4.1-Flash-1017` |
| `LLM_TIMEOUT_SECONDS` | `60` |
| `PYTHON_VERSION` | `3.12` (Django 5 requires ≥3.10; the runtime default can lag) |

`ALLOWED_HOSTS` and CSRF origins are handled automatically from `VERCEL_URL`; add
`CSRF_TRUSTED_ORIGINS` only if you attach a custom domain.

## 3. Apply migrations + seed rules (once, from your machine)

The build never touches your database. Use the **direct** (non-pooled) URL here:

```bash
# Windows
set DATABASE_URL=postgresql://...@ep-xxx.eu-central-1.aws.neon.tech/neondb?sslmode=require
.venv\Scripts\python.exe manage.py migrate
.venv\Scripts\python.exe manage.py seed_gcc_rules

# macOS / Linux
DATABASE_URL="postgresql://...direct..." .venv/bin/python manage.py migrate
DATABASE_URL="postgresql://...direct..." .venv/bin/python manage.py seed_gcc_rules
```

Expect `Seeded 5 GCC compliance rules.` If migrations fail with a connection error, your IP is
likely blocked by a Neon allow-list rule, or you pasted the pooled host by mistake.

## 4. Deploy

```bash
npx vercel        # first run: links the project, previews
npx vercel --prod # production
```

## 5. Smoke test

```bash
curl https://<your-app>.vercel.app/health
# {"status":"ok","simulations_stored":5,"llm_configured":true,"celery_eager":true}
```

Then open `/` and run all four profiles; `/graphql` serves GraphiQL.

## Known limits on this platform

- **Cold starts** — the first request after idle pays ~1–3s of import time. Extra dependencies in
  `requirements.txt` (celery, gunicorn) make it slightly worse; they are kept because
  `orin_config/__init__.py` imports the Celery app.
- **`maxDuration: 60`** — one LLM call takes ~6s, so this is comfortable. Four profiles fire as
  four separate invocations in parallel, not one long request.
- **Admin CSS** — `staticfiles/` is excluded from the upload, so `/admin/` loads unstyled. The demo
  page is unaffected (Tailwind via CDN). Run `collectstatic` and include the folder if you need it.
- **Cron/batch** — `process_orin_shortlist_batch` runs inline. For real batch volume, point
  `REDIS_URL` at Upstash and run workers off Vercel (Railway/Fly/ECS).
- **Sessions** — stored in Postgres; every anonymous visit writes rows. Fine for a demo.
- **Neon idle suspension** — the free tier suspends compute after ~5 minutes idle. The next request
  pays ~500ms–2s to wake it, on top of the Vercel cold start. Warm it with `curl /health` right
  before a demo.
