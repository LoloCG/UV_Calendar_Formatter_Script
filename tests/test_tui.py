import tempfile
import unittest
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from textual.widgets import Button, DataTable, Input, Static, TextArea

from core.change_tracking import compare_calendars
from core.models import CalendarEventData, GenerationResult, LoadedCalendar
from core.state_store import CalendarStateStore
from core.ui import CalendarFormatterApp
from core.ui.app import CollisionReviewScreen, ComparisonInfoScreen
from utils.file_selector import default_desktop_directory


class CalendarFormatterAppTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_analysis_remember_and_generate_are_independent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "fixture.ics"
            source.write_bytes(b"source calendar")
            loaded = _loaded_calendar(source)
            generation_calls = []

            def generate(calendar: LoadedCalendar) -> GenerationResult:
                generation_calls.append((calendar, dict(app.working_subject_names)))
                return GenerationResult(root / "generated.ics", root / "calendar_config.json", len(calendar.events), True)

            app = CalendarFormatterApp(
                file_picker=lambda: source,
                calendar_loader=lambda _: loaded,
                calendar_generator=generate,
                config_path=root / "calendar_config.json",
                suspend_file_picker=False,
            )
            async with app.run_test(size=(110, 42)) as pilot:
                await pilot.click("#select-file")
                await _wait_until(pilot, lambda: not app.query_one("#change-info", Button).disabled)

                self.assertEqual("first", app.comparison.status)
                change_table = app.query_one("#change-table", DataTable)
                self.assertEqual(0, change_table.row_count)
                self.assertFalse(change_table.display)
                self.assertFalse(app.query_one("#remember-baseline", Button).disabled)
                self.assertEqual(0, len(app.query("#collision-table")))
                self.assertFalse(app.query_one("#status", Static).display)
                self.assertEqual("First calendar analysis", str(app.query_one("#change-summary", Static).content))
                self.assertNotIn("SHA-256", str(app.query_one("#change-summary", Static).content))

                await pilot.click("#change-info")
                await _wait_until(pilot, lambda: isinstance(app.screen, ComparisonInfoScreen))
                comparison_details = str(app.screen.query_one("#comparison-info-content", Static).content)
                self.assertIn("Current analysis", comparison_details)
                self.assertIn("Source SHA-256", comparison_details)
                await pilot.click("#close-comparison-info")
                await _wait_until(pilot, lambda: not isinstance(app.screen, ComparisonInfoScreen))

                table = app.query_one("#subject-table", DataTable)
                table.focus(); table.action_select_cursor(); await pilot.pause()
                app.screen.query_one("#subject-name-input", Input).value = "Custom subject"
                await pilot.click("#save-subject-name")
                await _wait_until(pilot, lambda: len(app.query("#subject-name-input")) == 0)

                app._remember_confirmed(True)
                await _wait_until(pilot, lambda: app._baseline_accepted_current)
                self.assertTrue((root / "calendar_config.json").exists())
                self.assertTrue(app.query_one("#remember-baseline", Button).disabled)

                app._generation_confirmed(True)
                await _wait_until(pilot, lambda: app.generation_result is not None)
                self.assertEqual("Custom subject", generation_calls[0][1]["34082"])

                app._reset_confirmed(True)
                self.assertEqual("first", app.comparison.status)
                self.assertFalse(app.query_one("#remember-baseline", Button).disabled)
                self.assertFalse((root / "calendar_config.json").exists())

    async def test_initial_screen_mounts_at_compact_terminal_size(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = CalendarFormatterApp(config_path=Path(directory) / "calendar_config.json", file_picker=lambda: None, suspend_file_picker=False)
            async with app.run_test(size=(80, 24)):
                self.assertFalse(app.query_one("#select-file", Button).disabled)
                self.assertTrue(app.query_one("#generate-calendar", Button).disabled)
                self.assertEqual(default_desktop_directory() / "new_calendar.ics", app.output_path)
                self.assertEqual(0, len(app.query("#state-path")))
                self.assertFalse(app.query_one("#change-table", DataTable).display)

    async def test_output_picker_updates_calendar_and_both_report_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            selected = Path(directory) / "custom-calendar"
            app = CalendarFormatterApp(config_path=Path(directory) / "state.json", output_picker=lambda _: selected, file_picker=lambda: None, suspend_file_picker=False)
            async with app.run_test(size=(100, 36)) as pilot:
                app.query_one("#choose-output", Button).press(); await pilot.pause()
                self.assertEqual(selected.with_suffix(".ics"), app.output_path)
                self.assertEqual(selected.with_name("custom-calendar_collisions.txt"), app.report_path)
                self.assertEqual(selected.with_name("custom-calendar_changes.txt"), app.change_report_path)

    async def test_read_only_tracking_keeps_aliases_and_analysis_usable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "fixture.ics"
            source.write_bytes(b"source calendar")
            config = root / "calendar_config.json"
            config.write_text('{"34082": "Saved alias"}', encoding="utf-8")
            loaded = _loaded_calendar(source)
            app = CalendarFormatterApp(
                file_picker=lambda: source,
                calendar_loader=lambda _: loaded,
                config_path=config,
                suspend_file_picker=False,
            )
            app.state_store.is_writable = lambda: (False, "Tracking is read-only")

            async with app.run_test(size=(110, 42)) as pilot:
                await pilot.click("#select-file")
                await _wait_until(pilot, lambda: app.loaded_calendar is not None)

                self.assertEqual("Saved alias", app.working_subject_names["34082"])
                self.assertTrue(app.query_one("#remember-baseline", Button).disabled)
                self.assertFalse(app.query_one("#generate-calendar", Button).disabled)
                self.assertFalse(app.query_one("#review-collisions", Button).disabled)
                self.assertIn("read-only", str(app.query_one("#tracking-warning", Static).content))

    async def test_collision_review_is_a_dedicated_screen_and_preserves_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "collision.ics"; source.write_bytes(b"collisions")
            loaded = _loaded_collision_calendar(source)
            report_calls = []

            def write_report(analysis, calendar, names, output_path):
                report_calls.append((analysis, calendar, names, output_path)); return output_path.resolve()

            app = CalendarFormatterApp(file_picker=lambda: source, calendar_loader=lambda _: loaded, collision_report_writer=write_report, config_path=root / "state.json", suspend_file_picker=False)
            async with app.run_test(size=(110, 42)) as pilot:
                await pilot.click("#select-file")
                await _wait_until(pilot, lambda: app.collision_analysis is not None)
                original_calendar = app.loaded_calendar
                app.query_one("#review-collisions", Button).press()
                await _wait_until(pilot, lambda: isinstance(app.screen, CollisionReviewScreen))
                self.assertIsInstance(app.screen, CollisionReviewScreen)
                collision_table = app.screen.query_one("#collision-table", DataTable)
                await _wait_until(pilot, lambda: collision_table.row_count == 2)
                self.assertEqual(2, collision_table.row_count)
                collision_table.focus(); collision_table.action_select_cursor(); await pilot.pause()
                self.assertIn("Laboratory / Tutorial", str(app.screen.query_one("#collision-detail-content", Static).content))
                await pilot.click("#close-collision-detail"); await pilot.pause()
                await pilot.click("#view-collision-report"); await pilot.pause()
                self.assertIn("CALENDAR COLLISION REPORT", app.screen.query_one("#collision-report-content", TextArea).text)
                await pilot.click("#close-report-preview"); await pilot.pause()
                await pilot.click("#save-collision-report")
                await _wait_until(pilot, lambda: app.report_result_path is not None)
                self.assertEqual(1, len(report_calls))
                await pilot.click("#back-from-collisions"); await pilot.pause()
                self.assertEqual(original_calendar, app.loaded_calendar)
                self.assertEqual(0, len(app.query("#collision-table")))

    async def test_unchanged_calendar_has_compact_summary_and_detailed_info(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "fixture.ics"
            source.write_bytes(b"source calendar")
            loaded = _loaded_calendar(source)
            config_path = root / "calendar_config.json"
            store = CalendarStateStore(config_path)
            first = compare_calendars(None, loaded)
            store.accept_baseline(loaded, first, {"34082": "Technology"})

            app = CalendarFormatterApp(
                file_picker=lambda: source,
                calendar_loader=lambda _: loaded,
                config_path=config_path,
                suspend_file_picker=False,
            )
            async with app.run_test(size=(110, 42)) as pilot:
                await pilot.click("#select-file")
                await _wait_until(pilot, lambda: app.comparison is not None)

                self.assertEqual("unchanged", app.comparison.status)
                self.assertEqual("No calendar changes", str(app.query_one("#change-summary", Static).content))
                self.assertFalse(app.query_one("#change-table", DataTable).display)
                await pilot.click("#change-info")
                await _wait_until(pilot, lambda: isinstance(app.screen, ComparisonInfoScreen))
                details = str(app.screen.query_one("#comparison-info-content", Static).content)
                self.assertIn("Accepted baseline", details)
                self.assertIn("Accepted (UTC):", details)
                self.assertIn("Canonical SHA-256", details)

    async def test_change_table_is_shown_when_there_are_event_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline_path = root / "baseline.ics"
            current_path = root / "current.ics"
            baseline_path.write_bytes(b"baseline")
            current_path.write_bytes(b"current")
            baseline = _loaded_calendar(baseline_path)
            current_events = (replace(baseline.events[0], location="NEW ROOM"), *baseline.events[1:])
            current = LoadedCalendar(current_path, "", current_events, baseline.subject_catalog)
            comparison = compare_calendars(baseline, current)
            app = CalendarFormatterApp(config_path=root / "state.json", file_picker=lambda: None, suspend_file_picker=False)

            async with app.run_test(size=(100, 36)):
                app.comparison = comparison
                app._populate_change_table()
                table = app.query_one("#change-table", DataTable)
                self.assertEqual("changed", comparison.status)
                self.assertTrue(table.display)
                self.assertEqual(1, table.row_count)


async def _wait_until(pilot, condition, attempts: int = 300) -> None:
    for _ in range(attempts):
        if condition(): return
        await pilot.pause(0.02)
    raise AssertionError("Timed out waiting for the Textual worker")


def _loaded_calendar(path: Path) -> LoadedCalendar:
    timezone = ZoneInfo("Europe/Madrid")
    events = tuple(CalendarEventData(f"event-{index}", "34082", "Technology", "THEORY", "DG-T", datetime(2026, 9, 14, 10 + index, tzinfo=timezone), datetime(2026, 9, 14, 11 + index, tzinfo=timezone), None, "ROOM") for index in range(2))
    return LoadedCalendar(path, "", events, {"34082": "Technology"})


def _loaded_collision_calendar(path: Path) -> LoadedCalendar:
    timezone = ZoneInfo("Europe/Madrid")
    values = (("lab-1", "34082", "Technology", "LABORATORIO", "DG-L1", 14, 10, 12), ("tutorial-1", "99999", "New", "Tutoría", "DG-U1", 14, 11, 13), ("seminar-1", "11111", "Seminar", "SEMINARIO", "DG-E1", 15, 9, 11), ("class-1", "22222", "Class", "TEORÍA", "DG-T", 15, 10, 12))
    events = tuple(CalendarEventData(uid, sid, subject, kind, group, datetime(2026, 9, day, start, tzinfo=timezone), datetime(2026, 9, day, end, tzinfo=timezone), None, "ROOM") for uid, sid, subject, kind, group, day, start, end in values)
    return LoadedCalendar(path, "", events, {event.subject_id: event.original_subject for event in events})


if __name__ == "__main__":
    unittest.main()
