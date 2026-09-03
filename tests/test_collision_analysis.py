import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from core.calendar_workflow import load_calendar
from core.collision_detector import (
    analyze_collisions,
    collision_category,
)
from core.models import CalendarEventData, LoadedCalendar
from reports.collision_report import (
    default_collision_report_path,
    render_collision_report,
    write_collision_report,
)


class CollisionAnalysisTests(unittest.TestCase):
    def test_half_open_intervals_do_not_collide_at_shared_endpoint(self) -> None:
        events = (
            _event("lab", "LABORATORIO", 9, 10),
            _event("class", "TEOR\u00cdA", 10, 11),
        )

        analysis = analyze_collisions(events)

        self.assertEqual(0, analysis.collision_count)
        self.assertEqual(0, analysis.laboratory_collision_count)

    def test_detector_keeps_all_pairs_and_builds_lab_projection(self) -> None:
        events = (
            _event("lab", "LABORATORIO", 9, 12),
            _event("seminar", "SEMINARIO", 9, 10),
            _event("tutorial", "Tutor\u00eda", 10, 11),
            _event("class", "TEOR\u00cdA", 11, 13),
        )

        analysis = analyze_collisions(events)

        self.assertEqual(3, analysis.collision_count)
        self.assertEqual(3, analysis.laboratory_collision_count)
        self.assertEqual(1, analysis.affected_laboratory_count)
        self.assertEqual(
            [
                "Laboratory / Seminar",
                "Laboratory / Tutorial",
                "Laboratory / Class",
            ],
            [
                collision_category(collision)
                for collision in analysis.laboratory_collisions
            ],
        )

    def test_current_fixture_matches_collision_baseline(self) -> None:
        loaded = load_calendar(Path("test_files/new_format.ics"))

        analysis = analyze_collisions(loaded.events)

        self.assertEqual(372, analysis.event_count)
        self.assertEqual(19, analysis.collision_count)
        self.assertEqual(16, analysis.laboratory_collision_count)
        self.assertEqual(13, analysis.affected_laboratory_count)

    def test_text_report_includes_all_collisions_and_saves_next_to_output(self) -> None:
        laboratory = _event("lab", "LABORATORIO", 9, 11)
        tutorial = _event(
            "tutorial", "Tutor\u00eda", 10, 12, subject_id="99999"
        )
        seminar = _event(
            "seminar", "SEMINARIO", 9, 11, day=15, subject_id="11111"
        )
        class_event = _event(
            "class", "TEOR\u00cdA", 10, 12, day=15, subject_id="22222"
        )
        loaded = LoadedCalendar(
            source_path=Path("source.ics"),
            preamble="",
            events=(laboratory, tutorial, seminar, class_event),
            subject_catalog={"34082": "UV name"},
        )
        analysis = analyze_collisions(loaded.events)
        aliases = {
            "34082": "Edited subject",
            "99999": "Tutorial subject",
            "11111": "Seminar subject",
            "22222": "Class subject",
        }

        report = render_collision_report(analysis, loaded, aliases)

        self.assertIn("Collision pairs: 2", report)
        self.assertIn("Laboratory-involved pairs: 1", report)
        self.assertIn("Laboratory / Tutorial", report)
        self.assertIn("Seminar / Class", report)
        self.assertIn("Edited subject (34082)", report)
        self.assertNotIn("A collision is an actual time overlap", report)
        self.assertNotIn("| overlap ", report)
        self.assertLess(
            report.index("1. 2026-09-14 | Laboratory / Tutorial"),
            report.index("2. 2026-09-15 | Seminar / Class"),
        )
        self.assertNotIn("| ---", report)
        self.assertEqual(
            Path("calendar_collisions.txt"),
            default_collision_report_path(Path("calendar.ics")),
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "report"
            saved_path = write_collision_report(
                analysis,
                loaded,
                aliases,
                output_path,
            )
            saved_report = saved_path.read_text(encoding="utf-8")

        self.assertEqual(".txt", saved_path.suffix)
        self.assertEqual(report, saved_report)

    def test_report_groups_recurring_subjects_and_timeframes(self) -> None:
        events = (
            _event("lab-1", "LABORATORIO", 9, 11, group="DG-L1"),
            _event(
                "tutorial-1",
                "Tutor\u00eda",
                10,
                12,
                subject_id="99999",
                group="DG-U1",
            ),
            _event("lab-2", "LABORATORIO", 9, 11, day=15, group="DG-L1"),
            _event(
                "tutorial-2",
                "Tutor\u00eda",
                10,
                12,
                day=15,
                subject_id="99999",
                group="DG-U1",
            ),
            _event("lab-3", "LABORATORIO", 9, 11, day=17, group="DG-L1"),
            _event(
                "tutorial-3",
                "Tutor\u00eda",
                10,
                12,
                day=17,
                subject_id="99999",
                group="DG-U1",
            ),
        )
        loaded = LoadedCalendar(
            source_path=Path("source.ics"),
            preamble="",
            events=events,
            subject_catalog={"34082": "Lab subject", "99999": "Tutorial subject"},
        )

        report = render_collision_report(
            analyze_collisions(events),
            loaded,
            loaded.subject_catalog,
        )

        self.assertIn(
            "1. 2026-09-14 to 2026-09-15 (2 occurrences) | "
            "Laboratory / Tutorial",
            report,
        )
        self.assertIn(
            "2. 2026-09-17 | Laboratory / Tutorial",
            report,
        )

    def test_timezone_naive_event_is_rejected_with_clear_error(self) -> None:
        naive_event = CalendarEventData(
            uid="naive",
            subject_id="34082",
            original_subject="UV name",
            class_type="LABORATORIO",
            group="DG-L1",
            start=datetime(2026, 9, 14, 9, 0),
            end=datetime(2026, 9, 14, 10, 0),
            created=None,
            location="LAB",
        )

        with self.assertRaisesRegex(ValueError, "timezone-naive"):
            analyze_collisions((naive_event,))


def _event(
    uid: str,
    class_type: str,
    start_hour: int,
    end_hour: int,
    *,
    day: int = 14,
    subject_id: str = "34082",
    group: str | None = None,
):
    timezone = ZoneInfo("Europe/Madrid")
    return CalendarEventData(
        uid=uid,
        subject_id=subject_id,
        original_subject="UV name",
        class_type=class_type,
        group=group or f"DG-{uid.upper()}",
        start=datetime(2026, 9, day, start_hour, 0, tzinfo=timezone),
        end=datetime(2026, 9, day, end_hour, 0, tzinfo=timezone),
        created=None,
        location=f"Location {uid}",
    )


if __name__ == "__main__":
    unittest.main()
