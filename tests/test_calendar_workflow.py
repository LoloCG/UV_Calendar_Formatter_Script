import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ics.grammar.parse import GRAMMAR

from core.activity_policy import ActivityPriority, activity_priority
from core.calendar_workflow import (
    generate_formatted_calendar,
    load_calendar,
    prepare_subject_names,
)
from core.models import CalendarEventData, LoadedCalendar
from core.text_utils import normalize_label
from utils.ics_compat import disable_parser_colorization


class CalendarWorkflowTests(unittest.TestCase):
    def test_unused_ics_parser_colorization_is_disabled(self) -> None:
        GRAMMAR.config.colorize = True

        self.assertTrue(disable_parser_colorization())
        self.assertFalse(GRAMMAR.config.colorize)

    def test_new_fixture_loads_as_normalized_events(self) -> None:
        loaded = load_calendar(Path("test_files/new_format.ics"))

        self.assertEqual(372, len(loaded.events))
        self.assertEqual(8, len(loaded.subject_catalog))
        self.assertEqual(
            "Tecnología Farmaceutica I",
            loaded.subject_catalog["34082"],
        )
        self.assertTrue(
            all(
                event.start.tzinfo is not None and event.end.tzinfo is not None
                for event in loaded.events
            )
        )

    def test_label_normalization_is_shared_and_accent_insensitive(self) -> None:
        self.assertEqual("laboratorio", normalize_label("  LABORATÓRIO\u00a0"))
        self.assertEqual("tutorias", normalize_label("Tutorías"))

    def test_activity_priority_places_tutorial_between_seminar_and_class(self) -> None:
        self.assertEqual(
            ActivityPriority.LABORATORY,
            activity_priority("LABORATORIO"),
        )
        self.assertEqual(
            ActivityPriority.SEMINAR,
            activity_priority("Seminarios"),
        )
        self.assertEqual(
            ActivityPriority.TUTORIAL,
            activity_priority("Tutor\u00eda"),
        )
        self.assertEqual(ActivityPriority.CLASS, activity_priority("TEOR\u00cdA"))
        self.assertGreater(
            ActivityPriority.LABORATORY,
            ActivityPriority.SEMINAR,
        )
        self.assertGreater(ActivityPriority.SEMINAR, ActivityPriority.TUTORIAL)
        self.assertGreater(ActivityPriority.TUTORIAL, ActivityPriority.CLASS)

    def test_subject_names_merge_configured_aliases_with_new_subjects(self) -> None:
        loaded = _loaded_calendar()

        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "calendar_config.json"
            config_path.write_text('{"34082": "Tec Farm I"}', encoding="utf-8")

            subject_names, configured_ids = prepare_subject_names(
                loaded,
                config_path,
            )

        self.assertEqual("Tec Farm I", subject_names["34082"])
        self.assertEqual("New subject", subject_names["99999"])
        self.assertEqual(frozenset({"34082"}), configured_ids)

    def test_invalid_existing_configuration_is_not_silently_replaced(self) -> None:
        loaded = _loaded_calendar()

        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "calendar_config.json"
            config_path.write_text("{invalid", encoding="utf-8")

            with self.assertRaises(json.JSONDecodeError):
                prepare_subject_names(loaded, config_path)

            self.assertEqual("{invalid", config_path.read_text(encoding="utf-8"))

    def test_generation_uses_existing_alias_and_opaque_policy(self) -> None:
        timezone = ZoneInfo("Europe/Madrid")
        event = CalendarEventData(
            uid="event-1",
            subject_id="34082",
            original_subject="Tecnología Farmaceutica I",
            class_type="LABORATORIO",
            group="DG-L1",
            start=datetime(2026, 9, 29, 9, 0, tzinfo=timezone),
            end=datetime(2026, 9, 29, 11, 0, tzinfo=timezone),
            created=None,
            location="LAB 2",
        )
        loaded = LoadedCalendar(
            source_path=Path("source.ics"),
            preamble="",
            events=(event,),
            subject_catalog={"34082": event.original_subject},
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            config_path = temporary_path / "calendar_config.json"
            output_path = temporary_path / "formatted.ics"
            config_path.write_text(
                '{"34082": "Tec Farm I"}',
                encoding="utf-8",
            )

            result = generate_formatted_calendar(
                loaded,
                config_path=config_path,
                output_path=output_path,
            )
            output = result.output_path.read_text(encoding="utf-8")

        self.assertTrue(result.custom_names_applied)
        self.assertIn("SUMMARY:Tec Farm I - LABORATORIO", output)
        self.assertIn("TRANSP:OPAQUE", output)
        self.assertIn("LOCATION:LAB 2", output)

    def test_generation_saves_and_applies_tui_names_on_first_pass(self) -> None:
        loaded = _loaded_calendar()

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            config_path = temporary_path / "calendar_config.json"
            output_path = temporary_path / "formatted.ics"

            result = generate_formatted_calendar(
                loaded,
                config_path=config_path,
                output_path=output_path,
                subject_names={
                    "34082": "Tec Farm I",
                    "99999": "New subject",
                },
            )
            output = output_path.read_text(encoding="utf-8")
            saved_config = config_path.read_text(encoding="utf-8")

        self.assertTrue(result.custom_names_applied)
        self.assertIn("SUMMARY:Tec Farm I - LABORATORIO", output)
        self.assertIn('\"34082\": \"Tec Farm I\"', saved_config)


def _loaded_calendar() -> LoadedCalendar:
    timezone = ZoneInfo("Europe/Madrid")
    events = (
        CalendarEventData(
            uid="event-1",
            subject_id="34082",
            original_subject="Tecnolog\u00eda Farmaceutica I",
            class_type="LABORATORIO",
            group="DG-L1",
            start=datetime(2026, 9, 29, 9, 0, tzinfo=timezone),
            end=datetime(2026, 9, 29, 11, 0, tzinfo=timezone),
            created=None,
            location="LAB 2",
        ),
        CalendarEventData(
            uid="event-2",
            subject_id="99999",
            original_subject="New subject",
            class_type="TEOR\u00cdA",
            group="DG-T",
            start=datetime(2026, 9, 30, 9, 0, tzinfo=timezone),
            end=datetime(2026, 9, 30, 10, 0, tzinfo=timezone),
            created=None,
            location="AULA 1",
        ),
    )
    return LoadedCalendar(
        source_path=Path("source.ics"),
        preamble="",
        events=events,
        subject_catalog={
            "34082": "Tecnolog\u00eda Farmaceutica I",
            "99999": "New subject",
        },
    )


if __name__ == "__main__":
    unittest.main()
