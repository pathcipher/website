#!/usr/bin/env sh
set -e

# Wait for Postgres if we're configured to use it.
if [ -n "$POSTGRES_HOST" ]; then
  echo "Waiting for Postgres at ${POSTGRES_HOST}:${POSTGRES_PORT:-5432} ..."
  until pg_isready -h "$POSTGRES_HOST" -p "${POSTGRES_PORT:-5432}" -U "${POSTGRES_USER:-postgres}" >/dev/null 2>&1; do
    sleep 1
  done
  echo "Postgres is up."
fi

echo "Applying database migrations ..."
python manage.py migrate --noinput

echo "Seeding initial site content (idempotent) ..."
python manage.py seed_site

# Collect static unless explicitly disabled (dev uses runserver instead).
if [ "${DJANGO_COLLECTSTATIC:-1}" != "0" ]; then
  echo "Collecting static files ..."
  python manage.py collectstatic --noinput
fi

exec "$@"
