"""Django settings — 12-factor, Postgres-ready, eager Celery when Redis is absent."""
from pathlib import Path
import os

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-insecure-orin-feasibility-key")
# Anything other than an exact "1" is False. Defaults to debug-on for local work,
# but debug-OFF whenever we detect Vercel, so a forgotten env var fails safe.
DEBUG = os.getenv("DJANGO_DEBUG", "0" if os.getenv("VERCEL") else "1") == "1"
ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "*").split(",")
CSRF_TRUSTED_ORIGINS = [
    origin for origin in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if origin
]

# Vercel injects VERCEL_URL (no scheme) per deployment.
VERCEL_URL = os.getenv("VERCEL_URL")
if VERCEL_URL:
    ALLOWED_HOSTS.append(VERCEL_URL)
    CSRF_TRUSTED_ORIGINS.append(f"https://{VERCEL_URL}")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "strawberry.django",
    "compliance_engine",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

if not DEBUG:  # WhiteNoise serves collected assets in production only
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")

ROOT_URLCONF = "orin_config.urls"
WSGI_APPLICATION = "orin_config.wsgi.application"
ASGI_APPLICATION = "orin_config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

# Postgres in production via DATABASE_URL; SQLite for a zero-config local demo.
DATABASE_URL = os.getenv("DATABASE_URL", "")
if DATABASE_URL:
    # conn_max_age=0: serverless runtimes must not hold connections between requests.
    # Merge into OPTIONS rather than replacing it — dj-database-url puts query
    # params such as ?sslmode=require there, and Neon requires TLS.
    parsed_db = dj_database_url.parse(DATABASE_URL, conn_max_age=0)
    parsed_db.setdefault("OPTIONS", {})
    parsed_db["OPTIONS"]["DISABLE_SERVER_SIDE_CURSORS"] = True
    DATABASES = {"default": parsed_db}
elif os.getenv("VERCEL"):
    raise ImproperlyConfigured(
        "DATABASE_URL is required on Vercel: the filesystem is read-only and per-invocation, "
        "so the SQLite default would silently lose every simulation. Point it at Neon/Supabase."
    )
else:
    DATABASES = {
        "default": dj_database_url.config(
            default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
            conn_max_age=600,
        )
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Dubai"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    # Non-manifest: a missing collectstatic must never 500 a request.
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"}
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}

# --- Orin / LLM -------------------------------------------------------------
DEEPINFRA_API_KEY = os.getenv("DEEPINFRA_API_KEY", "")
DEEPINFRA_BASE_URL = os.getenv("DEEPINFRA_BASE_URL", "https://api.deepinfra.com/v1/openai")
DEEPINFRA_MODEL = os.getenv("DEEPINFRA_MODEL", "meta-llama/Meta-Llama-3.1-70B-Instruct")
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "60"))

# --- Celery -----------------------------------------------------------------
# No Redis locally → run tasks inline so the demo works with a single process.
CELERY_BROKER_URL = os.getenv("REDIS_URL", "")
REDIS_AVAILABLE = bool(CELERY_BROKER_URL)
CELERY_TASK_ALWAYS_EAGER = not REDIS_AVAILABLE
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", CELERY_BROKER_URL or None)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
