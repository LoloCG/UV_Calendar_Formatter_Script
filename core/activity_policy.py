from enum import IntEnum

from core.semantic import activity_key


class ActivityPriority(IntEnum):
    """Relative importance used by timetable analysis and presentation."""

    CLASS = 1
    TUTORIAL = 2
    SEMINAR = 3
    LABORATORY = 4


def activity_priority(class_type: str | None) -> ActivityPriority:
    """Classify a UV activity using accent- and case-insensitive labels."""

    normalized = activity_key(class_type)
    if normalized == "laboratorio":
        return ActivityPriority.LABORATORY
    if normalized == "seminario":
        return ActivityPriority.SEMINAR
    if normalized == "tutoria":
        return ActivityPriority.TUTORIAL
    return ActivityPriority.CLASS


def blocks_calendar_time(class_type: str | None) -> bool:
    """Return whether the activity should be emitted as opaque/busy."""

    return activity_priority(class_type) > ActivityPriority.CLASS
