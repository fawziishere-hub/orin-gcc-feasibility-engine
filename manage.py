#!/usr/bin/env python
"""Django management entrypoint for the Orin GCC Feasibility engine."""
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "orin_config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Django is not installed. Activate the venv: .venv\\Scripts\\activate"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
