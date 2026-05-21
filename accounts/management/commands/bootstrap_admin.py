import os

from django.contrib.auth.models import Permission, User
from django.core.management.base import BaseCommand, CommandError

from accounts.models import Role, UserProfile
from accounts.views import PRIMARY_ADMIN_NATIONAL_ID


class Command(BaseCommand):
    help = "Create or update the primary system administrator account."

    def add_arguments(self, parser):
        parser.add_argument("--username", default=os.environ.get("PRIMARY_ADMIN_USERNAME", "admin"))
        parser.add_argument("--password", default=os.environ.get("PRIMARY_ADMIN_PASSWORD"))
        parser.add_argument("--email", default=os.environ.get("PRIMARY_ADMIN_EMAIL", "admin@example.com"))
        parser.add_argument("--national-id", default=os.environ.get("PRIMARY_ADMIN_NATIONAL_ID", PRIMARY_ADMIN_NATIONAL_ID))
        parser.add_argument("--phone", default=os.environ.get("PRIMARY_ADMIN_PHONE", ""))

    def handle(self, *args, **options):
        password = options["password"]
        if not password:
            raise CommandError(
                "Password is required. Pass --password or set PRIMARY_ADMIN_PASSWORD."
            )

        role, _ = Role.objects.get_or_create(
            name="مشرف النظام الرئيسي",
            defaults={
                "description": "صلاحيات كاملة لإدارة النظام.",
                "requires_subscription": False,
            },
        )
        role.permissions.set(Permission.objects.all())

        user, created = User.objects.get_or_create(
            username=options["username"],
            defaults={
                "email": options["email"],
                "is_staff": True,
                "is_superuser": True,
                "is_active": True,
            },
        )
        user.email = options["email"]
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.set_password(password)
        user.save()

        profile = UserProfile.objects.filter(national_id=options["national_id"]).first()
        if profile and profile.user_id != user.id:
            profile.user = user
        elif not profile:
            profile = getattr(user, "profile", None) or UserProfile(user=user)
        profile.national_id = options["national_id"]
        profile.phone = options["phone"]
        profile.role = role
        profile.is_subscription_exempt = True
        profile.is_disabled_by_admin = False
        profile.disabled_reason = ""
        profile.save()

        self.stdout.write(self.style.SUCCESS(
            f"{'Created' if created else 'Updated'} primary admin: "
            f"username={user.username}, national_id={profile.national_id}"
        ))
