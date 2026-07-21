from datetime import datetime

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    Booking,
    BookingResource,
    Customer,
    PuzzleSet,
    Venue,
    overlapping_resource_bookings,
)


def dt(y, m, d, hh, mm=0):
    return timezone.make_aware(datetime(y, m, d, hh, mm))


class OverlapValidationTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name="Acme Team")
        self.venue = Venue.objects.create(name="The Vault")
        self.puzzle = PuzzleSet.objects.create(name="Heist Kit")

    def _booking(self, start, end, status=Booking.Status.CONFIRMED):
        return Booking.objects.create(
            customer=self.customer, start=start, end=end, status=status
        )

    def _reserve(self, booking, *, venue=None, puzzle_set=None, full_clean=True):
        br = BookingResource(booking=booking, venue=venue, puzzle_set=puzzle_set)
        if full_clean:
            br.full_clean()
        br.save()
        return br

    # --- the core rule ---

    def test_overlapping_same_venue_is_rejected(self):
        b1 = self._booking(dt(2026, 8, 1, 10), dt(2026, 8, 1, 12))
        self._reserve(b1, venue=self.venue)

        b2 = self._booking(dt(2026, 8, 1, 11), dt(2026, 8, 1, 13))
        with self.assertRaises(ValidationError):
            self._reserve(b2, venue=self.venue)

    def test_touching_windows_are_allowed(self):
        # 10–11 then 11–12 share only the boundary: half-open, no overlap.
        b1 = self._booking(dt(2026, 8, 1, 10), dt(2026, 8, 1, 11))
        self._reserve(b1, venue=self.venue)

        b2 = self._booking(dt(2026, 8, 1, 11), dt(2026, 8, 1, 12))
        self._reserve(b2, venue=self.venue)  # should not raise

        self.assertEqual(self.venue.booking_links.count(), 2)

    def test_different_resource_no_conflict(self):
        b1 = self._booking(dt(2026, 8, 1, 10), dt(2026, 8, 1, 12))
        self._reserve(b1, venue=self.venue)

        b2 = self._booking(dt(2026, 8, 1, 10), dt(2026, 8, 1, 12))
        self._reserve(b2, puzzle_set=self.puzzle)  # different resource, fine

    def test_cancelled_booking_does_not_block(self):
        b1 = self._booking(
            dt(2026, 8, 1, 10), dt(2026, 8, 1, 12), status=Booking.Status.CANCELLED
        )
        # A cancelled booking may still carry its resource rows.
        BookingResource.objects.create(booking=b1, venue=self.venue)

        b2 = self._booking(dt(2026, 8, 1, 10), dt(2026, 8, 1, 12))
        self._reserve(b2, venue=self.venue)  # should not raise

    def test_helper_excludes_self_booking(self):
        b1 = self._booking(dt(2026, 8, 1, 10), dt(2026, 8, 1, 12))
        self._reserve(b1, venue=self.venue)
        clashes = overlapping_resource_bookings(
            venue=self.venue,
            start=b1.start,
            end=b1.end,
            exclude_booking_id=b1.id,
        )
        self.assertFalse(clashes.exists())

    # --- shape rules ---

    def test_exactly_one_resource_required(self):
        b1 = self._booking(dt(2026, 8, 1, 10), dt(2026, 8, 1, 12))
        both = BookingResource(booking=b1, venue=self.venue, puzzle_set=self.puzzle)
        with self.assertRaises(ValidationError):
            both.full_clean()

        neither = BookingResource(booking=b1)
        with self.assertRaises(ValidationError):
            neither.full_clean()

    def test_end_must_be_after_start(self):
        b = Booking(
            customer=self.customer,
            start=dt(2026, 8, 1, 12),
            end=dt(2026, 8, 1, 10),
        )
        with self.assertRaises(ValidationError):
            b.full_clean()


class AdminInlineOverlapTests(TestCase):
    """The UI path: a brand-new (pk-less) booking must still be blocked."""

    def setUp(self):
        self.customer = Customer.objects.create(name="Acme Team")
        self.venue = Venue.objects.create(name="The Vault")
        admin_user = get_user_model().objects.create_superuser(
            "boss", "boss@example.com", "pw"
        )
        self.client.force_login(admin_user)

        # An existing confirmed booking holding the venue 10:00–12:00.
        existing = Booking.objects.create(
            customer=self.customer,
            start=dt(2026, 9, 1, 10),
            end=dt(2026, 9, 1, 12),
            status=Booking.Status.CONFIRMED,
        )
        BookingResource.objects.create(booking=existing, venue=self.venue)

    def _add_payload(self, start, end):
        return {
            "customer": self.customer.pk,
            "start_0": start.strftime("%Y-%m-%d"),
            "start_1": start.strftime("%H:%M:%S"),
            "end_0": end.strftime("%Y-%m-%d"),
            "end_1": end.strftime("%H:%M:%S"),
            "status": Booking.Status.CONFIRMED,
            "notes": "",
            # Inline management form + one resource row (the venue).
            "resources-TOTAL_FORMS": "1",
            "resources-INITIAL_FORMS": "0",
            "resources-MIN_NUM_FORMS": "0",
            "resources-MAX_NUM_FORMS": "1000",
            "resources-0-venue": self.venue.pk,
            "resources-0-puzzle_set": "",
        }

    def test_admin_add_overlapping_booking_is_rejected(self):
        url = reverse("admin:bookings_booking_add")
        # 11:00–13:00 overlaps the existing 10:00–12:00 on the same venue.
        resp = self.client.post(
            url, self._add_payload(dt(2026, 9, 1, 11), dt(2026, 9, 1, 13))
        )
        # Re-rendered form (200) with an error, and no second booking created.
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "already booked for an overlapping window")
        self.assertEqual(Booking.objects.count(), 1)

    def test_admin_add_non_overlapping_booking_succeeds(self):
        url = reverse("admin:bookings_booking_add")
        # 12:00–13:00 touches the boundary only — allowed.
        resp = self.client.post(
            url, self._add_payload(dt(2026, 9, 1, 12), dt(2026, 9, 1, 13))
        )
        self.assertEqual(resp.status_code, 302)  # saved -> redirect to changelist
        self.assertEqual(Booking.objects.count(), 2)
