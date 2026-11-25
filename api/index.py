"""Vercel serverless entrypoint — exposes the Django WSGI app.

Vercel routes every request here (see vercel.json). The project root is added to
sys.path so `orin_config` and `compliance_engine` import normally.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "orin_config.settings")

from django.core.wsgi import get_wsgi_application  # noqa: E402

app = get_wsgi_application()
