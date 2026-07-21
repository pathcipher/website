"""
Reshape the schema around "an event has exactly one venue, and many puzzles":

* Event gains ``name`` and a direct ``venue`` FK.
* The generic EventResource (venue-or-puzzle) join is retired: existing venue
  rows are copied onto Event.venue and then dropped; the remaining
  puzzle-only rows are renamed to EventPuzzle.
* Puzzle gains ``has_physical_components`` and ``hardware_required``, and
  ``flexible_answer`` is renamed to ``answer_restrictions`` — with inverted
  semantics, so existing boolean values are flipped, not just renamed.
* A new PuzzleFile model supports arbitrary file attachments on a puzzle.

Written by hand (rather than relying on the autodetector) so existing data is
preserved through the reshape instead of being dropped and recreated.
"""
import django.db.models.deletion
from django.db import migrations, models

import bookings.models


def migrate_venue_and_drop_venue_rows(apps, schema_editor):
    Event = apps.get_model("bookings", "Event")
    EventResource = apps.get_model("bookings", "EventResource")

    for res in EventResource.objects.filter(venue__isnull=False).select_related("event"):
        event = res.event
        if event.venue_id is None:
            event.venue_id = res.venue_id
            event.save(update_fields=["venue"])

    # These rows' data is now on Event.venue; the remaining (puzzle) rows
    # become EventPuzzle in the next steps.
    EventResource.objects.filter(puzzle__isnull=True).delete()


def invert_answer_restrictions(apps, schema_editor):
    Puzzle = apps.get_model("bookings", "Puzzle")
    # flexible_answer=True meant "accepts a range of answers" (unrestricted).
    # answer_restrictions means the opposite: "requires one exact answer".
    for puzzle in Puzzle.objects.all():
        puzzle.answer_restrictions = not puzzle.answer_restrictions
        puzzle.save(update_fields=["answer_restrictions"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("bookings", "0003_alter_eventresource_options_alter_puzzle_options_and_more"),
    ]

    operations = [
        # --- Event: name + direct venue FK ---
        migrations.AddField(
            model_name="event",
            name="name",
            field=models.CharField(default="", max_length=200),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="event",
            name="venue",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="events", to="bookings.venue",
            ),
        ),
        migrations.RunPython(migrate_venue_and_drop_venue_rows, noop_reverse),

        # --- Drop the old generic-resource shape on EventResource ---
        migrations.RemoveConstraint(
            model_name="eventresource", name="eventresource_exactly_one_resource",
        ),
        migrations.RemoveConstraint(
            model_name="eventresource", name="uniq_event_venue",
        ),
        migrations.RemoveField(model_name="eventresource", name="venue"),

        # --- Rename the (now puzzle-only) join model ---
        migrations.RenameModel(old_name="EventResource", new_name="EventPuzzle"),

        # --- Puzzle: field changes ---
        migrations.RemoveField(model_name="puzzle", name="is_active"),
        migrations.AddField(
            model_name="puzzle",
            name="has_physical_components",
            field=models.BooleanField(
                default=True,
                help_text="Tick if this puzzle involves physical props/kit "
                          "that can only be in one place at a time. Untick "
                          "for online-only puzzles, which can run at "
                          "multiple events simultaneously.",
            ),
        ),
        migrations.RenameField(
            model_name="puzzle", old_name="flexible_answer", new_name="answer_restrictions",
        ),
        migrations.RunPython(invert_answer_restrictions, noop_reverse),
        migrations.AddField(
            model_name="puzzle",
            name="hardware_required",
            field=models.TextField(blank=True, default="", help_text="One item per line."),
        ),

        # --- New model: arbitrary file uploads on a puzzle ---
        migrations.CreateModel(
            name="PuzzleFile",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("file", models.FileField(upload_to=bookings.models.puzzle_file_upload_to)),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                ("puzzle", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name="files",
                    to="bookings.puzzle",
                )),
            ],
            options={"ordering": ["-uploaded_at"]},
        ),
    ]
