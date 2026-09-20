import unittest
from collections import Counter
from pathlib import Path

from core.calendar_workflow import load_calendar
from core.change_tracking import canonical_sha256, compare_calendars
from core.collision_detector import analyze_collisions


CALENDAR_DOWNLOAD = Path("test_files/calendar_07092026.ics")
DIRECT_DOWNLOAD = Path("test_files/direct_download_07092026.ics")
PRIOR_YEAR_DIRECT_DOWNLOAD = Path("test_files/2025/oldcal2025.ics")


class CalendarFormatCharacterizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.calendar_download = load_calendar(CALENDAR_DOWNLOAD)
        cls.direct_download = load_calendar(DIRECT_DOWNLOAD)
        cls.prior_year = load_calendar(PRIOR_YEAR_DIRECT_DOWNLOAD)

    def test_fixture_inventory_and_source_metadata(self) -> None:
        calendar = self.calendar_download
        direct = self.direct_download
        prior = self.prior_year

        self.assertEqual(372, len(calendar.events))
        self.assertEqual(372, len(direct.events))
        self.assertEqual(497, len(prior.events))
        self.assertEqual((8, 8, 8), tuple(
            len(item.subject_catalog) for item in (calendar, direct, prior)
        ))
        self.assertEqual(
            ("-//UXXIAC-GRD//ES", "Horario estudiante", True),
            (
                calendar.source_metadata.prodid,
                calendar.source_metadata.calendar_name,
                calendar.source_metadata.has_utf8_bom,
            ),
        )
        self.assertEqual(
            ("-//secvirtual.uv.es//SECVIRTUAL UV", "Horarios 2027", False),
            (
                direct.source_metadata.prodid,
                direct.source_metadata.calendar_name,
                direct.source_metadata.has_utf8_bom,
            ),
        )
        self.assertEqual(
            ("-//secvirtual.uv.es//SECVIRTUAL UV", "Horarios 2026", False),
            (
                prior.source_metadata.prodid,
                prior.source_metadata.calendar_name,
                prior.source_metadata.has_utf8_bom,
            ),
        )
        self.assertEqual(
            ((2026, 9, 14), (2027, 5, 18)),
            _date_bounds(calendar),
        )
        self.assertEqual(_date_bounds(calendar), _date_bounds(direct))
        self.assertEqual(
            ((2025, 9, 15), (2026, 5, 12)),
            _date_bounds(prior),
        )
        self.assertEqual(
            "Tecnología Farmaceutica I",
            calendar.subject_catalog["34082"],
        )

    def test_raw_boundary_preserves_description_and_location_presence(self) -> None:
        calendar = self.calendar_download
        direct = self.direct_download
        prior = self.prior_year

        self.assertEqual(len(calendar.events), len(calendar.raw_events))
        self.assertEqual(len(direct.events), len(direct.raw_events))
        self.assertEqual(len(prior.events), len(prior.raw_events))
        self.assertEqual(
            372,
            sum(bool(event.location and event.location.strip()) for event in calendar.raw_events),
        )
        self.assertEqual(
            0,
            sum(event.location is not None for event in direct.raw_events),
        )
        self.assertEqual(
            372,
            sum(bool(event.description and event.description.strip()) for event in direct.raw_events),
        )
        self.assertEqual(
            496,
            sum(bool(event.description and event.description.strip()) for event in prior.raw_events),
        )
        blank_descriptions = [
            event
            for event in prior.raw_events
            if event.description is not None and not event.description.strip()
        ]
        self.assertEqual(1, len(blank_descriptions))
        self.assertEqual(
            "20260330T1000-20260330T1200-34090-DG-E1",
            blank_descriptions[0].uid,
        )
        self.assertEqual(
            {"known": 496, "absent": 1},
            Counter(event.location_identity.state for event in prior.events),
        )

    def test_current_formats_project_to_the_same_semantic_calendar(self) -> None:
        self.assertEqual("calendar-download", self.calendar_download.source_format.adapter_id)
        self.assertEqual("direct-download", self.direct_download.source_format.adapter_id)
        self.assertEqual(1.0, self.calendar_download.source_format.confidence)
        self.assertEqual(1.0, self.direct_download.source_format.confidence)
        self.assertEqual(
            canonical_sha256(self.calendar_download.events),
            canonical_sha256(self.direct_download.events),
        )
        for baseline, current in (
            (self.calendar_download, self.direct_download),
            (self.direct_download, self.calendar_download),
        ):
            with self.subTest(baseline=baseline.source_path.name):
                comparison = compare_calendars(
                    baseline,
                    current,
                    analyzed_at_utc="2026-09-07T00:00:00Z",
                )
                self.assertEqual("unchanged", comparison.status)
                self.assertEqual(0, sum(comparison.summary.values()))
                self.assertEqual((), comparison.projection_diagnostics)

        self.assertEqual(
            Counter(event.location_identity.canonical_key for event in self.calendar_download.events),
            Counter(event.location_identity.canonical_key for event in self.direct_download.events),
        )
        self.assertEqual(
            8,
            len({event.location_identity.canonical_key for event in self.calendar_download.events}),
        )
        self.assertEqual({"known"}, {event.location_identity.state for event in self.calendar_download.events})
        self.assertEqual({"known"}, {event.location_identity.state for event in self.direct_download.events})
        self.assertEqual(
            Counter(event.activity_identity.key for event in self.calendar_download.events),
            Counter(event.activity_identity.key for event in self.direct_download.events),
        )
        self.assertFalse(
            {event.uid for event in self.calendar_download.events}
            & {event.uid for event in self.direct_download.events}
        )

    def test_current_formats_have_identical_collision_results(self) -> None:
        calendar = analyze_collisions(self.calendar_download.events)
        direct = analyze_collisions(self.direct_download.events)

        self.assertEqual(
            (372, 19, 16, 13),
            (
                calendar.event_count,
                calendar.collision_count,
                calendar.laboratory_collision_count,
                calendar.affected_laboratory_count,
            ),
        )
        self.assertEqual(
            (
                calendar.event_count,
                calendar.collision_count,
                calendar.laboratory_collision_count,
                calendar.affected_laboratory_count,
            ),
            (
                direct.event_count,
                direct.collision_count,
                direct.laboratory_collision_count,
                direct.affected_laboratory_count,
            ),
        )

    def test_prior_year_is_unrelated_to_both_current_formats(self) -> None:
        for baseline in (self.calendar_download, self.direct_download):
            with self.subTest(baseline=baseline.source_path.name):
                comparison = compare_calendars(
                    baseline,
                    self.prior_year,
                    analyzed_at_utc="2026-09-07T00:00:00Z",
                )
                self.assertTrue(comparison.possibly_unrelated)
                self.assertEqual(
                    "subject overlap 25%, date-range overlap 0%, date gap 125 days",
                    comparison.unrelated_reason,
                )
                self.assertEqual(435, comparison.summary["added"])
                self.assertEqual(310, comparison.summary["removed"])
                self.assertEqual(62, comparison.summary["modified"])


def _date_bounds(calendar) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    first = min(event.start.date() for event in calendar.events)
    last = max(event.end.date() for event in calendar.events)
    return (
        (first.year, first.month, first.day),
        (last.year, last.month, last.day),
    )


if __name__ == "__main__":
    unittest.main()
