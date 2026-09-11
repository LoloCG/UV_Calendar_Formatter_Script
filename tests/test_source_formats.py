import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from core.change_tracking import compare_calendars
from core.models import (
    ActivityIdentity,
    CalendarEventData,
    CalendarSourceMetadata,
    LoadedCalendar,
    LocationIdentity,
    RawCalendarEvent,
)
from core.semantic import (
    resolve_baseline_location_fallbacks,
    resolve_same_calendar_location_fallbacks,
)
from core.source_formats import project_calendar


class SourceFormatAdapterTests(unittest.TestCase):
    def test_mixed_calendar_uses_event_shape_and_reports_diagnostic(self) -> None:
        projection = project_calendar(
            CalendarSourceMetadata(prodid="-//UXXIAC-GRD//ES"),
            (
                _raw(
                    "calendar",
                    "34082 - Subject(TEORÍA (34082))",
                    "DG-T - Grupo Teoría",
                    "21 BUILDING - AULA 1",
                ),
                _raw(
                    "direct",
                    "34082 - Subject Grupo Teoría DG-T",
                    "AULA 1 21",
                    None,
                ),
            ),
        )

        self.assertEqual("mixed", projection.evidence.adapter_id)
        self.assertEqual(
            {"calendar-download", "direct-download"},
            {event.adapter_id for event in projection.events},
        )
        self.assertIn("mixed-calendar-format", {item.code for item in projection.diagnostics})
        self.assertEqual(
            projection.events[0].location_identity.canonical_key,
            projection.events[1].location_identity.canonical_key,
        )

    def test_unknown_event_is_preserved_and_requires_review(self) -> None:
        projection = project_calendar(
            CalendarSourceMetadata(),
            (_raw("unknown", "34082 - Readable subject", "unparsed note", None),),
        )

        event = projection.events[0]
        self.assertEqual("unknown", projection.evidence.adapter_id)
        self.assertEqual("Readable subject", event.original_subject)
        self.assertEqual("unknown", event.location_identity.state)
        self.assertEqual("unparsed note", event.location_identity.raw_value)
        self.assertEqual(
            "unknown", _calendar((event,), projection=projection).source_format.adapter_id
        )
        self.assertTrue(any(item.severity == "review" for item in projection.diagnostics))
        comparison = compare_calendars(None, _calendar((event,), projection=projection))
        self.assertFalse(comparison.can_remember)


class LocationFallbackTests(unittest.TestCase):
    def test_same_calendar_unanimous_location_is_inferred_with_provenance(self) -> None:
        known = _event("known", location=_known_location("21", "AULA 1"))
        missing = _event("missing", location=_unavailable_location(), day=2)
        loaded = _calendar((known, missing))

        resolved = resolve_same_calendar_location_fallbacks(loaded)
        inferred = resolved.events[1].location_identity

        self.assertEqual("inferred", inferred.state)
        self.assertEqual("same-calendar", inferred.provenance)
        self.assertEqual(("21", "aula 1"), inferred.canonical_key)

    def test_baseline_fallback_is_secondary_and_does_not_override_current(self) -> None:
        historical = _event("old", location=_known_location("21", "AULA 1"))
        unavailable = _event("new", location=_unavailable_location())
        explicit = _event("new", location=_known_location("21", "AULA 2"))
        baseline = _calendar((historical,))

        inferred_calendar = resolve_baseline_location_fallbacks(
            _calendar((unavailable,)), baseline
        )
        explicit_calendar = resolve_baseline_location_fallbacks(
            _calendar((explicit,)), baseline
        )

        self.assertEqual("accepted-baseline", inferred_calendar.events[0].location_identity.provenance)
        self.assertEqual("AULA 2", explicit_calendar.events[0].location)
        comparison = compare_calendars(baseline, explicit_calendar)
        self.assertEqual(("relocated",), comparison.event_changes[0].categories)

    def test_conflicting_fallback_needs_review_and_selects_no_room(self) -> None:
        candidates = (
            _event("one", location=_known_location("21", "AULA 1")),
            _event("two", location=_known_location("21", "AULA 2"), day=2),
            _event("missing", location=_unavailable_location(), day=3),
        )

        resolved = resolve_same_calendar_location_fallbacks(_calendar(candidates))

        self.assertEqual("conflicting", resolved.events[2].location_identity.state)
        self.assertEqual("", resolved.events[2].location)
        self.assertTrue(any(item.severity == "review" for item in resolved.projection_diagnostics))

    def test_different_inferred_location_is_review_not_confirmed_relocation(self) -> None:
        known = _event("old", location=_known_location("21", "AULA 1"))
        inferred = replace(
            _event("new", location=_known_location("21", "AULA 2")),
            location_identity=replace(
                _known_location("21", "AULA 2"),
                provenance="accepted-baseline",
                confidence="inferred",
                state="inferred",
            ),
        )

        comparison = compare_calendars(_calendar((known,)), _calendar((inferred,)))

        self.assertEqual("changed", comparison.status)
        self.assertEqual(0, comparison.summary["modified"])
        self.assertTrue(any(item.severity == "review" for item in comparison.projection_diagnostics))
        self.assertFalse(comparison.can_remember)


def _raw(uid, summary, description, location):
    start = datetime(2026, 9, 14, 10, tzinfo=ZoneInfo("Europe/Madrid"))
    return RawCalendarEvent(
        uid=uid,
        summary=summary,
        description=description,
        classification=None,
        categories=None,
        created=None,
        last_modified=None,
        start=start,
        end=start + timedelta(hours=1),
        location=location,
    )


def _known_location(building, room):
    return LocationIdentity(
        building_code=building,
        room_key=room.casefold(),
        display_value=room,
        raw_value=room,
        source_property="LOCATION",
    )


def _unavailable_location():
    return LocationIdentity(state="unavailable", confidence="unknown")


def _event(uid, *, location, day=1):
    start = datetime(2026, 9, day, 10, tzinfo=ZoneInfo("Europe/Madrid"))
    return CalendarEventData(
        uid=uid,
        subject_id="34082",
        original_subject="Subject",
        class_type="TEORÍA",
        group="DG-T",
        start=start,
        end=start + timedelta(hours=1),
        created=None,
        location=location.display_value,
        activity_identity=ActivityIdentity("teoria", "TEORÍA", "TEORÍA"),
        location_identity=location,
        adapter_id="test",
    )


def _calendar(events, projection=None):
    kwargs = {}
    if projection is not None:
        kwargs = {
            "source_format": projection.evidence,
            "projection_diagnostics": projection.diagnostics,
        }
    return LoadedCalendar(
        Path("source.ics"),
        "",
        tuple(events),
        {"34082": "Subject"},
        **kwargs,
    )


if __name__ == "__main__":
    unittest.main()
