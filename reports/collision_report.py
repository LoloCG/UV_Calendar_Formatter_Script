from collections import Counter
from collections.abc import Mapping
from pathlib import Path

from core.collision_detector import collision_category, orient_collision
from core.models import (
    CalendarEventData,
    CollisionAnalysis,
    CollisionPair,
    LoadedCalendar,
)


def default_collision_report_path(calendar_output_path: str | Path) -> Path:
    output_path = Path(calendar_output_path)
    return output_path.with_name(f"{output_path.stem}_collisions.txt")


def write_collision_report(
    analysis: CollisionAnalysis,
    loaded_calendar: LoadedCalendar,
    subject_names: Mapping[str, str],
    output_path: str | Path,
) -> Path:
    """Render and save the collision report as a plain-text file."""

    target = _with_text_suffix(Path(output_path))
    target.write_text(
        render_collision_report(analysis, loaded_calendar, subject_names),
        encoding="utf-8",
    )
    return target.resolve()


def render_collision_report(
    analysis: CollisionAnalysis,
    loaded_calendar: LoadedCalendar,
    subject_names: Mapping[str, str],
) -> str:
    """Render a compact, deterministic plain-text report for every collision."""

    lines = [
        "CALENDAR COLLISION REPORT",
        "=========================",
        f"Source calendar: {loaded_calendar.source_path.name}",
        f"Events analysed: {analysis.event_count}",
        f"Collision pairs: {analysis.collision_count}",
        f"Laboratory-involved pairs: {analysis.laboratory_collision_count}",
        f"Affected laboratory sessions: {analysis.affected_laboratory_count}",
        "Priority: Laboratory > Seminar > Tutorial > Class",
        "",
        "CATEGORIES",
        "----------",
    ]

    category_counts = Counter(
        collision_category(collision) for collision in analysis.collisions
    )
    if category_counts:
        lines.extend(
            f"{category}: {count}"
            for category, count in sorted(category_counts.items())
        )
    else:
        lines.append("No collisions found.")

    lines.extend(("", "COLLISION GROUPS", "----------------"))
    if not analysis.collisions:
        lines.append("No collisions found.")
        return "\n".join(lines) + "\n"

    for index, collisions in enumerate(_group_collisions(analysis.collisions), 1):
        collision = collisions[0]
        first, second = orient_collision(collision)
        lines.extend(
            (
                "",
                f"{index}. {_format_dates(collisions)} | "
                f"{collision_category(collision)}",
                f"   Event: {_event_summary(first, subject_names)}",
                f"   Collides with: {_event_summary(second, subject_names)}",
            )
        )

    return "\n".join(lines).rstrip() + "\n"


def _group_collisions(
    collisions: tuple[CollisionPair, ...],
) -> tuple[tuple[CollisionPair, ...], ...]:
    """Group matching pairs only across consecutive dates, then order by date."""

    groups: dict[tuple, list[CollisionPair]] = {}
    for collision in collisions:
        first, second = orient_collision(collision)
        key = (
            collision_category(collision),
            _clock_key(collision.overlap_start),
            _clock_key(collision.overlap_end),
            _event_group_key(first),
            _event_group_key(second),
        )
        groups.setdefault(key, []).append(collision)
    consecutive_groups: list[tuple[CollisionPair, ...]] = []
    for group in groups.values():
        current_group = [group[0]]
        previous_date = group[0].overlap_start.date()
        for collision in group[1:]:
            current_date = collision.overlap_start.date()
            if (current_date - previous_date).days > 1:
                consecutive_groups.append(tuple(current_group))
                current_group = []
            current_group.append(collision)
            previous_date = current_date
        consecutive_groups.append(tuple(current_group))

    return tuple(
        sorted(
            consecutive_groups,
            key=lambda group: (
                group[0].overlap_start,
                group[0].overlap_end,
                collision_category(group[0]),
            ),
        )
    )


def _event_group_key(event: CalendarEventData) -> tuple:
    return (
        event.subject_id,
        event.original_subject,
        event.class_type,
        event.group,
        _clock_key(event.start),
        _clock_key(event.end),
    )


def _clock_key(value) -> tuple[int, int, int]:
    return value.hour, value.minute, value.second


def _format_dates(collisions: tuple[CollisionPair, ...]) -> str:
    dates = sorted({collision.overlap_start.date() for collision in collisions})
    ranges: list[str] = []
    range_start = dates[0]
    previous = dates[0]
    for current in dates[1:]:
        if (current - previous).days == 1:
            previous = current
            continue
        ranges.append(_format_date_range(range_start, previous))
        range_start = previous = current
    ranges.append(_format_date_range(range_start, previous))

    date_text = ", ".join(ranges)
    if len(collisions) == 1:
        return date_text
    return f"{date_text} ({len(collisions)} occurrences)"


def _format_date_range(start, end) -> str:
    if start == end:
        return start.isoformat()
    return f"{start.isoformat()} to {end.isoformat()}"


def _event_summary(
    event: CalendarEventData,
    subject_names: Mapping[str, str],
) -> str:
    subject = subject_names.get(event.subject_id, event.original_subject)
    subject_id = f" ({event.subject_id})" if event.subject_id else ""
    group = f" - {event.group}" if event.group else ""
    activity = event.class_type or "Unspecified activity"
    location = f" | {event.location}" if event.location else ""
    return (
        f"{subject}{subject_id}{group} | {activity} | "
        f"{_format_interval(event.start, event.end)}{location}"
    )


def _format_interval(start, end) -> str:
    return f"{start:%H:%M}-{end:%H:%M}"


def _with_text_suffix(path: Path) -> Path:
    return path if path.suffix.casefold() == ".txt" else path.with_suffix(".txt")
