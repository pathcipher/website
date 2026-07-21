from django.conf import settings


def site_settings(request):
    """Expose a small, explicit set of Django settings to all templates."""
    return {
        "TAILWIND_CDN": getattr(settings, "TAILWIND_CDN", False),
        "SITE_NAME": getattr(settings, "WAGTAIL_SITE_NAME", "Puzzle Team"),
    }
