from datetime import datetime

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    Customer,
    Event,
    EventPuzzle,
    Puzzle,
    Venue,
    overlapping_puzzle_events,
    overlapping_venue_events,
)


def dt(y, m, d, hh, mm=0):
    return timezone.make_aware(datetime(y, m, d, hh, mm))


class VenueOverlapTests(TestCase):
    """An event has exactly one venue; a venue must not be double-booked."""

    def setUp(self):
        self.customer = Customer.objects.create(name="Acme Team")
        self.venue = Venue.objects.create(name="The Vault")

    def _event(self, start, end, venue=None, status=Event.Status.CONFIRMED,
               full_clean=True, name="Test event"):
        e = Event(
            name=name, customer=self.customer, venue=venue, start=start, end=end,
            status=status,
        )
        if full_clean:
            e.full_clean()
        e.save()
        return e

    def test_overlapping_same_venue_is_rejected(self):
        self._event(dt(2026, 8, 1, 10), dt(2026, 8, 1, 12), venue=self.venue)
        with self.assertRaises(ValidationError):
            self._event(dt(2026, 8, 1, 11), dt(2026, 8, 1, 13), venue=self.venue)

    def test_touching_windows_are_allowed(self):
        self._event(dt(2026, 8, 1, 10), dt(2026, 8, 1, 11), venue=self.venue)
        self._event(dt(2026, 8, 1, 11), dt(2026, 8, 1, 12), venue=self.venue)  # no raise
        self.assertEqual(self.venue.events.count(), 2)

    def test_cancelled_event_does_not_block_venue(self):
        self._event(
            dt(2026, 8, 1, 10), dt(2026, 8, 1, 12), venue=self.venue,
            status=Event.Status.CANCELLED,
        )
        self._event(dt(2026, 8, 1, 10), dt(2026, 8, 1, 12), venue=self.venue)  # no raise

    def test_different_venues_no_conflict(self):
        other_venue = Venue.objects.create(name="The Lab")
        self._event(dt(2026, 8, 1, 10), dt(2026, 8, 1, 12), venue=self.venue)
        self._event(dt(2026, 8, 1, 10), dt(2026, 8, 1, 12), venue=other_venue)

    def test_helper_excludes_self_event(self):
        e = self._event(dt(2026, 8, 1, 10), dt(2026, 8, 1, 12), venue=self.venue)
        clashes = overlapping_venue_events(
            venue_id=self.venue.id, start=e.start, end=e.end, exclude_event_id=e.id
        )
        self.assertFalse(clashes.exists())

    def test_end_must_be_after_start(self):
        e = Event(
            name="Bad window", customer=self.customer,
            start=dt(2026, 8, 1, 12), end=dt(2026, 8, 1, 10),
        )
        with self.assertRaises(ValidationError):
            e.full_clean()


class PuzzleOverlapAndReuseTests(TestCase):
    """
    Physical puzzles can't be double-booked (like a venue); online-only
    puzzles have no such limit. Separately, a puzzle shouldn't normally be
    reused across a single customer's events (soft rule, overridable).
    """

    def setUp(self):
        self.customer = Customer.objects.create(name="Acme Team")
        self.other_customer = Customer.objects.create(name="Beta Team")
        self.physical_puzzle = Puzzle.objects.create(
            name="Heist Kit", hardware_required="Lockbox\nUV torch"
        )
        self.online_puzzle = Puzzle.objects.create(name="Web Riddle")

    def _event(self, start, end, status=Event.Status.CONFIRMED, customer=None,
               name="Test event"):
        return Event.objects.create(
            name=name, customer=customer or self.customer, start=start, end=end,
            status=status,
        )

    def _use(self, event, puzzle, allow_reuse=False, full_clean=True):
        ep = EventPuzzle(event=event, puzzle=puzzle, allow_reuse=allow_reuse)
        if full_clean:
            ep.full_clean()
        ep.save()
        return ep

    # --- physical vs online overlap ---

    def test_physical_puzzle_overlap_is_rejected(self):
        e1 = self._event(dt(2026, 8, 1, 10), dt(2026, 8, 1, 12))
        self._use(e1, self.physical_puzzle)
        e2 = self._event(dt(2026, 8, 1, 11), dt(2026, 8, 1, 13), customer=self.other_customer)
        with self.assertRaises(ValidationError):
            self._use(e2, self.physical_puzzle)

    def test_online_only_puzzle_overlap_is_allowed(self):
        e1 = self._event(dt(2026, 8, 1, 10), dt(2026, 8, 1, 12))
        self._use(e1, self.online_puzzle)
        e2 = self._event(dt(2026, 8, 1, 11), dt(2026, 8, 1, 13), customer=self.other_customer)
        self._use(e2, self.online_puzzle)  # no raise — online puzzles can run anywhere

    def test_helper_returns_empty_for_online_puzzle(self):
        e1 = self._event(dt(2026, 8, 1, 10), dt(2026, 8, 1, 12))
        self._use(e1, self.online_puzzle)
        clashes = overlapping_puzzle_events(
            puzzle=self.online_puzzle, start=e1.start, end=e1.end,
        )
        self.assertFalse(clashes.exists())

    def test_cancelled_event_does_not_block_physical_puzzle(self):
        e1 = self._event(
            dt(2026, 8, 1, 10), dt(2026, 8, 1, 12), status=Event.Status.CANCELLED
        )
        EventPuzzle.objects.create(event=e1, puzzle=self.physical_puzzle)
        e2 = self._event(dt(2026, 8, 1, 10), dt(2026, 8, 1, 12), customer=self.other_customer)
        self._use(e2, self.physical_puzzle)  # no raise

    # --- reuse across a customer's events ---

    def test_puzzle_reused_for_same_customer_is_rejected(self):
        e1 = self._event(dt(2026, 8, 1, 10), dt(2026, 8, 1, 12))
        self._use(e1, self.online_puzzle)
        e2 = self._event(dt(2026, 9, 1, 10), dt(2026, 9, 1, 12))  # same customer
        with self.assertRaises(ValidationError):
            self._use(e2, self.online_puzzle)

    def test_same_puzzle_different_customers_is_allowed(self):
        e1 = self._event(dt(2026, 8, 1, 10), dt(2026, 8, 1, 12))
        self._use(e1, self.online_puzzle)
        e2 = self._event(dt(2026, 9, 1, 10), dt(2026, 9, 1, 12), customer=self.other_customer)
        self._use(e2, self.online_puzzle)  # different customer, fine

    def test_puzzle_reuse_can_be_overridden(self):
        e1 = self._event(dt(2026, 8, 1, 10), dt(2026, 8, 1, 12))
        self._use(e1, self.online_puzzle)
        e2 = self._event(dt(2026, 9, 1, 10), dt(2026, 9, 1, 12))
        self._use(e2, self.online_puzzle, allow_reuse=True)  # no raise

    def test_puzzle_reuse_ignores_cancelled_events(self):
        e1 = self._event(
            dt(2026, 8, 1, 10), dt(2026, 8, 1, 12), status=Event.Status.CANCELLED
        )
        EventPuzzle.objects.create(event=e1, puzzle=self.online_puzzle)
        e2 = self._event(dt(2026, 9, 1, 10), dt(2026, 9, 1, 12))
        self._use(e2, self.online_puzzle)  # cancelled e1 doesn't count

    def test_override_propagates_to_the_other_conflicting_event(self):
        """
        Ticking "allow reuse" on the new event's row must also mark the
        *original* event's row as allow_reuse, so re-validating that event
        later doesn't re-trigger the same conflict from its own side.
        """
        e1 = self._event(dt(2026, 8, 1, 10), dt(2026, 8, 1, 12))
        ep1 = self._use(e1, self.online_puzzle)
        self.assertFalse(ep1.allow_reuse)

        e2 = self._event(dt(2026, 9, 1, 10), dt(2026, 9, 1, 12))
        self._use(e2, self.online_puzzle, allow_reuse=True)

        ep1.refresh_from_db()
        self.assertTrue(ep1.allow_reuse)

        # Re-validating e1's own row must not raise now that it carries the
        # override too (this is exactly the bug being guarded against).
        ep1.full_clean()

    def test_override_propagation_ignores_cancelled_events(self):
        e1 = self._event(dt(2026, 8, 1, 10), dt(2026, 8, 1, 12))
        ep1 = self._use(e1, self.online_puzzle)
        e_other_customer = self._event(
            dt(2026, 8, 15, 10), dt(2026, 8, 15, 12), customer=self.other_customer
        )
        # Same puzzle, different customer: unrelated, must not be touched.
        ep_other = self._use(e_other_customer, self.online_puzzle)

        e2 = self._event(dt(2026, 9, 1, 10), dt(2026, 9, 1, 12))
        self._use(e2, self.online_puzzle, allow_reuse=True)

        ep1.refresh_from_db()
        ep_other.refresh_from_db()
        self.assertTrue(ep1.allow_reuse)
        self.assertFalse(ep_other.allow_reuse)  # different customer, untouched

    def test_duplicate_puzzle_on_same_event_is_rejected(self):
        e = self._event(dt(2026, 8, 1, 10), dt(2026, 8, 1, 12))
        self._use(e, self.online_puzzle)
        with self.assertRaises(ValidationError):
            EventPuzzle(event=e, puzzle=self.online_puzzle).full_clean()


class PuzzleFieldTests(TestCase):
    def test_hardware_required_list_property(self):
        p = Puzzle.objects.create(
            name="Kit", hardware_required="Flashlight\n\nUV torch\nSpare batteries\n"
        )
        self.assertEqual(p.hardware_required_list, ["Flashlight", "UV torch", "Spare batteries"])

    def test_answer_restrictions_defaults_to_unrestricted(self):
        p = Puzzle.objects.create(name="Kit")
        self.assertFalse(p.answer_restrictions)

    def test_has_physical_components_is_derived_from_hardware_required(self):
        online = Puzzle.objects.create(name="No hardware")
        self.assertFalse(online.has_physical_components)

        physical = Puzzle.objects.create(name="Needs kit", hardware_required="UV torch")
        self.assertTrue(physical.has_physical_components)


class AdminEventFormTests(TestCase):
    """The UI path: a brand-new (pk-less) event must still be validated."""

    def setUp(self):
        self.customer = Customer.objects.create(name="Acme Team")
        self.venue = Venue.objects.create(name="The Vault")
        self.puzzle = Puzzle.objects.create(name="Heist Kit", hardware_required="Lockbox")
        admin_user = get_user_model().objects.create_superuser("boss", "boss@example.com", "pw")
        self.client.force_login(admin_user)

        self.existing = Event.objects.create(
            name="Existing event", customer=self.customer, venue=self.venue,
            start=dt(2026, 9, 1, 10), end=dt(2026, 9, 1, 12),
            status=Event.Status.CONFIRMED,
        )

    def _payload(self, start, end, venue=None, name="New event", **row):
        data = {
            "name": name,
            "customer": self.customer.pk,
            "venue": venue.pk if venue else "",
            "start_0": start.strftime("%Y-%m-%d"), "start_1": start.strftime("%H:%M:%S"),
            "end_0": end.strftime("%Y-%m-%d"), "end_1": end.strftime("%H:%M:%S"),
            "status": Event.Status.CONFIRMED, "notes": "",
            "event_puzzles-TOTAL_FORMS": "1", "event_puzzles-INITIAL_FORMS": "0",
            "event_puzzles-MIN_NUM_FORMS": "0", "event_puzzles-MAX_NUM_FORMS": "1000",
            "event_puzzles-0-puzzle": row.get("puzzle", ""),
        }
        if row.get("allow_reuse"):
            data["event_puzzles-0-allow_reuse"] = "on"
        return data

    def test_admin_add_overlapping_venue_event_is_rejected(self):
        url = reverse("admin:bookings_event_add")
        resp = self.client.post(
            url, self._payload(dt(2026, 9, 1, 11), dt(2026, 9, 1, 13), venue=self.venue)
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "already booked for an overlapping")
        self.assertEqual(Event.objects.count(), 1)

    def test_admin_add_non_overlapping_venue_event_succeeds(self):
        url = reverse("admin:bookings_event_add")
        resp = self.client.post(
            url, self._payload(dt(2026, 9, 1, 12), dt(2026, 9, 1, 13), venue=self.venue)
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Event.objects.count(), 2)

    def test_admin_puzzle_reuse_blocked_then_overridable(self):
        EventPuzzle.objects.create(event=self.existing, puzzle=self.puzzle)
        url = reverse("admin:bookings_event_add")

        blocked = self.client.post(
            url,
            self._payload(dt(2026, 11, 1, 10), dt(2026, 11, 1, 12), puzzle=self.puzzle.pk),
        )
        self.assertEqual(blocked.status_code, 200)
        self.assertContains(blocked, "can only be used once per customer")
        self.assertEqual(Event.objects.filter(start=dt(2026, 11, 1, 10)).count(), 0)

        ok = self.client.post(
            url,
            self._payload(
                dt(2026, 11, 1, 10), dt(2026, 11, 1, 12),
                puzzle=self.puzzle.pk, allow_reuse=True,
            ),
        )
        self.assertEqual(ok.status_code, 302)
        self.assertEqual(Event.objects.filter(start=dt(2026, 11, 1, 10)).count(), 1)

        # The override must have propagated back to the original event's row.
        original_link = self.existing.event_puzzles.get(puzzle=self.puzzle)
        self.assertTrue(original_link.allow_reuse)
