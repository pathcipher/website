"""
Seed the public site with a HomePage and a few starter pages, and point the
default Wagtail Site at it.

Idempotent: running it again is a no-op once a HomePage exists. Intended to run
once after `migrate` (the Docker entrypoint does this automatically).
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from wagtail.models import Page, Site

from cms.models import HomePage, StandardPage


class Command(BaseCommand):
    help = "Create initial public-site content (idempotent)."

    @transaction.atomic
    def handle(self, *args, **options):
        if HomePage.objects.exists():
            self.stdout.write("HomePage already exists — nothing to do.")
            return

        root = Page.objects.filter(depth=1).first()
        if root is None:
            self.stderr.write("No Wagtail root page found; run migrate first.")
            return

        # Free the 'home' slug from Wagtail's default welcome page before we
        # create ours (slugs are unique among siblings); delete it afterwards.
        stale_pages = list(Page.objects.filter(slug="home", depth=2))
        for stale in stale_pages:
            stale.slug = f"retired-welcome-{stale.pk}"
            stale.save(update_fields=["slug"])

        home = HomePage(
            title="Puzzle Team",
            slug="home",
            hero_kicker="Live puzzle experiences",
            hero_heading="Unforgettable puzzles for teams & events",
            hero_subheading=(
                "Immersive escape rooms and pop-up puzzle challenges, run for "
                "your team, party, or private event — anywhere you like."
            ),
            hero_cta_label="Plan your event",
            show_in_menus=False,
        )
        root.add_child(instance=home)

        for title, slug in [
            ("Experiences", "experiences"),
            ("About", "about"),
            ("Contact", "contact"),
        ]:
            home.add_child(instance=StandardPage(
                title=title, slug=slug, show_in_menus=True
            ))

        site = Site.objects.filter(is_default_site=True).first()
        if site:
            site.root_page = home
            site.site_name = "Puzzle Team"
            site.save()
        else:
            Site.objects.create(
                hostname="localhost", port=80, root_page=home,
                is_default_site=True, site_name="Puzzle Team",
            )

        for stale in stale_pages:
            stale.refresh_from_db()
            stale.delete()

        self.stdout.write(self.style.SUCCESS(
            "Seeded HomePage + Experiences/About/Contact and set the default site."
        ))
