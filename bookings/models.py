"""
Bookings domain model for the internal PM tool.

Core rule: a resource (a Venue or a PuzzleSet) must never be booked for two
overlapping time windows at once. That rule is enforced in Python via
``clean()`` / ``full_clean()`` so that admin users get a clear, human-readable
error — not a raw database IntegrityError.
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
    capacity = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    objects = ResourceQuerySet.as_manager()

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class PuzzleSet(models.Model):
    """A bookable puzzle/prop resource."""

    name = models.CharField(max_length=200)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    objects = ResourceQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        verbose_name = "Puzzle set"

    def __str__(self):
        return self.name


class Booking(models.Model):
    class Status(models.TextChoices):
        ENQUIRY = "enquiry", "Enquiry"
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"
        COMPLETED = "completed", "Completed"

    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name="bookings"
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
        """Cancelled bookings don't hold their resources."""
        return self.status != self.Status.CANCELLED

    def clean(self):
        super().clean()
        if self.start and self.end and self.end <= self.start:
            raise ValidationError(
                {"end": "End time must be after the start time."}
            )


def overlapping_resource_bookings(*, venue=None, puzzle_set=None, start, end,
                                  exclude_booking_id=None):
    """
    BookingResource rows that would clash with a [start, end) window for the
    given resource. A clash is an overlapping window on a booking that still
    holds its resources (i.e. not cancelled).

    Half-open intervals: touching end-to-start (e.g. 10:00–11:00 then
    11:00–12:00) does NOT count as an overlap.
    """
    if (venue is None) == (puzzle_set is None):
        raise ValueError("Provide exactly one of venue or puzzle_set.")

    qs = BookingResource.objects.select_related("booking", "booking__customer")
    if venue is not None:
        qs = qs.filter(venue=venue)
    else:
        qs = qs.filter(puzzle_set=puzzle_set)

    qs = qs.exclude(booking__status=Booking.Status.CANCELLED)
    # Overlap test for half-open intervals: a.start < b.end AND b.start < a.end
    qs = qs.filter(booking__start__lt=end, booking__end__gt=start)

    if exclude_booking_id is not None:
        qs = qs.exclude(booking_id=exclude_booking_id)

    return qs


class BookingResource(models.Model):
    """
    Links a Booking to exactly one resource (a Venue OR a PuzzleSet) it uses.

    A booking that needs a room and two puzzle sets has three BookingResource
    rows. The overlap rule is enforced per row in ``clean()``.
    """

    booking = models.ForeignKey(
        Booking, on_delete=models.CASCADE, related_name="resources"
    )
    venue = models.ForeignKey(
        Venue, null=True, blank=True, on_delete=models.PROTECT,
        related_name="booking_links",
    )
    puzzle_set = models.ForeignKey(
        PuzzleSet, null=True, blank=True, on_delete=models.PROTECT,
        related_name="booking_links",
    )

    class Meta:
        verbose_name = "Booked resource"
        constraints = [
            # Exactly one of venue / puzzle_set must be set (DB-level backstop).
            models.CheckConstraint(
                name="bookingresource_exactly_one_resource",
                condition=(
                    models.Q(venue__isnull=False, puzzle_set__isnull=True)
                    | models.Q(venue__isnull=True, puzzle_set__isnull=False)
                ),
            ),
            # Don't attach the same resource to a booking twice.
            models.UniqueConstraint(
                fields=["booking", "venue"],
                condition=models.Q(venue__isnull=False),
                name="uniq_booking_venue",
            ),
            models.UniqueConstraint(
                fields=["booking", "puzzle_set"],
                condition=models.Q(puzzle_set__isnull=False),
                name="uniq_booking_puzzle_set",
            ),
        ]

    @property
    def resource(self):
        return self.venue or self.puzzle_set

    @property
    def resource_label(self):
        if self.venue_id:
            return f"Venue: {self.venue}"
        if self.puzzle_set_id:
            return f"Puzzle set: {self.puzzle_set}"
        return "—"

    def __str__(self):
        return self.resource_label

    def clean(self):
        super().clean()

        # Exactly one resource must be chosen.
        if bool(self.venue_id) == bool(self.puzzle_set_id):
            raise ValidationError(
                "Choose exactly one resource: either a venue or a puzzle set."
            )

        # We can only check overlaps once we know which booking (and therefore
        # which time window) this row belongs to. During admin inline creation
        # the parent may not be attached yet — the inline formset performs the
        # authoritative check in that case (see bookings/admin.py).
        booking = self.booking if self.booking_id else None
        if not booking or not booking.start or not booking.end:
            return
        if not booking.blocks_resources:
            return  # cancelled bookings don't reserve anything

        clashes = overlapping_resource_bookings(
            venue=self.venue if self.venue_id else None,
            puzzle_set=self.puzzle_set if self.puzzle_set_id else None,
            start=booking.start,
            end=booking.end,
            exclude_booking_id=booking.id,
        ).exclude(pk=self.pk)

        first = clashes.first()
        if first is not None:
            other = first.booking
            raise ValidationError(
                "{res} is already booked for an overlapping time "
                "({start} – {end}) by booking “{other}”.".format(
                    res=self.resource_label,
                    start=timezone.localtime(other.start).strftime("%d %b %H:%M"),
                    end=timezone.localtime(other.end).strftime("%d %b %H:%M"),
                    other=other,
                )
            )
