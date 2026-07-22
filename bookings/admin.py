"""
Admin configuration for the internal PM tool, skinned with django-unfold.

Business rules and where they're enforced:

* Venue double-booking (an event has exactly one venue) — Event.clean(),
  surfaces as a normal field error on the admin's "venue" field.
* Physical-puzzle double-booking — EventPuzzle.clean() (model-level) and
  EventPuzzleInlineFormSet.clean() here (authoritative for the admin UI,
  since it sees the event's *edited* start/end and all puzzle rows submitted
  together, including on a brand-new event with no primary key yet). Puzzles
  without physical components have no such limit.
* Puzzle reuse across a customer's events — same two places, and it's a soft
  rule: tick "Allow reuse" to override (see EventPuzzle.save() for how the
  override then propagates to the other conflicting event automatically).
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
    EventPuzzle,
    Puzzle,
    PuzzleFile,
    Venue,
    overlapping_puzzle_events,
    puzzle_events_for_customer,
)


class EventPuzzleInlineFormSet(BaseInlineFormSet):
    """Validate the whole set of puzzles against the event's edited fields."""

    def clean(self):
        super().clean()
        event = self.instance

        start = getattr(event, "start", None)
        end = getattr(event, "end", None)
        customer = getattr(event, "customer", None)
        if not start or not end:
            return  # parent form already errored on the missing/invalid window

        # Cancelled events release their puzzles — nothing to guard.
        if getattr(event, "status", None) == Event.Status.CANCELLED:
            return

        seen = set()
        for form in self.forms:
            if not hasattr(form, "cleaned_data"):
                continue
            cd = form.cleaned_data
            if not cd or cd.get("DELETE"):
                continue

            puzzle = cd.get("puzzle")
            if not puzzle:
                continue

            if puzzle.pk in seen:
                raise ValidationError(
                    "The same puzzle is attached to this event twice."
                )
            seen.add(puzzle.pk)

            # Rule: a puzzle with physical components can't overlap another event.
            clashes = overlapping_puzzle_events(
                puzzle=puzzle, start=start, end=end, exclude_event_id=event.pk,
            )
            if form.instance.pk:
                clashes = clashes.exclude(pk=form.instance.pk)
            clash = clashes.first()
            if clash is not None:
                other = clash.event
                raise ValidationError(
                    format_html(
                        "“{}” has physical components and is already in use "
                        "for an overlapping time ({} – {}) by “{}”.",
                        str(puzzle),
                        timezone.localtime(other.start).strftime("%d %b %H:%M"),
                        timezone.localtime(other.end).strftime("%d %b %H:%M"),
                        str(other),
                    )
                )

            # Rule: a puzzle must not be reused across a customer's events.
            # Soft rule — the row's "allow reuse" checkbox overrides it.
            if customer and not cd.get("allow_reuse"):
                reused = puzzle_events_for_customer(
                    puzzle=puzzle, customer=customer, exclude_event_id=event.pk,
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


class EventPuzzleInline(TabularInline):
    model = EventPuzzle
    formset = EventPuzzleInlineFormSet
    extra = 1
    fields = ["puzzle", "allow_reuse"]
    autocomplete_fields = ["puzzle"]
    verbose_name = "Puzzle used"
    verbose_name_plural = "Puzzles used"


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


class PuzzleFileInline(TabularInline):
    model = PuzzleFile
    extra = 1
    fields = ["file", "uploaded_at"]
    readonly_fields = ["uploaded_at"]


class HasPhysicalComponentsFilter(admin.SimpleListFilter):
    """Filter on the derived has_physical_components property (no such column)."""

    title = "physical components"
    parameter_name = "has_physical_components"

    def lookups(self, request, model_admin):
        return (("yes", "Physical"), ("no", "Online-only"))

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.exclude(hardware_required="")
        if self.value() == "no":
            return queryset.filter(hardware_required="")
        return queryset


@admin.register(Puzzle)
class PuzzleAdmin(ModelAdmin):
    inlines = [PuzzleFileInline]
    list_display = [
        "name", "restrictions_badge", "physical_components_badge", "tag_list", "has_github",
    ]
    list_filter = [HasPhysicalComponentsFilter, "answer_restrictions"]
    search_fields = ["name", "answer", "tags__name"]
    fields = [
        "name", "answer_restrictions", "answer",
        "hardware_required", "github_url", "tags", "notes",
    ]

    @admin.display(description="Answer")
    def restrictions_badge(self, obj):
        if obj.answer_restrictions:
            return format_html(
                '<span style="color:#b45309;font-weight:600;" title="Answer restrictions">⚠</span>'
            )
        return format_html('<span style="color:#15803d;font-weight:600;">✓</span>')

    @admin.display(description="Physical", boolean=True)
    def physical_components_badge(self, obj):
        return obj.has_physical_components

    @admin.display(description="Tags")
    def tag_list(self, obj):
        return ", ".join(t.name for t in obj.tags.all()) or "—"

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
    inlines = [EventPuzzleInline]
    date_hierarchy = "start"
    list_display = ["name", "customer", "venue", "start", "end", "status_badge", "puzzle_count"]
    list_filter = ["status", "start", "venue"]
    search_fields = ["name", "customer__name", "notes"]
    autocomplete_fields = ["customer", "venue"]
    list_select_related = ["customer", "venue"]
    ordering = ["-start"]

    @admin.display(description="Status")
    def status_badge(self, obj):
        return format_html(
            '<span style="display:inline-block;padding:2px 10px;border-radius:9999px;'
            'font-size:12px;font-weight:600;color:#fff;background:{}">{}</span>',
            STATUS_COLOURS.get(obj.status, "#6b7280"),
            obj.get_status_display(),
        )

    @admin.display(description="Puzzles")
    def puzzle_count(self, obj):
        return obj.event_puzzles.count()

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("event_puzzles__puzzle")
