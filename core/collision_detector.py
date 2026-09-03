from collections.abc import Iterable

from core.activity_policy import ActivityPriority, activity_priority
from core.models import CalendarEventData, CollisionAnalysis, CollisionPair


def analyze_collisions(
    events: Iterable[CalendarEventData],
) -> CollisionAnalysis:
    """Detect all overlaps and derive the laboratory-focused result set."""

    source_events = tuple(events)
    _validate_events(source_events)
    ordered_events = tuple(sorted(source_events, key=_event_sort_key))

    active: list[CalendarEventData] = []
    collisions: list[CollisionPair] = []
    for event in ordered_events:
        active = [candidate for candidate in active if candidate.end > event.start]
        for candidate in active:
            overlap_start = max(candidate.start, event.start)
            overlap_end = min(candidate.end, event.end)
            if overlap_start < overlap_end:
                collisions.append(
                    CollisionPair(
                        first=candidate,
                        second=event,
                        overlap_start=overlap_start,
                        overlap_end=overlap_end,
                    )
                )
        active.append(event)

    ordered_collisions = tuple(sorted(collisions, key=_collision_sort_key))
    laboratory_collisions = tuple(
        collision
        for collision in ordered_collisions
        if collision_involves_laboratory(collision)
    )
    affected_laboratories = frozenset(
        session_identity(event)
        for collision in laboratory_collisions
        for event in (collision.first, collision.second)
        if activity_priority(event.class_type) == ActivityPriority.LABORATORY
    )

    return CollisionAnalysis(
        event_count=len(ordered_events),
        collisions=ordered_collisions,
        laboratory_collisions=laboratory_collisions,
        affected_laboratory_sessions=affected_laboratories,
    )


def collision_involves_laboratory(collision: CollisionPair) -> bool:
    return any(
        activity_priority(event.class_type) == ActivityPriority.LABORATORY
        for event in (collision.first, collision.second)
    )


def collision_category(collision: CollisionPair) -> str:
    priorities = sorted(
        (
            activity_priority(collision.first.class_type),
            activity_priority(collision.second.class_type),
        ),
        reverse=True,
    )
    return " / ".join(_priority_label(priority) for priority in priorities)


def orient_collision(
    collision: CollisionPair,
) -> tuple[CalendarEventData, CalendarEventData]:
    """Put the higher-priority event first, with deterministic tie-breaking."""

    return tuple(
        sorted(
            (collision.first, collision.second),
            key=lambda event: (
                -int(activity_priority(event.class_type)),
                _event_sort_key(event),
            ),
        )
    )


def orient_laboratory_collision(
    collision: CollisionPair,
) -> tuple[CalendarEventData, CalendarEventData]:
    """Return a deterministic laboratory/other orientation for presentation."""

    if not collision_involves_laboratory(collision):
        raise ValueError("Collision does not contain a laboratory session")
    return orient_collision(collision)


def session_identity(event: CalendarEventData) -> str:
    """Build a stable identity even when a source event has no UID."""

    return "|".join(
        (
            event.uid,
            event.subject_id,
            event.class_type,
            event.group,
            event.start.isoformat(),
            event.end.isoformat(),
        )
    )


def _validate_events(events: tuple[CalendarEventData, ...]) -> None:
    for event in events:
        if not _is_timezone_aware(event.start) or not _is_timezone_aware(event.end):
            raise ValueError(
                f"Event {event.uid or event.subject_id!r} has a timezone-naive time"
            )
        if event.end <= event.start:
            raise ValueError(
                f"Event {event.uid or event.subject_id!r} must end after it starts"
            )


def _is_timezone_aware(value) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _event_sort_key(event: CalendarEventData) -> tuple:
    return (
        event.start,
        event.end,
        -int(activity_priority(event.class_type)),
        event.subject_id,
        event.group,
        event.uid,
    )


def _collision_sort_key(collision: CollisionPair) -> tuple:
    return (
        collision.overlap_start,
        collision.overlap_end,
        -max(
            int(activity_priority(collision.first.class_type)),
            int(activity_priority(collision.second.class_type)),
        ),
        _event_sort_key(collision.first),
        _event_sort_key(collision.second),
    )


def _priority_label(priority: ActivityPriority) -> str:
    return {
        ActivityPriority.LABORATORY: "Laboratory",
        ActivityPriority.SEMINAR: "Seminar",
        ActivityPriority.TUTORIAL: "Tutorial",
        ActivityPriority.CLASS: "Class",
    }[priority]
