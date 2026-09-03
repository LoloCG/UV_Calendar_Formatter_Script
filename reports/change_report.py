"""Chronological human-readable calendar change reports."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from core.models import CalendarComparison, CalendarEventData


def default_change_report_path(output_path: str | Path) -> Path:
    path = Path(output_path)
    return path.with_name(f"{path.stem}_changes.txt")


def render_change_report(
    comparison: CalendarComparison,
    subject_names: Mapping[str, str] | None = None,
) -> str:
    names = subject_names or {}
    lines = [
        "CALENDAR CHANGE REPORT",
        "=" * 22,
        f"Status: {_status_label(comparison.status)}",
        f"Analysed (UTC): {comparison.analyzed_at_utc}",
        f"Current source: {comparison.source_name}",
        f"Current SHA-256: {comparison.source_sha256}",
    ]
    baseline = comparison.baseline_metadata or {}
    if baseline:
        lines.extend(
            (
                f"Baseline analysed (UTC): {baseline.get('analyzed_at_utc', '—')}",
                f"Baseline accepted (UTC): {baseline.get('accepted_at_utc', '—')}",
                f"Baseline SHA-256: {comparison.baseline_source_sha256 or '—'}",
            )
        )
    if comparison.possibly_unrelated:
        lines.extend(("", f"WARNING: Possibly unrelated calendar ({comparison.unrelated_reason})."))
    summary = comparison.summary
    lines.extend(
        (
            "",
            "SUMMARY",
            "-------",
            f"Added: {summary['added']}",
            f"Removed: {summary['removed']}",
            f"Modified: {summary['modified']}",
            f"Needs review: {summary['ambiguous']}",
            f"New collisions: {summary['new_collisions']}",
            f"Resolved collisions: {summary['resolved_collisions']}",
            f"Changed collisions: {summary['changed_collisions']}",
        )
    )
    if comparison.status == "first":
        lines.extend(("", "This is the first analysis; sessions are not listed as added."))
    elif comparison.status == "unchanged":
        lines.extend(("", "No calendar changes."))
    else:
        lines.extend(("", "EVENT CHANGES", "-------------"))
        for change in comparison.event_changes:
            event = change.current or change.before
            label = _event_label(event, names)
            if change.change == "modified":
                lines.append(
                    f"{event.start:%Y-%m-%d %H:%M} | {', '.join(change.categories).title()} | {label}"
                )
                for field, (before, current) in change.fields.items():
                    lines.append(f"  {field}: {before or '—'} -> {current or '—'}")
            else:
                lines.append(
                    f"{event.start:%Y-%m-%d %H:%M} | {change.change.title()} | {label}"
                )
        for warning in comparison.warnings:
            lines.append(f"Needs review | {warning.reason}")
            lines.append(
                "  Baseline: "
                + "; ".join(_event_label(event, names) for event in warning.baseline_candidates)
            )
            lines.append(
                "  Current: "
                + "; ".join(_event_label(event, names) for event in warning.current_candidates)
            )
        lines.extend(("", "COLLISION CHANGES", "-----------------"))
        if not comparison.collision_changes:
            lines.append("No collision changes.")
        for change in sorted(
            comparison.collision_changes,
            key=lambda item: (item.current or item.before).overlap_start,
        ):
            collision = change.current or change.before
            lines.append(
                f"{collision.overlap_start:%Y-%m-%d %H:%M} | "
                f"{change.change.title()} collision | "
                f"{_event_label(collision.first, names)} <> "
                f"{_event_label(collision.second, names)}"
            )
            if change.related_event_changes:
                references = ", ".join(
                    f"#{index + 1}" for index in change.related_event_changes
                )
                lines.append(f"  related event changes: {references}")
            if change.before and change.current:
                lines.append(
                    f"  overlap: {change.before.overlap_start:%H:%M}–"
                    f"{change.before.overlap_end:%H:%M} -> "
                    f"{change.current.overlap_start:%H:%M}–"
                    f"{change.current.overlap_end:%H:%M}"
                )
    return "\n".join(lines) + "\n"


def write_change_report(
    comparison: CalendarComparison,
    subject_names: Mapping[str, str],
    output_path: str | Path,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_change_report(comparison, subject_names), encoding="utf-8")
    return path.resolve()


def _event_label(event: CalendarEventData, names: Mapping[str, str]) -> str:
    subject = names.get(event.subject_id, event.original_subject)
    pieces = [subject or event.subject_id or "Untitled session"]
    if event.class_type:
        pieces.append(event.class_type)
    if event.group:
        pieces.append(event.group)
    return " / ".join(pieces)


def _status_label(status: str) -> str:
    return {"first": "First analysis", "unchanged": "No calendar changes", "changed": "Changed"}.get(status, status)
