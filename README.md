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
| CMS + public site  | Wagtail 6.3, Django templates + Tailwind (compiled) + htmx |
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
├── bookings/               # Customers, Events, Venues, Puzzles + overlap rule
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

## Front-end CSS (Tailwind)

Styling is a **compiled, vendored** Tailwind stylesheet
(`static/css/tailwind.build.css`) — no runtime CDN, so the site is fully
self-contained. The brand theme (Pathcipher teal, Lato) lives in
`tailwind.config.js`. Rebuild it after changing template classes:

```bash
npm install          # once
npm run build:css    # or: npm run watch:css  (rebuild on save)
```

`config.settings.dev` uses the compiled sheet too, so dev is styled offline.
For quick prototyping you can opt into the Tailwind Play CDN with
`DJANGO_TAILWIND_CDN=True` (needs `cdn.tailwindcss.com` reachable).

## The bookings domain (the important bit)

An `Event` belongs to a `Customer`, has exactly one `Venue` (a direct field,
not a many-to-many), and uses any number of `Puzzle`s via the `EventPuzzle`
join (with a "count of puzzles" column on the events list). All overlap/reuse
rules are enforced **in Python via model validation** (not only a DB
constraint), so admin users get a clear, readable error, using half-open
intervals throughout (10:00–11:00 and 11:00–12:00 do **not** clash):

- **Venue double-booking** — `Event.clean()`. A venue can't host two
  overlapping (non-cancelled) events.
- **Physical-puzzle double-booking** — `EventPuzzle.clean()`. A `Puzzle` with
  `has_physical_components=True` can't be used by two overlapping events (its
  props can only be in one place at once). Puzzles without physical
  components (purely online) have no such limit.
- **Puzzle reuse across a customer's events** — `EventPuzzle.clean()`, a
  *soft* rule: a repeat customer normally shouldn't get the same puzzle twice
  (answer/narrative spoiling). Tick **"Allow reuse for this customer"** on the
  row to override it — and that override automatically propagates to the
  *other* conflicting event's row too (`EventPuzzle.save()`), so re-opening
  and re-saving that other event doesn't re-trigger the same conflict from
  its side.
- `EventPuzzleInlineFormSet.clean()` (in `bookings/admin.py`) mirrors the
  puzzle rules for the admin UI, since it sees the event's *edited* start/end
  and all puzzle rows submitted together, including on a brand-new event with
  no primary key yet. The venue rule is a plain model field, so it surfaces as
  a normal "venue" field error via Django's standard form validation.
- Cancelled events release their venue/puzzles and don't block others.

A `Puzzle` also has an `answer_restrictions` flag (warning shown in the list
if the puzzle needs one exact answer; a tick if it accepts a flexible range),
`hardware_required` (free text, one item per line), tags, an optional GitHub
link, and arbitrary file attachments (props lists, artwork, etc. via the
`PuzzleFile` inline).

Run the tests:

```bash
python manage.py test          # 23 tests, incl. admin-POST and override-propagation cases
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

### Run on boot (systemd)

To have the production stack start automatically on boot (and stop cleanly on
shutdown), install the provided systemd service:

```bash
sudo ./deploy/install-service.sh          # generates + enables 'pathcipher.service'
sudo systemctl start pathcipher           # bring it up now
```

The script auto-detects the project path and the Docker Compose command and
writes an absolute-path unit to `/etc/systemd/system/`. Manage it with
`systemctl start|stop|status pathcipher` and view logs with
`journalctl -u pathcipher`. The unit runs `up -d` (no rebuild) so boot stays
fast; deploy new code with `git pull && docker compose -f docker-compose.prod.yml up -d --build`.

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

- **The public site follows the Pathcipher brand** (teal `#138275` on light,
  mint accent, Lato) with the site's own copy. Tweak the palette in
  `tailwind.config.js` (+ the CDN mirror in `templates/base.html`) and
  `UNFOLD["COLORS"]` in `config/settings/base.py`. Real page copy is seeded by
  `python manage.py seed_site` and fully editable in the Wagtail CMS.
- Suggested polish (per the brief's build order): a calendar view of bookings
  in the admin, a working contact form (Wagtail form page), and real imagery
  from the brand.
- The Docker image/stack is config-validated; build & run it on a machine with
  a running Docker daemon.
```
