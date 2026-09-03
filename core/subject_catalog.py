from collections.abc import Iterable

from core.models import CalendarEventData


def build_subject_catalog(events: Iterable[CalendarEventData]) -> dict[str, str]:
    """Return one deterministic UV subject name for every non-empty ID."""

    ordered_events = sorted(
        events,
        key=lambda event: (
            _subject_sort_key(event.subject_id),
            event.original_subject.casefold(),
        ),
    )

    catalog: dict[str, str] = {}
    for event in ordered_events:
        if event.subject_id:
            catalog.setdefault(event.subject_id, event.original_subject)
    return catalog


def _subject_sort_key(subject_id: str) -> tuple[int, int | str]:
    if subject_id.isdigit():
        return (0, int(subject_id))
    return (1, subject_id.casefold())
