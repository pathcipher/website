"""
Events domain model for the internal PM tool.

Rules enforced in Python (via ``clean()`` / ``full_clean()``) so admin users
get clear, human-readable errors rather than raw database IntegrityErrors:

1. A Venue must never be double-booked for overlapping time windows
   (an Event has exactly one venue).
2. A Puzzle with physical components must never be used by two overlapping
   events at once (online-only puzzles have no such limit — they can run
   at multiple events simultaneously).
3. A given Puzzle should not normally be used by more than one event for the
   same customer (answer/narrative spoiling) — a soft rule, overridable via
   ``EventPuzzle.allow_reuse``.
"""
import os

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from taggit.managers import TaggableManager


class Customer(models.Model):
    name = models.CharField(max_length=200)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class VenueQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)


class Venue(models.Model):
    """A bookable location/room. An event has exactly one venue."""

    name = models.CharField(max_length=200)
    address = models.TextField(blank=True)
    capacity = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    objects = VenueQuerySet.as_manager()

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


def puzzle_file_upload_to(instance, filename):
    return f"puzzle_files/{instance.puzzle_id}/{filename}"


class Puzzle(models.Model):
    """
    A puzzle used in events. May involve physical props/kit, or be purely
    online — that distinction drives whether it can be double-booked.
    """

    name = models.CharField(max_length=200)
    has_physical_components = models.BooleanField(
        default=True,
        help_text="Tick if this puzzle involves physical props/kit that can "
                  "only be in one place at a time. Untick for online-only "
                  "puzzles, which can run at multiple events simultaneously.",
    )
    answer_restrictions = models.BooleanField(
        default=False,
        verbose_name="Answer restrictions",
        help_text="Tick if the puzzle requires one exact answer. Leave "
                  "unticked if it accepts a flexible range of answers.",
    )
    answer = models.TextField(
        blank=True,
        help_text="The puzzle's solution (or accepted answers).",
    )
    hardware_required = models.TextField(
        blank=True,
        verbose_name="Hardware required",
        help_text="One item per line.",
    )
    github_url = models.URLField(
        blank=True,
        verbose_name="GitHub link",
        help_text="Optional link to the puzzle's repository.",
    )
    tags = TaggableManager(blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Puzzle"

    def __str__(self):
        return self.name

    @property
    def hardware_required_list(self):
        return [
            line.strip() for line in self.hardware_required.splitlines()
            if line.strip()
        ]


class PuzzleFile(models.Model):
    """An arbitrary file attached to a puzzle (props list, artwork, PDF, ...)."""

    puzzle = models.ForeignKey(Puzzle, on_delete=models.CASCADE, related_name="files")
    file = models.FileField(upload_to=puzzle_file_upload_to)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return os.path.basename(self.file.name)


class Event(models.Model):
    class Status(models.TextChoices):
        ENQUIRY = "enquiry", "Enquiry"
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"
        COMPLETED = "completed", "Completed"

    name = models.CharField(max_length=200)
    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name="events"
    )
    venue = models.ForeignKey(
        Venue, null=True, blank=True, on_delete=models.PROTECT,
        related_name="events",
    )
    start = models.DateTimeField()
    end = models.DateTimeField()
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ENQUIRY
    )
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start"]
        indexes = [
            models.Index(fields=["start", "end"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        when = timezone.localtime(self.start).strftime("%d %b %Y %H:%M") if self.start else "?"
        return f"{self.name} ({when})"

    @property
    def blocks_resources(self):
        """Cancelled events don't hold their venue/puzzles."""
        return self.status != self.Status.CANCELLED

    def clean(self):
        super().clean()
        if self.start and self.end and self.end <= self.start:
            raise ValidationError(
                {"end": "End time must be after the start time."}
            )

        if self.venue_id and self.start and self.end and self.blocks_resources:
            clash = overlapping_venue_events(
                venue_id=self.venue_id, start=self.start, end=self.end,
                exclude_event_id=self.pk,
            ).first()
            if clash is not None:
                raise ValidationError({
                    "venue": "{venue} is already booked for an overlapping "
                    "time ({start} – {end}) by “{other}”.".format(
                        venue=self.venue,
                        start=timezone.localtime(clash.start).strftime("%d %b %H:%M"),
                        end=timezone.localtime(clash.end).strftime("%d %b %H:%M"),
                        other=clash,
                    )
                })


def overlapping_venue_events(*, venue_id, start, end, exclude_event_id=None):
    """
    Events that would clash with a [start, end) window at the given venue. A
    clash is an overlapping window on an event that still holds its venue
    (i.e. not cancelled). Half-open intervals: touching end-to-start does not
    count as an overlap.
    """
    qs = Event.objects.filter(venue_id=venue_id).exclude(
        status=Event.Status.CANCELLED
    ).filter(start__lt=end, end__gt=start)
    if exclude_event_id is not None:
        qs = qs.exclude(pk=exclude_event_id)
    return qs


def overlapping_puzzle_events(*, puzzle, start, end, exclude_event_id=None):
    """
    EventPuzzle rows that would clash with a [start, end) window for a puzzle
    with physical components (online-only puzzles have no capacity limit, so
    they can never clash).
    """
    if not puzzle.has_physical_components:
        return EventPuzzle.objects.none()

    qs = EventPuzzle.objects.select_related("event", "event__customer").filter(
        puzzle=puzzle
    ).exclude(event__status=Event.Status.CANCELLED)
    qs = qs.filter(event__start__lt=end, event__end__gt=start)
    if exclude_event_id is not None:
        qs = qs.exclude(event_id=exclude_event_id)
    return qs


def puzzle_events_for_customer(*, puzzle, customer, exclude_event_id=None):
    """
    EventPuzzle rows attaching ``puzzle`` to a (non-cancelled) event for
    ``customer``. Used to stop the same puzzle being reused across a
    customer's events.
    """
    qs = EventPuzzle.objects.select_related("event").filter(
        puzzle=puzzle, event__customer=customer
    ).exclude(event__status=Event.Status.CANCELLED)
    if exclude_event_id is not None:
        qs = qs.exclude(event_id=exclude_event_id)
    return qs


class EventPuzzle(models.Model):
    """A puzzle used by an event. An event can use many puzzles."""

    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name="event_puzzles"
    )
    puzzle = models.ForeignKey(
        Puzzle, on_delete=models.PROTECT, related_name="event_links"
    )
    allow_reuse = models.BooleanField(
        default=False,
        verbose_name="Allow reuse for this customer",
        help_text="Tick to permit using this puzzle even though it's already "
                  "used by another event for the same customer.",
    )

    class Meta:
        verbose_name = "Puzzle used"
        verbose_name_plural = "Puzzles used"
        constraints = [
            models.UniqueConstraint(fields=["event", "puzzle"], name="uniq_event_puzzle"),
        ]

    def __str__(self):
        return f"{self.puzzle} (for {self.event})"

    def clean(self):
        super().clean()

        event = self.event if self.event_id else None
        if not event or not event.start or not event.end:
            return
        if not event.blocks_resources:
            return  # cancelled events don't reserve anything

        # Rule: a puzzle with physical components can't overlap another event.
        clashes = overlapping_puzzle_events(
            puzzle=self.puzzle, start=event.start, end=event.end,
            exclude_event_id=event.id,
        ).exclude(pk=self.pk)
        first = clashes.first()
        if first is not None:
            other = first.event
            raise ValidationError(
                "“{puzzle}” has physical components and is already in use "
                "for an overlapping time ({start} – {end}) by “{other}”.".format(
                    puzzle=self.puzzle,
                    start=timezone.localtime(other.start).strftime("%d %b %H:%M"),
                    end=timezone.localtime(other.end).strftime("%d %b %H:%M"),
                    other=other,
                )
            )

        # Rule: a puzzle must not be reused across a customer's events.
        # This is a soft rule — tick ``allow_reuse`` to override it.
        if not self.allow_reuse:
            reused = puzzle_events_for_customer(
                puzzle=self.puzzle, customer=event.customer, exclude_event_id=event.id,
            ).exclude(pk=self.pk)
            dup = reused.first()
            if dup is not None:
                raise ValidationError(
                    "Puzzle “{puzzle}” is already used by another event for "
                    "{customer} ({other}). A puzzle can only be used once per "
                    "customer (tick “Allow reuse” to override).".format(
                        puzzle=self.puzzle,
                        customer=event.customer,
                        other=dup.event,
                    )
                )

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.allow_reuse and self.event_id:
            # Propagate the override to any other (non-cancelled) event for the
            # same customer using this puzzle. Without this, re-opening and
            # re-saving *that* event would re-trigger the reuse conflict from
            # its own side, since it wouldn't itself carry the override.
            EventPuzzle.objects.filter(
                puzzle_id=self.puzzle_id,
                event__customer_id=self.event.customer_id,
            ).exclude(pk=self.pk).exclude(
                event__status=Event.Status.CANCELLED
            ).update(allow_reuse=True)
