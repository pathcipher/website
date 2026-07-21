"""
Seed the public site with a HomePage (Pathcipher brand content) and a Contact
page, and point the default Wagtail Site at it.

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
            title="Pathcipher Events",
            slug="home",
            hero_kicker="Collaborate. Solve. Engage.",
            hero_heading="Immersive puzzle experiences for teams & events",
            hero_subheading=(
                "Bring your team together through puzzle experiences designed "
                "to challenge minds, build trust, and spark creativity. Perfect "
                "for school team building, corporate away days, and activities "
                "for all ages."
            ),
            hero_cta_label="Get in touch",
            show_in_menus=False,
            body=[
                ("heading", {"text": "Serious Fun for Serious Teams", "size": "h2"}),
                ("paragraph", (
                    "<p>We create puzzle-based events that combine critical "
                    "thinking with communication under pressure. Each experience "
                    "is crafted to test logic, teamwork, and lateral thinking — "
                    "ensuring everyone contributes and no one feels left out.</p>"
                )),
                ("feature_grid", {
                    "heading": "",
                    "cards": [
                        {
                            "icon_emoji": "🧩",
                            "title": "Custom-Designed Challenges",
                            "body": (
                                "Tailored to your team's goals, size, and theme "
                                "— we can cater for any group."
                            ),
                        },
                        {
                            "icon_emoji": "🤝",
                            "title": "Inclusive Experiences",
                            "body": (
                                "Designed for all backgrounds and skill levels, "
                                "we provide a variety of challenges."
                            ),
                        },
                        {
                            "icon_emoji": "📍",
                            "title": "Tailored to any Space",
                            "body": (
                                "We have experience with events in various "
                                "settings, from conference spaces to parks."
                            ),
                        },
                    ],
                }),
                ("cta", {
                    "heading": "Find Out More",
                    "text": (
                        "Ready to bring your team together? Get in touch to "
                        "plan your event."
                    ),
                    "button_label": "Contact Us",
                }),
            ],
        )
        root.add_child(instance=home)

        home.add_child(instance=StandardPage(
            title="Contact Us",
            slug="contact",
            show_in_menus=True,
            intro=(
                "<p>Ready to plan your event or have a question? "
                "We'd love to hear from you.</p>"
            ),
        ))

        site = Site.objects.filter(is_default_site=True).first()
        if site:
            site.root_page = home
            site.site_name = "Pathcipher Events"
            site.save()
        else:
            Site.objects.create(
                hostname="localhost", port=80, root_page=home,
                is_default_site=True, site_name="Pathcipher Events",
            )

        for stale in stale_pages:
            stale.refresh_from_db()
            stale.delete()

        self.stdout.write(self.style.SUCCESS(
            "Seeded Pathcipher HomePage + Contact page and set the default site."
        ))
