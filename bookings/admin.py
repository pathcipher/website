"""
Admin configuration for the internal PM tool, skinned with django-unfold.

The venue/puzzle-set double-booking rule is enforced in two complementary
places:

* ``BookingResource.clean()`` — the model-level rule (see models.py), which
  also protects programmatic/API use and existing-booking edits.
* ``BookingResourceInlineFormSet.clean()`` here — the authoritative check for
  the admin UI, because it can see the booking's *edited* start/end and the
  full set of resource rows being submitted together (including new ones on a
  brand-new booking that has no primary key yet).
"""
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet
from django.utils import timezone
from django.utils.html import format_html

from unfold.admin import ModelAdmin, TabularInline

from .models import (
    Booking,
    BookingResource,
    Customer,
    PuzzleSet,
    Venue,
    overlapping_resource_bookings,
)


class BookingResourceInlineFormSet(BaseInlineFormSet):
    """Validate the whole set of resources against the booking's edited window."""

    def clean(self):
        super().clean()
        booking = self.instance

        start = getattr(booking, "start", None)
        end = getattr(booking, "end", None)
        if not start or not end:
            return  # parent form already errored on the missing/invalid window

        # Cancelled bookings release their resources — nothing to guard.
        if getattr(booking, "status", None) == Booking.Status.CANCELLED:
            return

        seen = set()
        for form in self.forms:
            if not hasattr(form, "cleaned_data"):
                continue
            cd = form.cleaned_data
            if not cd or cd.get("DELETE"):
                continue

            venue = cd.get("venue")
            puzzle_set = cd.get("puzzle_set")
            if bool(venue) == bool(puzzle_set):
                continue  # exactly-one rule reported at the row level

            key = ("venue", venue.pk) if venue else ("puzzle", puzzle_set.pk)
            if key in seen:
                raise ValidationError(
                    "The same resource is attached to this booking twice."
                )
            seen.add(key)

            clashes = overlapping_resource_bookings(
                venue=venue if venue else None,
                puzzle_set=puzzle_set if puzzle_set else None,
                start=start,
                end=end,
                exclude_booking_id=booking.pk,
            )
            if form.instance.pk:
                clashes = clashes.exclude(pk=form.instance.pk)

            clash = clashes.first()
            if clash is not None:
                other = clash.booking
                label = f"Venue “{venue}”" if venue else f"Puzzle set “{puzzle_set}”"
                raise ValidationError(
                    format_html(
                        "{} is already booked for an overlapping window "
                        "({} – {}) by “{}”.",
                        label,
                        timezone.localtime(other.start).strftime("%d %b %H:%M"),
                        timezone.localtime(other.end).strftime("%d %b %H:%M"),
                        str(other),
                    )
                )


class BookingResourceInline(TabularInline):
    model = BookingResource
    formset = BookingResourceInlineFormSet
    extra = 1
    autocomplete_fields = ["venue", "puzzle_set"]
    verbose_name = "Booked resource"
    verbose_name_plural = "Booked resources (one venue or puzzle set per row)"


@admin.register(Customer)
class CustomerAdmin(ModelAdmin):
    list_display = ["name", "email", "phone", "booking_count"]
    search_fields = ["name", "email", "phone"]
    list_filter = ["created_at"]

    @admin.display(description="Bookings")
    def booking_count(self, obj):
        return obj.bookings.count()


@admin.register(Venue)
class VenueAdmin(ModelAdmin):
    list_display = ["name", "capacity", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name"]


@admin.register(PuzzleSet)
class PuzzleSetAdmin(ModelAdmin):
    list_display = ["name", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name"]


STATUS_COLOURS = {
    Booking.Status.ENQUIRY: "#a16207",    # amber
    Booking.Status.CONFIRMED: "#15803d",  # green
    Booking.Status.CANCELLED: "#b91c1c",  # red
    Booking.Status.COMPLETED: "#4338ca",  # indigo
}


@admin.register(Booking)
class BookingAdmin(ModelAdmin):
    inlines = [BookingResourceInline]
    date_hierarchy = "start"
    list_display = ["customer", "start", "end", "status_badge", "resource_summary"]
    list_filter = ["status", "start"]
    search_fields = ["customer__name", "notes"]
    autocomplete_fields = ["customer"]
    list_select_related = ["customer"]
    ordering = ["-start"]

    @admin.display(description="Status")
    def status_badge(self, obj):
        return format_html(
            '<span style="display:inline-block;padding:2px 10px;border-radius:9999px;'
            'font-size:12px;font-weight:600;color:#fff;background:{}">{}</span>',
            STATUS_COLOURS.get(obj.status, "#6b7280"),
            obj.get_status_display(),
        )

    @admin.display(description="Resources")
    def resource_summary(self, obj):
        parts = [r.resource_label for r in obj.resources.all()]
        return ", ".join(parts) if parts else "—"

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related(
            "resources__venue", "resources__puzzle_set"
        )
