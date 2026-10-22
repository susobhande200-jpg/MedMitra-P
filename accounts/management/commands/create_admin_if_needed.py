import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create or repair the configured deployment admin."

    def handle(self, *args, **options):
        if os.getenv("CREATE_ADMIN_ON_DEPLOY") != "1":
            self.stdout.write("Admin setup disabled.")
            return

        username = os.getenv("DJANGO_SUPERUSER_USERNAME", "").strip()
        password = os.getenv("DJANGO_SUPERUSER_PASSWORD", "")
        email = os.getenv("DJANGO_SUPERUSER_EMAIL", "").strip()

        if not username or not password:
            raise CommandError(
                "DJANGO_SUPERUSER_USERNAME and "
                "DJANGO_SUPERUSER_PASSWORD must be configured."
            )

        User = get_user_model()
        fields = {field.name for field in User._meta.fields}
        lookup = {User.USERNAME_FIELD: username}
        defaults = {}

        if "email" in fields and email:
            defaults["email"] = email

        user, created = User.objects.get_or_create(
            **lookup, defaults=defaults
        )

        changed = []

        for field in ("is_active", "is_staff", "is_superuser"):
            if field in fields and not getattr(user, field):
                setattr(user, field, True)
                changed.append(field)

        if "email" in fields and email and user.email != email:
            user.email = email
            changed.append("email")

        if created or os.getenv("RESET_ADMIN_PASSWORD") == "1":
            user.set_password(password)
            changed.append("password")

        if changed:
            user.save(update_fields=list(set(changed)))

        action = "Created" if created else "Verified/repaired"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} deployment admin: {username}"
            )
        )
