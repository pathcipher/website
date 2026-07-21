# Puzzle Team Platform

Two connected, self-hosted web apps for a puzzle / escape-room team, in a single
Django project:

1. **Public site** — a flashy marketing/content site editable via **Wagtail** CMS.
2. **Admin / PM tool** — internal Django admin (skinned with **django-unfold**)
   mapping customers → bookings → resources (venues, puzzle sets), with real
   double-booking prevention.

Everything is open source and runs on a single small VPS behind nginx with
Let's Encrypt TLS, via Docker Compose.

## Stack

| Concern            | Choice                                             |
| ------------------ | -------------------------------------------------- |
| Language/framework | Python 3.12, Django 5.1                            |
| CMS + public site  | Wagtail 6.3, Django templates + Tailwind (CDN) + htmx |
| Admin / PM tool    | Django admin skinned with django-unfold            |
| Database           | PostgreSQL 16 (single instance, shared)            |
| Reverse proxy/TLS  | nginx + certbot (Let's Encrypt, auto-renew)        |
| Serving            | gunicorn; WhiteNoise + nginx for static/media      |

## URLs

| Path        | What                                             |
| ----------- | ------------------------------------------------ |
| `/`         | Public site (Wagtail-rendered pages)             |
| `/admin/`   | Internal PM tool (bookings) — django-unfold      |
| `/cms/`     | Wagtail CMS admin (edit the public site)         |

## Repo layout

```
├── config/                 # Django project (settings split, urls, wsgi/asgi)
│   └── settings/           # base.py, dev.py, prod.py
├── cms/                    # Wagtail app: pages, StreamField blocks, seed command
├── bookings/               # Customers, Bookings, Venues, PuzzleSets + overlap rule
├── templates/              # base.html, header/footer includes
├── static/css/site.css     # custom animations layered on Tailwind
├── docker/entrypoint.sh    # wait-for-db, migrate, seed, collectstatic, gunicorn
├── nginx/templates/        # nginx config template (envsubst ${DOMAIN})
├── docker-compose.yml      # local dev: db + web (runserver)
├── docker-compose.prod.yml # prod: db + web + nginx + certbot
├── init-letsencrypt.sh     # one-time TLS bootstrap
├── Dockerfile
└── requirements.txt
```

## Local development

### Option A — Docker (Postgres, closest to prod)

```bash
cp .env.example .env        # edit if you like; defaults work for local
docker compose up --build
```

Visit http://localhost:8000/. Create an admin user:

```bash
docker compose exec web python manage.py createsuperuser
```

### Option B — bare virtualenv (sqlite)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DJANGO_SETTINGS_MODULE=config.settings.dev
python manage.py migrate
python manage.py seed_site          # creates Home + starter pages
python manage.py createsuperuser
python manage.py runserver
```

With no `DATABASE_URL` set, dev falls back to a local `db.sqlite3`.

## The double-booking rule (the important bit)

A `Venue` or `PuzzleSet` must never be booked for two overlapping time windows.
This is enforced **in Python via model validation** (not only a DB constraint),
so admin users get a clear, readable error:

- `BookingResource.clean()` — the model-level rule (also covers programmatic
  and existing-booking edits). Uses half-open intervals, so 10:00–11:00 and
  11:00–12:00 do **not** clash.
- `BookingResourceInlineFormSet.clean()` (in `bookings/admin.py`) — the
  authoritative check for the admin UI, because it sees the booking's *edited*
  start/end and all resource rows submitted together (including on a brand-new
  booking with no primary key yet).
- Cancelled bookings release their resources and don't block others.

Run the tests:

```bash
python manage.py test          # 9 tests, incl. an admin-POST overlap test
```

## Production deployment (single VPS)

1. Point DNS `A`/`AAAA` records for your domain (and `www.`) at the VPS.
2. Install Docker + the compose plugin.
3. Clone this repo and create `.env` from `.env.example`. **Set real secrets**
   (`DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD`, `DOMAIN`, `CERTBOT_EMAIL`).
   Generate a secret key:
   ```bash
   python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
   ```
4. Bootstrap TLS (obtains the first certificate and starts everything):
   ```bash
   STAGING=1 ./init-letsencrypt.sh   # test against LE staging first
   ./init-letsencrypt.sh             # then the real certificate
   ```
5. Thereafter:
   ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser
   ```

nginx terminates TLS and proxies to gunicorn; certbot renews certificates
automatically and nginx reloads every 6h to pick them up. The `web` entrypoint
runs migrations, seeds initial content (idempotent), and collects static on
each start.

### Prod settings notes

- `config.settings.prod`: `DEBUG=False`, Postgres required via `DATABASE_URL`,
  HSTS/secure cookies on, `SECURE_PROXY_SSL_HEADER` set for the nginx TLS
  offload.
- `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS` are derived from
  `DOMAIN` in `docker-compose.prod.yml`.

## Secrets

Never commit real secrets. `.env` is gitignored; only `.env.example`
(placeholders) is tracked. TLS material (`certbot/`, `*.pem`, `*.key`) is
gitignored too.

## Notes / next steps

- **Styling is intentionally brand-neutral** (placeholder indigo/cyan palette,
  Space Grotesk + Inter). Swap the palette in `templates/base.html`
  (`tailwind.config`) and `UNFOLD["COLORS"]` in `config/settings/base.py` for
  the real pathcipher.co.uk brand once assets are available.
- Tailwind is loaded via the Play CDN (no build pipeline, per brief). For
  maximum production performance you can later compile a static stylesheet and
  set `TAILWIND_CDN=False`.
- Suggested polish (per the brief's build order): a calendar view of bookings
  in the admin, richer public-site animation, a contact form (Wagtail form
  page).
- The Docker image/stack is config-validated; build & run it on a machine with
  a running Docker daemon.
```
