from datetime import datetime

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    Customer,
    Event,
    EventResource,
    Puzzle,
    Venue,
    overlapping_resource_events,
)


def dt(y, m, d, hh, mm=0):
    return timezone.make_aware(datetime(y, m, d, hh, mm))


class OverlapValidationTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name="Acme Team")
        self.other_customer = Customer.objects.create(name="Beta Team")
        self.venue = Venue.objects.create(name="The Vault")
        self.puzzle = Puzzle.objects.create(name="Heist Kit")

    def _event(self, start, end, status=Event.Status.CONFIRMED, customer=None):
        return Event.objects.create(
            customer=customer or self.customer, start=start, end=end, status=status
        )

    def _reserve(self, event, *, venue=None, puzzle=None, allow_reuse=False,
                 full_clean=True):
        r = EventResource(event=event, venue=venue, puzzle=puzzle,
                          allow_reuse=allow_reuse)
        if full_clean:
            r.full_clean()
        r.save()
        return r

    # --- Rule 1: time-overlap on a resource ---

    def test_overlapping_same_venue_is_rejected(self):
        e1 = self._event(dt(2026, 8, 1, 10), dt(2026, 8, 1, 12))
        self._reserve(e1, venue=self.venue)
        e2 = self._event(dt(2026, 8, 1, 11), dt(2026, 8, 1, 13))
        with self.assertRaises(ValidationError):
            self._reserve(e2, venue=self.venue)

    def test_touching_windows_are_allowed(self):
        e1 = self._event(dt(2026, 8, 1, 10), dt(2026, 8, 1, 11))
        self._reserve(e1, venue=self.venue)
        e2 = self._event(dt(2026, 8, 1, 11), dt(2026, 8, 1, 12))
        self._reserve(e2, venue=self.venue)  # should not raise
        self.assertEqual(self.venue.event_links.count(), 2)

    def test_cancelled_event_does_not_block(self):
        e1 = self._event(
            dt(2026, 8, 1, 10), dt(2026, 8, 1, 12), status=Event.Status.CANCELLED
        )
        EventResource.objects.create(event=e1, venue=self.venue)
        e2 = self._event(dt(2026, 8, 1, 10), dt(2026, 8, 1, 12))
        self._reserve(e2, venue=self.venue)  # should not raise

    def test_helper_excludes_self_event(self):
        e1 = self._event(dt(2026, 8, 1, 10), dt(2026, 8, 1, 12))
        self._reserve(e1, venue=self.venue)
        clashes = overlapping_resource_events(
            venue=self.venue, start=e1.start, end=e1.end, exclude_event_id=e1.id
        )
        self.assertFalse(clashes.exists())

    # --- Rule 2: a puzzle must not be reused across a customer's events ---

    def test_puzzle_reused_for_same_customer_is_rejected(self):
        e1 = self._event(dt(2026, 8, 1, 10), dt(2026, 8, 1, 12))
        self._reserve(e1, puzzle=self.puzzle)
        # Different, non-overlapping day for the same customer.
        e2 = self._event(dt(2026, 9, 1, 10), dt(2026, 9, 1, 12))
        with self.assertRaises(ValidationError):
            self._reserve(e2, puzzle=self.puzzle)

    def test_same_puzzle_different_customers_is_allowed(self):
        e1 = self._event(dt(2026, 8, 1, 10), dt(2026, 8, 1, 12))
        self._reserve(e1, puzzle=self.puzzle)
        e2 = self._event(
            dt(2026, 9, 1, 10), dt(2026, 9, 1, 12), customer=self.other_customer
        )
        self._reserve(e2, puzzle=self.puzzle)  # different customer, fine

    def test_puzzle_reuse_can_be_overridden(self):
        e1 = self._event(dt(2026, 8, 1, 10), dt(2026, 8, 1, 12))
        self._reserve(e1, puzzle=self.puzzle)
        e2 = self._event(dt(2026, 9, 1, 10), dt(2026, 9, 1, 12))
        # allow_reuse ticked -> the soft rule is bypassed.
        self._reserve(e2, puzzle=self.puzzle, allow_reuse=True)

    def test_puzzle_reuse_ignores_cancelled_events(self):
        e1 = self._event(
            dt(2026, 8, 1, 10), dt(2026, 8, 1, 12), status=Event.Status.CANCELLED
        )
        EventResource.objects.create(event=e1, puzzle=self.puzzle)
        e2 = self._event(dt(2026, 9, 1, 10), dt(2026, 9, 1, 12))
        self._reserve(e2, puzzle=self.puzzle)  # cancelled e1 doesn't count

    # --- shape rules ---

    def test_exactly_one_resource_required(self):
        e1 = self._event(dt(2026, 8, 1, 10), dt(2026, 8, 1, 12))
        both = EventResource(event=e1, venue=self.venue, puzzle=self.puzzle)
        with self.assertRaises(ValidationError):
            both.full_clean()
        neither = EventResource(event=e1)
        with self.assertRaises(ValidationError):
            neither.full_clean()

    def test_end_must_be_after_start(self):
        e = Event(customer=self.customer, start=dt(2026, 8, 1, 12), end=dt(2026, 8, 1, 10))
        with self.assertRaises(ValidationError):
            e.full_clean()


class AdminInlineOverlapTests(TestCase):
    """The UI path: a brand-new (pk-less) event must still be validated."""

    def setUp(self):
        self.customer = Customer.objects.create(name="Acme Team")
        self.venue = Venue.objects.create(name="The Vault")
        self.puzzle = Puzzle.objects.create(name="Heist Kit")
        admin_user = get_user_model().objects.create_superuser("boss", "boss@example.com", "pw")
        self.client.force_login(admin_user)

        existing = Event.objects.create(
            customer=self.customer, start=dt(2026, 9, 1, 10), end=dt(2026, 9, 1, 12),
            status=Event.Status.CONFIRMED,
        )
        EventResource.objects.create(event=existing, venue=self.venue)

    def _payload(self, start, end, **row):
        data = {
            "customer": self.customer.pk,
            "start_0": start.strftime("%Y-%m-%d"), "start_1": start.strftime("%H:%M:%S"),
            "end_0": end.strftime("%Y-%m-%d"), "end_1": end.strftime("%H:%M:%S"),
            "status": Event.Status.CONFIRMED, "notes": "",
            "resources-TOTAL_FORMS": "1", "resources-INITIAL_FORMS": "0",
            "resources-MIN_NUM_FORMS": "0", "resources-MAX_NUM_FORMS": "1000",
            "resources-0-venue": row.get("venue", ""),
            "resources-0-puzzle": row.get("puzzle", ""),
        }
        if row.get("allow_reuse"):
            data["resources-0-allow_reuse"] = "on"
        return data

    def test_admin_add_overlapping_event_is_rejected(self):
        url = reverse("admin:bookings_event_add")
        resp = self.client.post(
            url, self._payload(dt(2026, 9, 1, 11), dt(2026, 9, 1, 13), venue=self.venue.pk)
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "already booked for an overlapping window")
        self.assertEqual(Event.objects.count(), 1)

    def test_admin_add_non_overlapping_event_succeeds(self):
        url = reverse("admin:bookings_event_add")
        resp = self.client.post(
            url, self._payload(dt(2026, 9, 1, 12), dt(2026, 9, 1, 13), venue=self.venue.pk)
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Event.objects.count(), 2)

    def test_admin_puzzle_reuse_blocked_then_overridable(self):
        # Give the customer an event already using the puzzle.
        e = Event.objects.create(
            customer=self.customer, start=dt(2026, 10, 1, 10), end=dt(2026, 10, 1, 12),
            status=Event.Status.CONFIRMED,
        )
        EventResource.objects.create(event=e, puzzle=self.puzzle)
        url = reverse("admin:bookings_event_add")

        blocked = self.client.post(
            url, self._payload(dt(2026, 11, 1, 10), dt(2026, 11, 1, 12), puzzle=self.puzzle.pk)
        )
        self.assertEqual(blocked.status_code, 200)
        self.assertContains(blocked, "can only be used once per customer")
        self.assertEqual(Event.objects.filter(start=dt(2026, 11, 1, 10)).count(), 0)

        ok = self.client.post(
            url,
            self._payload(dt(2026, 11, 1, 10), dt(2026, 11, 1, 12),
                          puzzle=self.puzzle.pk, allow_reuse=True),
        )
        self.assertEqual(ok.status_code, 302)
        self.assertEqual(Event.objects.filter(start=dt(2026, 11, 1, 10)).count(), 1)
