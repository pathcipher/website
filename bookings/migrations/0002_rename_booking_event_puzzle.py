"""
Rename Booking→Event, PuzzleSet→Puzzle, BookingResource→EventResource (and the
join FKs booking→event, puzzle_set→puzzle), and add the new fields. Written by
hand as renames so existing rows are preserved rather than dropped/recreated.

Old constraints are removed first (they reference the pre-rename field names);
the follow-up migration re-adds them under their new names.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bookings", "0001_initial"),
    ]

    operations = [
        # Drop constraints that reference names/fields about to change.
        migrations.RemoveConstraint(
            model_name="bookingresource",
            name="bookingresource_exactly_one_resource",
        ),
        migrations.RemoveConstraint(
            model_name="bookingresource", name="uniq_booking_venue",
        ),
        migrations.RemoveConstraint(
            model_name="bookingresource", name="uniq_booking_puzzle_set",
        ),

        # Rename the models (preserves table data).
        migrations.RenameModel(old_name="Booking", new_name="Event"),
        migrations.RenameModel(old_name="PuzzleSet", new_name="Puzzle"),
        migrations.RenameModel(old_name="BookingResource", new_name="EventResource"),

        # Rename the join FKs.
        migrations.RenameField(
            model_name="eventresource", old_name="booking", new_name="event",
        ),
        migrations.RenameField(
            model_name="eventresource", old_name="puzzle_set", new_name="puzzle",
        ),

        # New fields.
        migrations.AddField(
            model_name="venue",
            name="address",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="puzzle",
            name="flexible_answer",
            field=models.BooleanField(
                default=False,
                help_text="Whether the puzzle accepts a range of answers "
                          "rather than one exact solution.",
            ),
        ),
        migrations.AddField(
            model_name="puzzle",
            name="answer",
            field=models.TextField(
                blank=True,
                help_text="The puzzle's solution (or accepted answers).",
            ),
        ),
        migrations.AddField(
            model_name="puzzle",
            name="github_url",
            field=models.URLField(
                blank=True,
                verbose_name="GitHub link",
                help_text="Optional link to the puzzle's repository.",
            ),
        ),
        migrations.AddField(
            model_name="eventresource",
            name="allow_reuse",
            field=models.BooleanField(
                default=False,
                verbose_name="Allow reuse for this customer",
                help_text="Tick to permit using this puzzle even though it's "
                          "already used by another event for the same customer.",
            ),
        ),
    ]
