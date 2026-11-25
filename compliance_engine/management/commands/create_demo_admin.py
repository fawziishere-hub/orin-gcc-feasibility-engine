"""Create or reset the demo superuser, logging in with an email address.

    manage.py create_demo_admin --email admin@gmail.com --password admin123

`set_password` is used directly, which bypasses AUTH_PASSWORD_VALIDATORS — the
default validators reject a password this similar to the username. That is a
demo convenience, and the reason the password should be rotated before anything
real is put behind /admin/.
"""
import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create or reset a superuser that logs in with an email address."

    def add_arguments(self, parser):
        parser.add_argument("--email", default=os.getenv("ADMIN_EMAIL", "admin@gmail.com"))
        # No default: this repo is public, so a hardcoded password ships to GitHub.
        parser.add_argument("--password", default=os.getenv("ADMIN_PASSWORD"))

    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        password = options["password"]
        if not password:
            raise CommandError(
                "Provide --password or set ADMIN_PASSWORD. Never commit a password to source."
            )
        User = get_user_model()

        user, created = User.objects.get_or_create(
            username=email, defaults={"email": email}
        )
        user.email = email
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.set_password(password)
        user.save()

        action = "Created" if created else "Reset password for"
        self.stdout.write(self.style.SUCCESS(f"{action} {email}"))
        if password in {"admin123", "admin", "password", "12345678"}:
            self.stdout.write(
                self.style.WARNING(
                    "  ! Weak demo password — rotate before putting real candidate data behind /admin/:\n"
                    "    manage.py create_demo_admin --email <you@company.com> --password '<strong>'"
                )
            )
