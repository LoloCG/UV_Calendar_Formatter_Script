from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from pathlib import Path

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.scrollbar import ScrollBar, ScrollBarRender
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, LoadingIndicator, Static, TextArea

from core import __version__
from core.calendar_workflow import DEFAULT_CONFIG_PATH, DEFAULT_OUTPUT_PATH, generate_formatted_calendar, load_calendar, prepare_subject_names
from core.change_tracking import compare_calendars
from core.collision_detector import analyze_collisions, collision_category, orient_collision
from core.models import CalendarComparison, CalendarEventData, CollisionAnalysis, CollisionPair, GenerationResult, LoadedCalendar
from core.semantic import event_location_identity
from core.state_store import CalendarStateStore
from core.tracking_workflow import analyze_with_baseline
from reports.change_report import default_change_report_path, render_change_report, write_change_report
from reports.collision_report import default_collision_report_path, render_collision_report, write_collision_report
from utils.file_selector import default_desktop_directory, pick_file, pick_save_file


class SolidScrollBarRender(ScrollBarRender):
    """Render scrollbars without font-dependent fractional block glyphs."""

    VERTICAL_BARS = [" "] * 8
    HORIZONTAL_BARS = [" "] * 8


ScrollBar.renderer = SolidScrollBarRender


FilePicker = Callable[[], Path | None]
OutputPicker = Callable[[Path], Path | None]
CalendarLoader = Callable[[Path], LoadedCalendar]
CalendarGenerator = Callable[[LoadedCalendar], GenerationResult]
CollisionAnalyzer = Callable[[tuple[CalendarEventData, ...]], CollisionAnalysis]
CollisionReportWriter = Callable[[CollisionAnalysis, LoadedCalendar, Mapping[str, str], Path], Path]


class ConfirmGenerationScreen(ModalScreen[bool]):
    def __init__(self, output_path: Path, config_will_save: bool) -> None:
        super().__init__()
        self.output_path = output_path
        self.config_will_save = config_will_save

    def compose(self) -> ComposeResult:
        config_text = ("The subject names shown in the table will be saved and applied." if self.config_will_save else "Subject names will be applied to the output but cannot be persisted because tracking storage is unavailable.")
        with Vertical(id="confirm-dialog"):
            yield Label("Generate the formatted calendar?", id="confirm-title")
            yield Static(f"Output: {self.output_path.resolve()}\n\n{config_text} Generating does not accept or replace the comparison baseline.")
            with Horizontal(classes="dialog-actions"):
                yield Button("Cancel", id="cancel-generation")
                yield Button("Generate", id="confirm-generation", variant="success")

    @on(Button.Pressed, "#cancel-generation")
    def cancel_generation(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#confirm-generation")
    def confirm_generation(self) -> None:
        self.dismiss(True)


class ConfirmRememberScreen(ModalScreen[bool]):
    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Label("Remember this calendar as the baseline?", id="confirm-title")
            yield Static("The exact selected ICS will become the reference for the next comparison. Formatted-calendar generation is independent of this action.")
            with Horizontal(classes="dialog-actions"):
                yield Button("Cancel", id="cancel-remember")
                yield Button("Remember as baseline", id="confirm-remember", variant="success")

    @on(Button.Pressed, "#cancel-remember")
    def cancel(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#confirm-remember")
    def confirm(self) -> None:
        self.dismiss(True)


class SubjectNameEditorScreen(ModalScreen[tuple[str, str] | None]):
    BINDINGS = [("escape", "cancel_edit", "Cancel")]

    def __init__(self, subject_id: str, original_name: str, output_name: str) -> None:
        super().__init__()
        self.subject_id, self.original_name, self.output_name = subject_id, original_name, output_name

    def compose(self) -> ComposeResult:
        with Vertical(id="subject-editor-dialog"):
            yield Label(f"Edit subject {self.subject_id}", id="subject-editor-title")
            yield Static(f"UV name: {self.original_name}", id="subject-original-name")
            yield Label("Output name")
            yield Input(value=self.output_name, id="subject-name-input", select_on_focus=False)
            yield Static("", id="subject-name-error")
            with Horizontal(classes="dialog-actions"):
                yield Button("Use UV name", id="use-original-subject-name")
                yield Button("Cancel", id="cancel-subject-name")
                yield Button("Save name", id="save-subject-name", variant="success")

    def on_mount(self) -> None:
        widget = self.query_one("#subject-name-input", Input)
        widget.focus()
        widget.cursor_position = len(widget.value)

    @on(Button.Pressed, "#use-original-subject-name")
    def use_original_name(self) -> None:
        self.dismiss((self.subject_id, self.original_name))

    @on(Button.Pressed, "#cancel-subject-name")
    def cancel_edit(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#save-subject-name")
    @on(Input.Submitted, "#subject-name-input")
    def save_name(self) -> None:
        output_name = self.query_one("#subject-name-input", Input).value.strip()
        error = self.query_one("#subject-name-error", Static)
        if not output_name:
            error.update("The output name cannot be empty.")
            return
        if any(ord(character) < 32 for character in output_name):
            error.update("The output name cannot contain control characters.")
            return
        self.dismiss((self.subject_id, output_name))

    def action_cancel_edit(self) -> None:
        self.dismiss(None)


class CollisionDetailScreen(ModalScreen[None]):
    BINDINGS = [("escape", "close_detail", "Close")]

    def __init__(self, collision: CollisionPair, subject_names: Mapping[str, str]) -> None:
        super().__init__()
        self.collision, self.subject_names = collision, subject_names

    def compose(self) -> ComposeResult:
        first, second = orient_collision(self.collision)
        with Vertical(id="collision-detail-dialog"):
            yield Label("Collision details", id="collision-detail-title")
            yield Static("\n".join((f"Category: {collision_category(self.collision)}", f"Overlap: {self.collision.overlap_start:%Y-%m-%d %H:%M}–{self.collision.overlap_end:%H:%M}", "", _event_detail("Event", first, self.subject_names), "", _event_detail("Collides with", second, self.subject_names))), id="collision-detail-content")
            yield Button("Close", id="close-collision-detail", variant="primary")

    @on(Button.Pressed, "#close-collision-detail")
    def close_from_button(self) -> None:
        self.dismiss(None)

    def action_close_detail(self) -> None:
        self.dismiss(None)


class TextReportScreen(ModalScreen[None]):
    BINDINGS = [("escape", "close_report", "Close")]

    def __init__(self, title: str, report_text: str, content_id: str) -> None:
        super().__init__()
        self.report_title, self.report_text, self.content_id = title, report_text, content_id

    def compose(self) -> ComposeResult:
        with Vertical(id="report-preview-dialog"):
            yield Label(self.report_title, id="report-preview-title")
            yield TextArea(self.report_text, read_only=True, show_cursor=False, show_line_numbers=False, highlight_cursor_line=False, id=self.content_id, classes="report-preview-content")
            with Horizontal(id="report-preview-actions"):
                yield Button("Close", id="close-report-preview", variant="primary", compact=True)

    def on_mount(self) -> None:
        self.query_one(f"#{self.content_id}", TextArea).focus()

    @on(Button.Pressed, "#close-report-preview")
    def close_from_button(self) -> None:
        self.dismiss(None)

    def action_close_report(self) -> None:
        self.dismiss(None)


class ComparisonInfoScreen(ModalScreen[None]):
    """Detailed tracking metadata kept out of the main workflow."""

    BINDINGS = [("escape", "close_info", "Close")]

    def __init__(self, comparison: CalendarComparison) -> None:
        super().__init__()
        self.comparison = comparison

    def compose(self) -> ComposeResult:
        with Vertical(id="comparison-info-dialog"):
            yield Label("Calendar comparison details", id="comparison-info-title")
            yield Static(_comparison_info_text(self.comparison), id="comparison-info-content")
            yield Button("Close", id="close-comparison-info", variant="primary", compact=True)

    @on(Button.Pressed, "#close-comparison-info")
    def close_from_button(self) -> None:
        self.dismiss(None)

    def action_close_info(self) -> None:
        self.dismiss(None)


class CollisionReviewScreen(Screen[None]):
    """Dedicated non-modal home for complete collision review and reporting."""

    BINDINGS = [("escape", "go_back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header(icon="")
        with VerticalScroll(id="collision-content"):
            yield Label("Collision analysis", classes="screen-title")
            yield Static("", id="collision-full-summary")
            yield DataTable(id="collision-table")
            yield Static("Select a row and press Enter to inspect both sessions.", id="collision-help")
            yield Label("Collision report", classes="section-title")
            yield Static("", id="collision-report-path")
            with Horizontal(id="collision-report-actions"):
                yield Button("View report", id="view-collision-report", variant="primary")
                yield Button("Save collision report", id="save-collision-report")
                yield Button("Back", id="back-from-collisions")
        yield Footer(show_command_palette=False)

    @property
    def formatter(self) -> CalendarFormatterApp:
        return self.app  # type: ignore[return-value]

    def on_mount(self) -> None:
        table = self.query_one("#collision-table", DataTable)
        for title, key in (("Date", "date"), ("Overlap", "overlap"), ("Category", "category"), ("Event", "event"), ("Collides with", "other")):
            table.add_column(title, key=key)
        table.cursor_type, table.zebra_stripes = "row", True
        analysis = self.formatter.collision_analysis
        if analysis is None:
            return
        self.query_one("#collision-full-summary", Static).update(self.formatter.collision_summary_text())
        self.query_one("#collision-report-path", Static).update(str(self.formatter.report_path.resolve()))
        for index, collision in enumerate(analysis.collisions):
            first, second = orient_collision(collision)
            table.add_row(collision.overlap_start.date().isoformat(), f"{collision.overlap_start:%H:%M}–{collision.overlap_end:%H:%M}", collision_category(collision), self.formatter.event_display_name(first), self.formatter.event_display_name(second), key=str(index))

    @on(DataTable.RowSelected, "#collision-table")
    def show_collision_detail(self, event: DataTable.RowSelected) -> None:
        analysis = self.formatter.collision_analysis
        if analysis is None:
            return
        try:
            collision = analysis.collisions[int(str(event.row_key.value))]
        except (ValueError, IndexError):
            return
        self.app.push_screen(CollisionDetailScreen(collision, dict(self.formatter.working_subject_names)))

    @on(Button.Pressed, "#view-collision-report")
    def view_report(self) -> None:
        app = self.formatter
        if app.loaded_calendar is not None and app.collision_analysis is not None:
            self.app.push_screen(TextReportScreen("Collision report preview", render_collision_report(app.collision_analysis, app.loaded_calendar, app.working_subject_names), "collision-report-content"))

    @on(Button.Pressed, "#save-collision-report")
    def save_report(self) -> None:
        self.formatter.save_collision_report()

    @on(Button.Pressed, "#back-from-collisions")
    def go_back_button(self) -> None:
        self.action_go_back()

    def action_go_back(self) -> None:
        self.app.pop_screen()


class CalendarFormatterApp(App[None]):
    CSS_PATH = "calendar_formatter.tcss"
    TITLE = f"UV Calendar Formatter v{__version__}"
    SUB_TITLE = "Calendar import, comparison, and generation"
    BINDINGS = [("q", "quit_app", "Quit"), ("c", "review_collisions", "Collisions")]

    def __init__(self, *, file_picker: FilePicker | None = None, output_picker: OutputPicker | None = None, calendar_loader: CalendarLoader = load_calendar, calendar_generator: CalendarGenerator | None = None, collision_analyzer: CollisionAnalyzer = analyze_collisions, collision_report_writer: CollisionReportWriter = write_collision_report, config_path: str | Path = DEFAULT_CONFIG_PATH, output_path: str | Path | None = None, suspend_file_picker: bool = True) -> None:
        super().__init__()
        self._file_picker, self._output_picker = file_picker, output_picker
        self._calendar_loader, self._calendar_generator = calendar_loader, calendar_generator
        self._collision_analyzer, self._collision_report_writer = collision_analyzer, collision_report_writer
        self._suspend_file_picker = suspend_file_picker
        self.config_path = Path(config_path)
        self.state_store = CalendarStateStore(self.config_path)
        self.output_path = Path(output_path) if output_path else default_desktop_directory() / DEFAULT_OUTPUT_PATH.name
        self.report_path = default_collision_report_path(self.output_path)
        self.change_report_path = default_change_report_path(self.output_path)
        self.loaded_calendar: LoadedCalendar | None = None
        self.collision_analysis: CollisionAnalysis | None = None
        self.comparison: CalendarComparison | None = None
        self.generation_result: GenerationResult | None = None
        self.report_result_path: Path | None = None
        self.change_report_result_path: Path | None = None
        self.working_subject_names: dict[str, str] = {}
        self.initial_subject_names: dict[str, str] = {}
        self.configured_subject_ids: frozenset[str] = frozenset()
        self.modified_subject_ids: set[str] = set()
        self._subject_names_ready = self._busy = False
        self._tracking_available = True
        self._tracking_warning = ""
        self._baseline_accepted_current = False
        self._showing_remembered_baseline = False

    def compose(self) -> ComposeResult:
        yield Header(icon="")
        with VerticalScroll(id="main-content"):
            yield Label("Your remembered calendar loads automatically. Select an ICS calendar to start or check for updates.", id="intro")
            with Horizontal(id="file-actions"):
                yield Button("Select ICS calendar", id="select-file", variant="primary")
                yield Button("Exit", id="exit-app", variant="error")
            yield Static("No calendar selected.", id="selected-path")
            yield Static("", id="tracking-warning")
            yield LoadingIndicator(id="loader")
            yield Static("Waiting for a calendar.", id="status")
            yield Static("", id="calendar-summary")
            with Horizontal(id="change-heading"):
                yield Label("Changes since previous calendar", id="change-title", classes="section-title")
                yield Button("Info", id="change-info", disabled=True, compact=True)
            yield Static("Select a calendar to compare it with the accepted baseline.", id="change-summary")
            yield DataTable(id="change-table")
            with Horizontal(id="change-actions"):
                yield Button("View changes", id="view-changes", variant="primary", disabled=True)
                yield Button("Save change report", id="save-change-report", disabled=True)
                yield Button("Remember as baseline", id="remember-baseline", variant="success", disabled=True)
            yield Label("Collision status", classes="section-title")
            yield Static("Select a calendar to calculate timetable collisions.", id="collision-summary")
            yield Button("Review collisions", id="review-collisions", disabled=True)
            yield Label("Unique subjects (select a row and press Enter to edit its output name)", classes="section-title")
            yield DataTable(id="subject-table")
            yield Label("Output calendar", classes="section-title")
            with Horizontal(id="output-actions"):
                yield Static(str(self.output_path.resolve()), id="output-path")
                yield Button("Choose output…", id="choose-output")
            with Horizontal(id="generation-actions"):
                yield Button("Generate formatted ICS", id="generate-calendar", variant="success", disabled=True)
        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        self.query_one("#loader", LoadingIndicator).display = False
        table = self.query_one("#subject-table", DataTable)
        for title, key in (("Subject ID", "subject_id"), ("UV name", "original_name"), ("Output name", "output_name"), ("Sessions", "sessions"), ("Status", "status")):
            table.add_column(title, key=key)
        table.cursor_type, table.zebra_stripes = "row", True
        changes = self.query_one("#change-table", DataTable)
        for title, key in (("Date", "date"), ("Change", "change"), ("Subject / session", "session"), ("Previous", "previous"), ("Current", "current")):
            changes.add_column(title, key=key)
        changes.cursor_type, changes.zebra_stripes = "row", True
        changes.display = False
        self.query_one("#view-changes", Button).display = False
        self.query_one("#save-change-report", Button).display = False
        writable, warning = self.state_store.is_writable()
        if not writable:
            self._tracking_available = False
            self._tracking_warning = warning
        tracking_warning = self.query_one("#tracking-warning", Static)
        tracking_warning.update(self._tracking_warning)
        tracking_warning.display = bool(self._tracking_warning)
        try:
            manifest = self.state_store.load()
            baseline_path = self.state_store.verified_baseline_path(manifest)
            baseline_metadata = manifest["tracking"].get("baseline")
        except Exception as error:
            self._tracking_available = False
            self._tracking_warning = f"Remembered calendar could not be loaded: {error}. Select an ICS calendar to continue."
            tracking_warning.update(self._tracking_warning)
            tracking_warning.display = True
            return
        if baseline_path is not None and baseline_metadata is not None:
            self.query_one("#select-file", Button).label = "Check updated ICS calendar"
            self.query_one("#selected-path", Static).update(f"Remembered calendar: {baseline_metadata['source_name']}")
            self._prepare_for_load(baseline_path, remembered=True)
            self._load_selected_calendar(baseline_path, persist_last_check=False, remembered=True)

    def on_ready(self) -> None:
        """Give Windows terminals a second complete first-frame repaint."""

        self.query_one("#select-file", Button).focus()
        self.set_timer(0.08, self._repaint_initial_frame, name="initial-frame-repaint")

    def _repaint_initial_frame(self) -> None:
        # Some terminal hosts do not present Textual's first alternate-screen
        # frame until an input event arrives. Repainting once after the event
        # loop is live makes startup independent of a key press.
        self.refresh(repaint=True, layout=True)

    @on(Button.Pressed, "#select-file")
    def select_file(self) -> None:
        if self._busy:
            return
        try:
            if self._file_picker is None:
                if self._suspend_file_picker:
                    with self.suspend():
                        selected = pick_file(title="Select a UV calendar", filetypes=(("ICS calendars", "*.ics"), ("All files", "*.*")))
                else:
                    selected = pick_file()
            else:
                selected = self._file_picker()
        except Exception as error:
            self._show_error(f"Could not open the file selector: {error}")
            return
        if selected is None:
            return
        path = Path(selected)
        self.query_one("#selected-path", Static).update(str(path.resolve()))
        self._prepare_for_load(path)
        self._load_selected_calendar(path)

    def _prepare_for_load(self, path: Path, *, remembered: bool = False) -> None:
        self.loaded_calendar = self.collision_analysis = self.comparison = self.generation_result = None
        self.report_result_path = self.change_report_result_path = None
        self.working_subject_names.clear(); self.initial_subject_names.clear(); self.modified_subject_ids.clear()
        self.configured_subject_ids = frozenset()
        self._subject_names_ready = self._baseline_accepted_current = False
        self._showing_remembered_baseline = remembered
        self.query_one("#subject-table", DataTable).clear()
        change_table = self.query_one("#change-table", DataTable)
        change_table.clear(); change_table.display = False
        self.query_one("#change-summary", Static).update("Loading remembered calendar…" if remembered else "Reading baseline and comparing sessions…")
        self.query_one("#collision-summary", Static).update("Reading events and calculating collisions…")
        self._set_busy(True, "Loading remembered calendar…" if remembered else f"Reading and analysing {path.name}…")

    @work(thread=True, exclusive=True, group="calendar-load")
    def _load_selected_calendar(self, path: Path, *, persist_last_check: bool = True, remembered: bool = False) -> None:
        try:
            loaded = self._calendar_loader(path)
            collisions = self._collision_analyzer(loaded.events)
        except Exception as error:
            self.call_from_thread(self._load_failed, error); return
        warning, tracking_available = self._tracking_warning, self._tracking_available
        try:
            original_events = loaded.events
            comparison, analysis_warning = analyze_with_baseline(self.state_store, loaded, collisions, calendar_loader=self._calendar_loader, persist_last_check=tracking_available and persist_last_check)
            if loaded.events is not original_events:
                collisions = self._collision_analyzer(loaded.events)
            if analysis_warning:
                warning = analysis_warning
                tracking_available = False
        except Exception as error:
            tracking_available = False
            warning = f"Tracking state could not be used: {error}. Formatting and collision review remain available."
            try:
                comparison = compare_calendars(None, loaded, current_collisions=collisions)
            except Exception as comparison_error:
                self.call_from_thread(self._load_failed, comparison_error); return
        self.call_from_thread(self._load_finished, loaded, collisions, comparison, warning, tracking_available, remembered)

    def _load_finished(self, loaded, collisions, comparison, warning, tracking_available, remembered=False) -> None:
        try:
            # Read access to aliases remains useful even when the portable
            # directory is not writable; only persistence actions are disabled.
            names, configured = prepare_subject_names(loaded, self.config_path)
        except Exception as error:
            tracking_available = False
            warning = f"Stored aliases could not be used: {error}. Formatting continues with UV names."
            names, configured = dict(loaded.subject_catalog), frozenset()
        self.loaded_calendar, self.collision_analysis, self.comparison = loaded, collisions, comparison
        self.working_subject_names, self.initial_subject_names = names, dict(names)
        self.configured_subject_ids, self.modified_subject_ids = configured, set()
        self._subject_names_ready, self._tracking_available = True, tracking_available
        self._showing_remembered_baseline = remembered
        self._baseline_accepted_current = remembered
        self._tracking_warning = warning
        tracking_warning = self.query_one("#tracking-warning", Static)
        tracking_warning.update(warning)
        tracking_warning.display = bool(warning)
        counts = Counter(event.subject_id for event in loaded.events if event.subject_id)
        table = self.query_one("#subject-table", DataTable)
        for subject_id, name in loaded.subject_catalog.items():
            table.add_row(Text(subject_id), Text(name), Text(names[subject_id]), str(counts[subject_id]), self._subject_name_status(subject_id), key=subject_id)
        self._populate_change_table(); self._refresh_change_summary(); self._refresh_collision_summary(); self._refresh_calendar_summary()
        self._set_busy(False, "")
        if remembered: self.query_one("#select-file", Button).focus()
        if comparison.possibly_unrelated:
            self.notify(f"Possibly unrelated calendar: {comparison.unrelated_reason}. For a new academic year, close the app, delete {self.state_store.data_dir}, restart, and load the calendar again.", title="Review required", severity="warning", timeout=10)

    def _load_failed(self, error: Exception) -> None:
        self.loaded_calendar = self.collision_analysis = self.comparison = None
        self._subject_names_ready = False
        self._set_busy(False, "Calendar loading failed.")
        self._show_error(f"Could not load or analyse the selected calendar: {error}")

    @on(DataTable.RowSelected, "#subject-table")
    def edit_subject_name(self, event: DataTable.RowSelected) -> None:
        if self._busy or self.loaded_calendar is None or not self._subject_names_ready:
            return
        subject_id = str(event.row_key.value)
        original, output = self.loaded_calendar.subject_catalog.get(subject_id), self.working_subject_names.get(subject_id)
        if original is not None and output is not None:
            self.push_screen(SubjectNameEditorScreen(subject_id, original, output), self._subject_name_edited)

    def _subject_name_edited(self, result: tuple[str, str] | None) -> None:
        if result is None: return
        subject_id, output = result
        self.working_subject_names[subject_id] = output
        (self.modified_subject_ids.discard if output == self.initial_subject_names.get(subject_id) else self.modified_subject_ids.add)(subject_id)
        table = self.query_one("#subject-table", DataTable)
        table.update_cell(subject_id, "output_name", Text(output)); table.update_cell(subject_id, "status", self._subject_name_status(subject_id))
        self.report_result_path = self.change_report_result_path = None

    @on(Button.Pressed, "#review-collisions")
    def review_collisions(self) -> None:
        self._open_collision_screen()

    def action_review_collisions(self) -> None:
        self._open_collision_screen()

    def _open_collision_screen(self) -> None:
        if self._busy or self.collision_analysis is None:
            self.notify("Collision analysis is still loading.", severity="warning")
            return
        if isinstance(self.screen, CollisionReviewScreen):
            return
        self.call_after_refresh(self.push_screen, CollisionReviewScreen())

    @on(Button.Pressed, "#change-info")
    def show_change_info(self) -> None:
        if self.comparison is not None and not self._busy:
            self.push_screen(ComparisonInfoScreen(self.comparison))

    @on(Button.Pressed, "#view-changes")
    def view_changes(self) -> None:
        if self.comparison and self.comparison.status != "first": self.push_screen(TextReportScreen("Calendar change report", render_change_report(self.comparison, self.working_subject_names), "change-report-content"))

    @on(Button.Pressed, "#save-change-report")
    def save_change_report(self) -> None:
        if self.comparison is None or self.comparison.status == "first" or self._busy: return
        self._set_busy(True, "Saving change report…"); self._write_change_report(self.comparison, dict(self.working_subject_names), self.change_report_path)

    @work(thread=True, exclusive=True, group="change-report")
    def _write_change_report(self, comparison, names, path) -> None:
        try: result = write_change_report(comparison, names, path)
        except Exception as error: self.call_from_thread(self._change_report_failed, error); return
        self.call_from_thread(self._change_report_finished, result)

    def _change_report_finished(self, path: Path) -> None:
        self.change_report_result_path = path; self._set_busy(False, f"Change report saved at {path}."); self.notify("Change report saved successfully.")

    def _change_report_failed(self, error: Exception) -> None:
        self._set_busy(False, "Change report generation failed."); self._show_error(f"Could not save the change report: {error}")

    @on(Button.Pressed, "#remember-baseline")
    def request_remember(self) -> None:
        if self.comparison and self.comparison.can_remember and self._tracking_available and not self._baseline_accepted_current: self.push_screen(ConfirmRememberScreen(), self._remember_confirmed)

    def _remember_confirmed(self, confirmed: bool | None) -> None:
        if not confirmed or self.loaded_calendar is None or self.comparison is None: return
        self._set_busy(True, "Remembering the selected calendar…"); self._accept_baseline(self.loaded_calendar, self.comparison, dict(self.working_subject_names))

    @work(thread=True, exclusive=True, group="baseline")
    def _accept_baseline(self, loaded, comparison, names) -> None:
        try: metadata = self.state_store.accept_baseline(loaded, comparison, names)
        except Exception as error: self.call_from_thread(self._baseline_failed, error); return
        self.call_from_thread(self._baseline_finished, metadata)

    def _baseline_finished(self, metadata: dict) -> None:
        self._baseline_accepted_current = True; self.initial_subject_names = dict(self.working_subject_names); self.configured_subject_ids = frozenset(self.working_subject_names); self.modified_subject_ids.clear()
        self._refresh_subject_statuses(); self._refresh_change_summary(); self._set_busy(False, f"Baseline accepted at {metadata['accepted_at_utc']}."); self.notify("Calendar remembered as the comparison baseline.")

    def _baseline_failed(self, error: Exception) -> None:
        self._set_busy(False, "Baseline was not changed."); self._show_error(f"Could not remember the baseline: {error}")

    @on(Button.Pressed, "#choose-output")
    def choose_output(self) -> None:
        if self._busy: return
        try:
            if self._output_picker is None:
                if self._suspend_file_picker:
                    with self.suspend(): selected = pick_save_file(title="Save formatted calendar", initialdir=self.output_path.parent, initialfile=self.output_path.name, defaultextension=".ics", filetypes=(("ICS calendars", "*.ics"),))
                else: selected = pick_save_file(initialdir=self.output_path.parent, initialfile=self.output_path.name, defaultextension=".ics")
            else: selected = self._output_picker(self.output_path)
        except Exception as error: self._show_error(f"Could not open the output selector: {error}"); return
        if selected is None: return
        output = _ensure_ics_suffix(Path(selected))
        if self.loaded_calendar and _same_path(output, self.loaded_calendar.source_path): self._show_error("The output path must be different from the input file."); return
        self.output_path = output; self.report_path = default_collision_report_path(output); self.change_report_path = default_change_report_path(output); self.report_result_path = self.change_report_result_path = None
        self.query_one("#output-path", Static).update(str(output.resolve()))

    @on(Button.Pressed, "#generate-calendar")
    def request_generation(self) -> None:
        if self._busy or self.loaded_calendar is None or not self._subject_names_ready: return
        if _same_path(self.output_path, self.loaded_calendar.source_path): self._show_error("The output path must be different from the input file."); return
        self.push_screen(ConfirmGenerationScreen(self.output_path, self._tracking_available), self._generation_confirmed)

    def _generation_confirmed(self, confirmed: bool | None) -> None:
        if not confirmed or self.loaded_calendar is None: return
        self._set_busy(True, "Generating formatted calendar…"); self._generate_calendar(self.loaded_calendar, dict(self.working_subject_names))

    @work(thread=True, exclusive=True, group="calendar-generation")
    def _generate_calendar(self, loaded, names) -> None:
        try:
            result = generate_formatted_calendar(loaded, config_path=self.config_path, output_path=self.output_path, subject_names=names, persist_subject_names=self._tracking_available) if self._calendar_generator is None else self._calendar_generator(loaded)
        except Exception as error: self.call_from_thread(self._generation_failed, error); return
        self.call_from_thread(self._generation_finished, result)

    def _generation_finished(self, result: GenerationResult) -> None:
        self.generation_result = result
        if result.config_saved:
            self.initial_subject_names = dict(self.working_subject_names); self.configured_subject_ids = frozenset(self.working_subject_names); self.modified_subject_ids.clear(); self._refresh_subject_statuses()
        note = "Configured subject names applied." if result.config_saved else "Names applied to output; tracking storage was not written."
        self._set_busy(False, f"Generated {result.event_count} events at {result.output_path}.\n{note}"); self.notify("Formatted calendar generated successfully.")

    def _generation_failed(self, error: Exception) -> None:
        self._set_busy(False, "Calendar generation failed."); self._show_error(f"Could not generate the formatted calendar: {error}")

    def save_collision_report(self) -> None:
        if self._busy or self.loaded_calendar is None or self.collision_analysis is None: return
        self._set_busy(True, "Saving collision report…"); self._write_collision_report(self.collision_analysis, self.loaded_calendar, dict(self.working_subject_names), self.report_path)

    @work(thread=True, exclusive=True, group="collision-report")
    def _write_collision_report(self, analysis, loaded, names, path) -> None:
        try: result = self._collision_report_writer(analysis, loaded, names, path)
        except Exception as error: self.call_from_thread(self._report_failed, error); return
        self.call_from_thread(self._report_finished, result)

    def _report_finished(self, path: Path) -> None:
        self.report_result_path = path; self._set_busy(False, f"Collision report saved at {path}."); self.notify("Collision report saved successfully.")

    def _report_failed(self, error: Exception) -> None:
        self._set_busy(False, "Collision report generation failed."); self._show_error(f"Could not save the collision report: {error}")

    def _set_busy(self, busy: bool, status: str) -> None:
        self._busy = busy; self.query_one("#loader", LoadingIndicator).display = busy
        status_widget = self.query_one("#status", Static)
        status_widget.update(status); status_widget.display = bool(status)
        self.query_one("#select-file", Button).disabled = busy; self.query_one("#choose-output", Button).disabled = busy
        self.query_one("#generate-calendar", Button).disabled = busy or self.loaded_calendar is None or not self._subject_names_ready
        self.query_one("#review-collisions", Button).disabled = busy or self.collision_analysis is None
        self.query_one("#change-info", Button).disabled = busy or self.comparison is None or self._showing_remembered_baseline
        has_baseline_comparison = self.comparison is not None and self.comparison.status != "first" and not self._showing_remembered_baseline
        view_changes = self.query_one("#view-changes", Button)
        save_change_report = self.query_one("#save-change-report", Button)
        view_changes.display = save_change_report.display = has_baseline_comparison
        view_changes.disabled = save_change_report.disabled = busy or not has_baseline_comparison
        self.query_one("#remember-baseline", Button).disabled = busy or not self._tracking_available or self.comparison is None or not self.comparison.can_remember or self._baseline_accepted_current

    def _refresh_calendar_summary(self) -> None:
        if self.loaded_calendar: self.query_one("#calendar-summary", Static).update(f"Events: {len(self.loaded_calendar.events)}    Unique subjects: {len(self.loaded_calendar.subject_catalog)}")

    def collision_summary_text(self) -> str:
        analysis = self.collision_analysis
        if analysis is None: return "No collision analysis is available."
        categories = Counter(collision_category(item) for item in analysis.collisions)
        category_text = ", ".join(f"{name}: {count}" for name, count in sorted(categories.items())) or "No collisions."
        return f"All collision pairs: {analysis.collision_count}    Laboratory-involved pairs: {analysis.laboratory_collision_count}    Affected laboratory sessions: {analysis.affected_laboratory_count}\n{category_text}"

    def _refresh_collision_summary(self) -> None:
        text = self.collision_summary_text()
        if self.comparison and self.comparison.status == "changed":
            summary = self.comparison.summary; text += f"\nSince baseline — new: {summary['new_collisions']}, resolved: {summary['resolved_collisions']}, changed: {summary['changed_collisions']}"
        self.query_one("#collision-summary", Static).update(text)

    def _refresh_change_summary(self) -> None:
        comparison = self.comparison
        if comparison is None: return
        if self._showing_remembered_baseline: text = "Showing the remembered baseline. Select an updated ICS calendar to review changes."
        elif comparison.status == "first": text = "First calendar analysis"
        elif comparison.status == "unchanged": text = "No calendar changes"
        else:
            summary = comparison.summary
            text = f"Calendar changed: {summary['added']} added, {summary['removed']} removed, {summary['modified']} modified"
            if summary["ambiguous"]:
                text += f", {summary['ambiguous']} need review"
        if comparison.possibly_unrelated: text += f"\nPossibly unrelated calendar: {comparison.unrelated_reason}. For a new academic year, close the app, delete the portable data folder, restart, and load it again."
        review_count = sum(diagnostic.severity == "review" for diagnostic in comparison.projection_diagnostics)
        if review_count: text += f"\nProjection review required: {review_count} diagnostic(s)."
        if self._baseline_accepted_current and not self._showing_remembered_baseline: text += "\nRemembered as the current baseline."
        self.query_one("#change-summary", Static).update(text)

    def _populate_change_table(self) -> None:
        table = self.query_one("#change-table", DataTable); table.clear()
        if self.comparison is None:
            table.display = False
            return
        review_diagnostics = tuple(
            diagnostic
            for diagnostic in self.comparison.projection_diagnostics
            if diagnostic.severity == "review"
        )
        table.display = bool(
            (self.comparison.status == "changed" and (self.comparison.event_changes or self.comparison.warnings))
            or review_diagnostics
        )
        for index, change in enumerate(self.comparison.event_changes):
            event = change.current or change.before; title = self.event_display_name(event)
            label = ", ".join(change.categories).title() if change.categories else change.change.title()
            table.add_row(event.start.date().isoformat(), label, title, _compact_event(change.before) if change.before else "—", _compact_event(change.current) if change.current else "—", key=f"change-{index}")
        for index, warning in enumerate(self.comparison.warnings):
            event = warning.current_candidates[0] if warning.current_candidates else warning.baseline_candidates[0]
            table.add_row(event.start.date().isoformat(), "Needs review", self.event_display_name(event), f"{len(warning.baseline_candidates)} candidates", f"{len(warning.current_candidates)} candidates", key=f"warning-{index}")
        events_by_uid = {
            event.uid: event
            for event in (self.loaded_calendar.events if self.loaded_calendar else ())
            if event.uid
        }
        for index, diagnostic in enumerate(review_diagnostics):
            event = events_by_uid.get(diagnostic.event_uid or "")
            table.add_row(
                event.start.date().isoformat() if event else "—",
                "Needs review",
                self.event_display_name(event) if event else diagnostic.code,
                diagnostic.message,
                "—",
                key=f"projection-warning-{index}",
            )

    def event_display_name(self, event: CalendarEventData) -> str:
        subject = self.working_subject_names.get(event.subject_id, event.original_subject)
        return f"{subject} — {event.group}" if event.group else subject

    def _subject_name_status(self, subject_id: str) -> str:
        return "Modified" if subject_id in self.modified_subject_ids else "Configured" if subject_id in self.configured_subject_ids else "UV default"

    def _refresh_subject_statuses(self) -> None:
        if self.loaded_calendar:
            table = self.query_one("#subject-table", DataTable)
            for subject_id in self.loaded_calendar.subject_catalog: table.update_cell(subject_id, "status", self._subject_name_status(subject_id))

    def _refresh_subject_table_names(self) -> None:
        if self.loaded_calendar:
            table = self.query_one("#subject-table", DataTable)
            for subject_id, name in self.working_subject_names.items(): table.update_cell(subject_id, "output_name", Text(name))
            self._refresh_subject_statuses()

    def _show_error(self, message: str) -> None:
        self.notify(message, title="Error", severity="error", timeout=8)

    @on(Button.Pressed, "#exit-app")
    def exit_from_button(self) -> None: self.exit()

    def action_quit_app(self) -> None: self.exit()


def _ensure_ics_suffix(path: Path) -> Path:
    return path if path.suffix.casefold() == ".ics" else path.with_suffix(".ics")


def _same_path(left: Path, right: Path) -> bool:
    return left.resolve() == right.resolve()


def _compact_event(event: CalendarEventData) -> str:
    return f"{event.start:%H:%M}–{event.end:%H:%M}; {event.location or '—'}; {event.class_type or '—'}; {event.group or '—'}"


def _comparison_info_text(comparison: CalendarComparison) -> str:
    status_labels = {
        "first": "First analysis (no accepted baseline)",
        "unchanged": "No changes",
        "changed": "Changes detected",
    }
    lines = [
        f"Result: {status_labels.get(comparison.status, comparison.status)}",
        "",
        "Current analysis",
        f"  Source: {comparison.source_name}",
        f"  Analysed (UTC): {comparison.analyzed_at_utc}",
        f"  Source SHA-256: {comparison.source_sha256}",
        f"  Canonical SHA-256: {comparison.canonical_sha256}",
        f"  Detected format: {comparison.current_source_format.adapter_id} "
        f"({comparison.current_source_format.confidence:.0%} confidence)",
    ]
    baseline = comparison.baseline_metadata or {}
    if baseline:
        baseline_format = (
            comparison.baseline_source_format.adapter_id
            if comparison.baseline_source_format
            else baseline.get("source_format", "unknown")
        )
        date_range = baseline.get("date_range") or {}
        range_text = "—"
        if date_range:
            range_text = f"{date_range.get('start', '—')} to {date_range.get('end', '—')}"
        lines.extend(
            [
                "",
                "Accepted baseline",
                f"  Detected format: {baseline_format}",
                f"  Source: {baseline.get('source_name', '—')}",
                f"  Analysed (UTC): {baseline.get('analyzed_at_utc', '—')}",
                f"  Accepted (UTC): {baseline.get('accepted_at_utc', '—')}",
                f"  Source SHA-256: {comparison.baseline_source_sha256 or baseline.get('source_sha256', '—')}",
                f"  Canonical SHA-256: {comparison.baseline_canonical_sha256 or baseline.get('canonical_sha256', '—')}",
                f"  Events: {baseline.get('event_count', '—')}",
                f"  Date range: {range_text}",
                f"  Application version: {baseline.get('application_version', '—')}",
                f"  Parser data version: {baseline.get('parser_data_version', '—')}",
            ]
        )
    else:
        lines.extend(["", "Accepted baseline", "  None"])
    if comparison.projection_diagnostics:
        lines.extend(("", "Projection diagnostics"))
        lines.extend(
            f"  [{diagnostic.severity.upper()}] {diagnostic.message}"
            for diagnostic in comparison.projection_diagnostics
        )
    return "\n".join(lines)


def _event_detail(heading: str, event: CalendarEventData, subject_names: Mapping[str, str]) -> str:
    subject = subject_names.get(event.subject_id, event.original_subject)
    location = event_location_identity(event)
    provenance = (
        f" ({location.provenance}, {location.state})"
        if location.state != "known"
        else ""
    )
    return "\n".join((f"{heading}: {subject}", f"Subject ID: {event.subject_id or '—'}", f"Activity: {event.class_type or '—'}", f"Group: {event.group or '—'}", f"Session: {event.start:%Y-%m-%d %H:%M}–{event.end:%H:%M}", f"Location: {event.location or '—'}{provenance}", f"UID: {event.uid or '—'}"))
