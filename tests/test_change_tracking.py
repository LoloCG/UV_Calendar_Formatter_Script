import json
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from core.change_tracking import canonical_sha256, compare_calendars, unrelated_calendar_reason
from core.collision_detector import analyze_collisions
from core.models import CalendarEventData, LoadedCalendar
from core.state_store import CalendarStateStore, StateValidationError
from core.tracking_workflow import analyze_with_baseline
from reports.change_report import render_change_report


class ChangeTrackingTests(unittest.TestCase):
    def test_canonical_hash_ignores_uid_order_title_wording_and_equivalent_offset(self) -> None:
        madrid = ZoneInfo("Europe/Madrid")
        first = _event("old-1", start=datetime(2026, 9, 14, 10, tzinfo=madrid))
        second = _event("old-2", subject_id="2", start=datetime(2026, 9, 15, 10, tzinfo=madrid))
        equivalent_first = _event(
            "new-uid",
            subject="Different wording",
            start=first.start.astimezone(timezone.utc),
        )
        equivalent_first = _replace_end(equivalent_first, first.end.astimezone(timezone.utc))

        self.assertEqual(
            canonical_sha256((first, second)),
            canonical_sha256((second, equivalent_first)),
        )

    def test_comparison_reports_field_changes_and_changed_collision(self) -> None:
        first = _event("a", start=_time(10), end=_time(12), location="Room A")
        other = _event("b", subject_id="2", start=_time(11), end=_time(13))
        moved = _event("x", start=_time(10), end=_time(11, 30), location="Room B")
        baseline = _calendar(Path("baseline.ics"), (first, other))
        current = _calendar(Path("current.ics"), (other, moved))

        comparison = compare_calendars(
            baseline,
            current,
            baseline_collisions=analyze_collisions(baseline.events),
            current_collisions=analyze_collisions(current.events),
        )

        self.assertEqual("changed", comparison.status)
        self.assertEqual(1, comparison.summary["modified"])
        self.assertEqual(("rescheduled", "relocated"), comparison.event_changes[0].categories)
        self.assertEqual(1, comparison.summary["changed_collisions"])

    def test_second_pass_reports_regrouped_and_retyped(self) -> None:
        baseline = _calendar(Path("baseline.ics"), (_event("a", group="G1", activity="Theory"),))
        current = _calendar(Path("current.ics"), (_event("b", group="G2", activity="Lab"),))

        comparison = compare_calendars(baseline, current)

        self.assertEqual(("regrouped", "retyped"), comparison.event_changes[0].categories)
        self.assertEqual(0, comparison.summary["added"])
        self.assertEqual(0, comparison.summary["removed"])

    def test_collision_comparison_reports_resolved_and_new_pairs(self) -> None:
        first = _event("a", start=_time(10), end=_time(12))
        second = _event("b", subject_id="2", start=_time(11), end=_time(13))
        moved_first = _event("a2", start=_time(14), end=_time(15))
        added = _event("c", subject_id="3", start=_time(12), end=_time(14))

        comparison = compare_calendars(
            _calendar(Path("baseline.ics"), (first, second)),
            _calendar(Path("current.ics"), (moved_first, second, added)),
        )

        self.assertEqual(1, comparison.summary["resolved_collisions"])
        self.assertEqual(1, comparison.summary["new_collisions"])

    def test_equal_pairing_choices_remain_added_removed_and_need_review(self) -> None:
        baseline = _calendar(
            Path("baseline.ics"),
            (_event("a", start=_time(10)), _event("b", start=_time(12))),
        )
        current = _calendar(
            Path("current.ics"),
            (_event("c", start=_time(11)), _event("d", start=_time(11))),
        )

        comparison = compare_calendars(baseline, current)

        self.assertEqual(2, comparison.summary["added"])
        self.assertEqual(2, comparison.summary["removed"])
        self.assertEqual(1, comparison.summary["ambiguous"])
        self.assertEqual(0, comparison.summary["modified"])

    def test_first_analysis_has_no_added_rows(self) -> None:
        comparison = compare_calendars(None, _calendar(Path("current.ics"), (_event("a"),)))
        self.assertEqual("first", comparison.status)
        self.assertEqual((), comparison.event_changes)
        self.assertIn("first analysis", render_change_report(comparison).casefold())

    def test_unrelated_heuristic_allows_partial_export_but_flags_distant_year(self) -> None:
        baseline = (_event("a", start=_time(10)),)
        partial = (_event("b", start=_time(10) + timedelta(days=2)),)
        distant = (_event("c", subject_id="99", start=_time(10) + timedelta(days=200)),)
        self.assertFalse(unrelated_calendar_reason(baseline, partial)[0])
        self.assertTrue(unrelated_calendar_reason(baseline, distant)[0])


class StateStoreTests(unittest.TestCase):
    def test_legacy_aliases_migrate_with_backup_and_first_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "calendar_config.json"
            state_path.write_text('{"1": "Custom"}', encoding="utf-8")
            source = root / "source.ics"
            source.write_bytes(b"exact raw source")
            loaded = _calendar(source, (_event("a"),))
            store = CalendarStateStore(state_path)
            comparison = compare_calendars(None, loaded)

            store.accept_baseline(loaded, comparison, {"1": "Custom"}, accepted_at_utc="2026-09-03T10:00:00Z")
            manifest = store.load()

            self.assertEqual(2, manifest["schema_version"])
            self.assertEqual("Custom", manifest["subject_names"]["1"])
            baseline_path = store.verified_baseline_path(manifest)
            self.assertEqual(b"exact raw source", baseline_path.read_bytes())
            self.assertTrue(state_path.with_suffix(".json.legacy.bak").exists())

    def test_external_legacy_discovery_is_one_time_after_migration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / "calendar_config.json"
            state_path = root / "data" / "calendar_config.json"
            legacy.write_text('{"1": "Custom"}', encoding="utf-8")
            store = CalendarStateStore(state_path, legacy_path=legacy)

            store.save_subject_names(store.subject_names())

            self.assertFalse(legacy.exists())
            self.assertTrue(legacy.with_suffix(".json.legacy.bak").exists())
            store.reset()
            self.assertEqual({}, store.subject_names())

    def test_unchanged_check_does_not_replace_last_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = CalendarStateStore(root / "calendar_config.json")
            old_path, new_path = root / "old.ics", root / "new.ics"
            old_path.write_bytes(b"old"); new_path.write_bytes(b"new")
            old = _calendar(old_path, (_event("a"),))
            first = compare_calendars(None, old)
            store.accept_baseline(old, first, {})
            new = _calendar(new_path, (_event("b", location="Elsewhere"),))
            changed = compare_calendars(old, new, baseline_metadata=store.baseline_metadata())
            store.accept_baseline(new, changed, {})
            last_change = store.load()["tracking"]["last_change"]
            unchanged = compare_calendars(new, new, baseline_metadata=store.baseline_metadata())

            store.record_last_check(unchanged)
            final = store.load()

            self.assertEqual(last_change, final["tracking"]["last_change"])
            self.assertEqual("unchanged", final["tracking"]["last_check"]["result"])
            self.assertEqual(1, len(list(store.baseline_dir.glob("*.ics"))))

    def test_future_schema_and_corrupt_baseline_path_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calendar_config.json"
            path.write_text(json.dumps({"schema_version": 99, "subject_names": {}, "tracking": {}}), encoding="utf-8")
            with self.assertRaises(StateValidationError):
                CalendarStateStore(path).load()

    def test_interrupted_manifest_replace_keeps_previous_baseline_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = CalendarStateStore(root / "calendar_config.json")
            old_path, new_path = root / "old.ics", root / "new.ics"
            old_path.write_bytes(b"old source")
            new_path.write_bytes(b"new source")
            old = _calendar(old_path, (_event("old"),))
            store.accept_baseline(old, compare_calendars(None, old), {})
            old_metadata = store.baseline_metadata()
            new = _calendar(new_path, (_event("new", location="New room"),))
            changed = compare_calendars(old, new, baseline_metadata=old_metadata)

            import os

            real_replace = os.replace

            def fail_manifest_replace(source, target):
                if Path(target) == store.path:
                    raise OSError("simulated interruption")
                return real_replace(source, target)

            with patch("core.state_store.os.replace", side_effect=fail_manifest_replace):
                with self.assertRaises(OSError):
                    store.accept_baseline(new, changed, {})

            self.assertEqual(old_metadata, store.baseline_metadata())
            self.assertEqual(b"old source", store.verified_baseline_path().read_bytes())

    def test_real_raw_baseline_is_reparsed_and_unchanged_check_is_lightweight(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = Path("test_files/new_format.ics")
            first_path, second_path = root / "first.ics", root / "renamed.ics"
            first_path.write_bytes(source.read_bytes())
            second_path.write_bytes(source.read_bytes())
            from core.calendar_workflow import load_calendar

            first = load_calendar(first_path)
            store = CalendarStateStore(root / "calendar_config.json")
            store.accept_baseline(first, compare_calendars(None, first), {})
            second = load_calendar(second_path)

            comparison, warning = analyze_with_baseline(
                store,
                second,
                analyze_collisions(second.events),
            )

            self.assertEqual("unchanged", comparison.status)
            self.assertEqual("", warning)
            self.assertNotIn("last_change", store.load()["tracking"])
            self.assertEqual(1, len(list(store.baseline_dir.glob("*.ics"))))


def _time(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 14, hour, minute, tzinfo=ZoneInfo("Europe/Madrid"))


def _event(uid: str, *, subject_id: str = "1", subject: str = "Subject", activity: str = "Theory", group: str = "G1", start: datetime | None = None, end: datetime | None = None, location: str = "Room A") -> CalendarEventData:
    start = start or _time(10)
    end = end or start + timedelta(hours=1)
    return CalendarEventData(uid, subject_id, subject, activity, group, start, end, None, location)


def _replace_end(event: CalendarEventData, end: datetime) -> CalendarEventData:
    return CalendarEventData(event.uid, event.subject_id, event.original_subject, event.class_type, event.group, event.start, end, event.created, event.location)


def _calendar(path: Path, events: tuple[CalendarEventData, ...]) -> LoadedCalendar:
    subjects = {event.subject_id: event.original_subject for event in events if event.subject_id}
    return LoadedCalendar(path, "", events, subjects)


if __name__ == "__main__":
    unittest.main()
