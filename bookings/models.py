"""
Events domain model for the internal PM tool.

Rules enforced in Python (via ``clean()`` / ``full_clean()``) so admin users
get clear, human-readable errors rather than raw database IntegrityErrors:

1. A resource (a Venue or a Puzzle) must never be booked for two overlapping
   time windows at once.
2. A given Puzzle must not be used by more than one event for the same
   customer.
"""
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


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


class ResourceQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)


class Venue(models.Model):
    """A bookable location/room."""

    name = models.CharField(max_length=200)
    address = models.TextField(blank=True)
    capacity = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    objects = ResourceQuerySet.as_manager()

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Puzzle(models.Model):
    """A bookable puzzle/prop resource."""

    name = models.CharField(max_length=200)
    flexible_answer = models.BooleanField(
        default=False,
        help_text="Whether the puzzle accepts a range of answers rather than "
                  "one exact solution.",
    )
    answer = models.TextField(
        blank=True,
        help_text="The puzzle's solution (or accepted answers).",
    )
    github_url = models.URLField(
        blank=True,
        verbose_name="GitHub link",
        help_text="Optional link to the puzzle's repository.",
    )
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    objects = ResourceQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        verbose_name = "Puzzle"

    def __str__(self):
        return self.name


class Event(models.Model):
    class Status(models.TextChoices):
        ENQUIRY = "enquiry", "Enquiry"
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"
        COMPLETED = "completed", "Completed"

    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name="events"
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
        return f"{self.customer} — {when} ({self.get_status_display()})"

    @property
    def blocks_resources(self):
        """Cancelled events don't hold their resources."""
        return self.status != self.Status.CANCELLED

    def clean(self):
        super().clean()
        if self.start and self.end and self.end <= self.start:
            raise ValidationError(
                {"end": "End time must be after the start time."}
            )


def overlapping_resource_events(*, venue=None, puzzle=None, start, end,
                                exclude_event_id=None):
    """
    EventResource rows that would clash with a [start, end) window for the given
    resource. A clash is an overlapping window on an event that still holds its
    resources (i.e. not cancelled).

    Half-open intervals: touching end-to-start (e.g. 10:00–11:00 then
    11:00–12:00) does NOT count as an overlap.
    """
    if (venue is None) == (puzzle is None):
        raise ValueError("Provide exactly one of venue or puzzle.")

    qs = EventResource.objects.select_related("event", "event__customer")
    if venue is not None:
        qs = qs.filter(venue=venue)
    else:
        qs = qs.filter(puzzle=puzzle)

    qs = qs.exclude(event__status=Event.Status.CANCELLED)
    # Overlap test for half-open intervals: a.start < b.end AND b.start < a.end
    qs = qs.filter(event__start__lt=end, event__end__gt=start)

    if exclude_event_id is not None:
        qs = qs.exclude(event_id=exclude_event_id)

    return qs


def puzzle_events_for_customer(*, puzzle, customer, exclude_event_id=None):
    """
    EventResource rows attaching ``puzzle`` to a (non-cancelled) event for
    ``customer``. Used to stop the same puzzle being reused across a customer's
    events.
    """
    qs = EventResource.objects.select_related("event").filter(
        puzzle=puzzle, event__customer=customer
    ).exclude(event__status=Event.Status.CANCELLED)
    if exclude_event_id is not None:
        qs = qs.exclude(event_id=exclude_event_id)
    return qs


class EventResource(models.Model):
    """
    Links an Event to exactly one resource (a Venue OR a Puzzle) it uses.

    An event that needs a room and two puzzles has three EventResource rows.
    The overlap and reuse rules are enforced per row in ``clean()``.
    """

    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name="resources"
    )
    venue = models.ForeignKey(
        Venue, null=True, blank=True, on_delete=models.PROTECT,
        related_name="event_links",
    )
    puzzle = models.ForeignKey(
        Puzzle, null=True, blank=True, on_delete=models.PROTECT,
        related_name="event_links",
    )
    allow_reuse = models.BooleanField(
        default=False,
        verbose_name="Allow reuse for this customer",
        help_text="Tick to permit using this puzzle even though it's already "
                  "used by another event for the same customer.",
    )

    class Meta:
        verbose_name = "Used resource"
        constraints = [
            # Exactly one of venue / puzzle must be set (DB-level backstop).
            models.CheckConstraint(
                name="eventresource_exactly_one_resource",
                condition=(
                    models.Q(venue__isnull=False, puzzle__isnull=True)
                    | models.Q(venue__isnull=True, puzzle__isnull=False)
                ),
            ),
            # Don't attach the same resource to an event twice.
            models.UniqueConstraint(
                fields=["event", "venue"],
                condition=models.Q(venue__isnull=False),
                name="uniq_event_venue",
            ),
            models.UniqueConstraint(
                fields=["event", "puzzle"],
                condition=models.Q(puzzle__isnull=False),
                name="uniq_event_puzzle",
            ),
        ]

    @property
    def resource(self):
        return self.venue or self.puzzle

    @property
    def resource_label(self):
        if self.venue_id:
            return f"Venue: {self.venue}"
        if self.puzzle_id:
            return f"Puzzle: {self.puzzle}"
        return "—"

    def __str__(self):
        return self.resource_label

    def clean(self):
        super().clean()

        # Exactly one resource must be chosen.
        if bool(self.venue_id) == bool(self.puzzle_id):
            raise ValidationError(
                "Choose exactly one resource: either a venue or a puzzle."
            )

        # We can only check the cross-event rules once we know which event (and
        # therefore which time window / customer) this row belongs to. During
        # admin inline creation the parent may not be attached yet — the inline
        # formset performs the authoritative check in that case (see admin.py).
        event = self.event if self.event_id else None
        if not event or not event.start or not event.end:
            return
        if not event.blocks_resources:
            return  # cancelled events don't reserve anything

        # Rule 1: no overlapping time window for the same resource.
        clashes = overlapping_resource_events(
            venue=self.venue if self.venue_id else None,
            puzzle=self.puzzle if self.puzzle_id else None,
            start=event.start,
            end=event.end,
            exclude_event_id=event.id,
        ).exclude(pk=self.pk)

        first = clashes.first()
        if first is not None:
            other = first.event
            raise ValidationError(
                "{res} is already booked for an overlapping time "
                "({start} – {end}) by event “{other}”.".format(
                    res=self.resource_label,
                    start=timezone.localtime(other.start).strftime("%d %b %H:%M"),
                    end=timezone.localtime(other.end).strftime("%d %b %H:%M"),
                    other=other,
                )
            )

        # Rule 2: a puzzle must not be reused across a customer's events.
        # This is a soft rule — tick ``allow_reuse`` to override it.
        if self.puzzle_id and not self.allow_reuse:
            reused = puzzle_events_for_customer(
                puzzle=self.puzzle,
                customer=event.customer,
                exclude_event_id=event.id,
            ).exclude(pk=self.pk)
            dup = reused.first()
            if dup is not None:
                raise ValidationError(
                    "Puzzle “{puzzle}” is already used by another event for "
                    "{customer} ({other}). A puzzle can only be used once per "
                    "customer.".format(
                        puzzle=self.puzzle,
                        customer=event.customer,
                        other=dup.event,
                    )
                )
