"""Application service for loading, verifying, and comparing a saved baseline."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from core.calendar_workflow import load_calendar
from core.change_tracking import PARSER_DATA_VERSION, canonical_sha256, compare_calendars
from core.collision_detector import analyze_collisions
from core.models import CalendarComparison, CollisionAnalysis, LoadedCalendar
from core.state_store import CalendarStateStore, StateValidationError


CalendarLoader = Callable[[Path], LoadedCalendar]


def analyze_with_baseline(
    store: CalendarStateStore,
    current: LoadedCalendar,
    current_collisions: CollisionAnalysis,
    *,
    calendar_loader: CalendarLoader = load_calendar,
    persist_last_check: bool = True,
) -> tuple[CalendarComparison, str]:
    """Return comparison plus a non-fatal persistence warning."""

    manifest = store.load()
    baseline_metadata = manifest["tracking"].get("baseline")
    baseline = None
    baseline_analysis = None
    if baseline_metadata:
        raw_path = store.verified_baseline_path(manifest)
        if raw_path is None:
            raise StateValidationError("Baseline metadata has no raw calendar")
        baseline = calendar_loader(raw_path)
        baseline_analysis = analyze_collisions(baseline.events)
        derived_hash = canonical_sha256(baseline.events)
        stored_version = baseline_metadata["parser_data_version"]
        stored_hash = baseline_metadata["canonical_sha256"]
        if stored_version == PARSER_DATA_VERSION and derived_hash != stored_hash:
            raise StateValidationError(
                "Stored baseline canonical hash does not match its raw calendar"
            )
        if stored_version != PARSER_DATA_VERSION:
            # Both projections have already been parsed by the current code. Updating
            # derived metadata is a projection migration, not a timetable change.
            baseline_metadata = dict(baseline_metadata)
            baseline_metadata["parser_data_version"] = PARSER_DATA_VERSION
            baseline_metadata["canonical_sha256"] = derived_hash

    comparison = compare_calendars(
        baseline,
        current,
        baseline_collisions=baseline_analysis,
        current_collisions=current_collisions,
        baseline_metadata=baseline_metadata,
    )
    warning = ""
    if persist_last_check:
        writable, writable_warning = store.is_writable()
        if writable:
            try:
                if (
                    baseline is not None
                    and manifest["tracking"]["baseline"]["parser_data_version"]
                    != PARSER_DATA_VERSION
                ):
                    from core.change_tracking import date_range

                    store.migrate_projection_metadata(
                        canonical_sha256(baseline.events),
                        len(baseline.events),
                        date_range(baseline.events),
                    )
                store.record_last_check(comparison)
            except OSError as error:
                warning = f"Calendar analysis succeeded, but tracking state could not be updated: {error}"
        else:
            warning = writable_warning
    return comparison, warning
