"""
Admin configuration for the internal PM tool, skinned with django-unfold.

Two cross-event rules are enforced in two complementary places each — the
model ``clean()`` (see models.py, also covers programmatic/API use) and the
admin inline formset here (authoritative for the UI, because it sees the
event's *edited* start/end/customer and all resource rows submitted together,
including on a brand-new event that has no primary key yet):

* a Venue/Puzzle must not be double-booked for overlapping time windows;
* a Puzzle must not be reused across a customer's events.
"""
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet
from django.utils import timezone
from django.utils.html import format_html

from unfold.admin import ModelAdmin, TabularInline

from .models import (
    Customer,
    Event,
    EventResource,
    Puzzle,
    Venue,
    overlapping_resource_events,
    puzzle_events_for_customer,
)


class EventResourceInlineFormSet(BaseInlineFormSet):
    """Validate the whole set of resources against the event's edited fields."""

    def clean(self):
        super().clean()
        event = self.instance

        start = getattr(event, "start", None)
        end = getattr(event, "end", None)
        customer = getattr(event, "customer", None)
        if not start or not end:
            return  # parent form already errored on the missing/invalid window

        # Cancelled events release their resources — nothing to guard.
        if getattr(event, "status", None) == Event.Status.CANCELLED:
            return

        seen = set()
        for form in self.forms:
            if not hasattr(form, "cleaned_data"):
                continue
            cd = form.cleaned_data
            if not cd or cd.get("DELETE"):
                continue

            venue = cd.get("venue")
            puzzle = cd.get("puzzle")
            if bool(venue) == bool(puzzle):
                continue  # exactly-one rule reported at the row level

            key = ("venue", venue.pk) if venue else ("puzzle", puzzle.pk)
            if key in seen:
                raise ValidationError(
                    "The same resource is attached to this event twice."
                )
            seen.add(key)

            # Rule 1: overlapping time window for the same resource.
            clashes = overlapping_resource_events(
                venue=venue if venue else None,
                puzzle=puzzle if puzzle else None,
                start=start,
                end=end,
                exclude_event_id=event.pk,
            )
            if form.instance.pk:
                clashes = clashes.exclude(pk=form.instance.pk)
            clash = clashes.first()
            if clash is not None:
                other = clash.event
                label = f"Venue “{venue}”" if venue else f"Puzzle “{puzzle}”"
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

            # Rule 2: a puzzle must not be reused across a customer's events.
            # Soft rule — the row's "allow reuse" checkbox overrides it.
            if puzzle and customer and not cd.get("allow_reuse"):
                reused = puzzle_events_for_customer(
                    puzzle=puzzle, customer=customer, exclude_event_id=event.pk
                )
                if form.instance.pk:
                    reused = reused.exclude(pk=form.instance.pk)
                dup = reused.first()
                if dup is not None:
                    raise ValidationError(
                        format_html(
                            "Puzzle “{}” is already used by another event for "
                            "{} (“{}”). A puzzle can only be used once per "
                            "customer.",
                            str(puzzle), str(customer), str(dup.event),
                        )
                    )


class EventResourceInline(TabularInline):
    model = EventResource
    formset = EventResourceInlineFormSet
    extra = 1
    fields = ["venue", "puzzle", "allow_reuse"]
    autocomplete_fields = ["venue", "puzzle"]
    verbose_name = "Used resource"
    verbose_name_plural = "Resources used (one venue or puzzle per row)"


@admin.register(Customer)
class CustomerAdmin(ModelAdmin):
    list_display = ["name", "email", "phone", "event_count"]
    search_fields = ["name", "email", "phone"]
    list_filter = ["created_at"]

    @admin.display(description="Events")
    def event_count(self, obj):
        return obj.events.count()


@admin.register(Venue)
class VenueAdmin(ModelAdmin):
    list_display = ["name", "capacity", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name", "address"]
    fields = ["name", "address", "capacity", "notes", "is_active"]


@admin.register(Puzzle)
class PuzzleAdmin(ModelAdmin):
    list_display = ["name", "flexible_answer", "has_github", "is_active"]
    list_filter = ["is_active", "flexible_answer"]
    search_fields = ["name", "answer"]
    fields = [
        "name", "flexible_answer", "answer", "github_url", "notes", "is_active",
    ]

    @admin.display(description="GitHub", boolean=True)
    def has_github(self, obj):
        return bool(obj.github_url)


STATUS_COLOURS = {
    Event.Status.ENQUIRY: "#a16207",    # amber
    Event.Status.CONFIRMED: "#15803d",  # green
    Event.Status.CANCELLED: "#b91c1c",  # red
    Event.Status.COMPLETED: "#4338ca",  # indigo
}


@admin.register(Event)
class EventAdmin(ModelAdmin):
    inlines = [EventResourceInline]
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
            "resources__venue", "resources__puzzle"
        )
