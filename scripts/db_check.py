"""Diagnose the database: which one Django actually sees, can it connect, is it migrated.

Run from the project root:
    .venv\\Scripts\\python.exe scripts/db_check.py

Reads DATABASE_URL from the environment or from .env (which settings loads anyway).
Prints the host and database name, never the password.
"""
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "orin_config.settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.db import connection  # noqa: E402

cfg = settings.DATABASES["default"]
engine = str(cfg.get("ENGINE"))
host = cfg.get("HOST") or "(local file)"
name = cfg.get("NAME")
user = cfg.get("USER") or "(none)"

print(f"engine : {engine}")
print(f"host   : {host}")
print(f"db     : {name}")
print(f"user   : {user}")
print(f"options: {cfg.get('OPTIONS')}")

if "sqlite" in engine:
    print()
    print("!! Django is using SQLite, not Postgres.")
    print("   DATABASE_URL never reached it, so nothing you migrate here touches the")
    print("   deployed site. In bash use `export DATABASE_URL=...`, not `set DATABASE_URL=...`")
    print("   (that is cmd.exe syntax; in bash `set` does not create an env var).")
    print("   Easiest fix: add DATABASE_URL=... to .env (git-ignored) and rerun.")
    sys.exit(2)

print()
try:
    connection.ensure_connection()
    print("connect: OK")
except Exception as exc:
    print(f"connect: FAILED -> {type(exc).__name__}")
    print(str(exc)[:600])
    print()
    print("Typical causes: -pooler host pasted for migrations, wrong password,")
    print("wrong database name, Neon IP allow-list, or missing ?sslmode=require.")
    sys.exit(1)

print()
try:
    call_command("migrate", interactive=False, verbosity=1)
    print("\nmigrate: OK")
except Exception:
    print("\nmigrate: FAILED")
    traceback.print_exc()
    sys.exit(1)

try:
    call_command("seed_gcc_rules", verbosity=0)
    print("seed: OK")
except Exception:
    print("\nseed: FAILED")
    traceback.print_exc()
    sys.exit(1)

from compliance_engine.models import CandidateSimulation, CountryComplianceRule  # noqa: E402

print()
print(f"rules seeded      : {CountryComplianceRule.objects.count()} (expect 5)")
print(f"simulations stored: {CandidateSimulation.objects.count()}")
print("\nDone — reload the deployed site.")
