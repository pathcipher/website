"""
Development settings.

DEBUG on, permissive hosts, sqlite by default (or Postgres if DATABASE_URL is
set, e.g. when running under Docker Compose locally).
"""
from .base import *  # noqa: F401,F403
from .base import env

DEBUG = env.bool("DJANGO_DEBUG", default=True)

# A predictable key so local dev never breaks; prod supplies a real one.
SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-only-not-secret-key")

ALLOWED_HOSTS = env.list(
    "DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "0.0.0.0"]
)

# Show emails in the console during development.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Simpler static storage in dev (no manifest hashing needed).
STORAGES["staticfiles"] = {  # noqa: F405
    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
}

# Flag consumed by templates to load Tailwind via CDN in dev.
TAILWIND_CDN = True

try:
    from .local import *  # noqa: F401,F403
except ImportError:
    pass
