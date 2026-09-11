"""Compatibility wrapper around the source-adapter projection pipeline."""

from __future__ import annotations

from dataclasses import replace

from core.models import CalendarSourceMetadata, RawCalendarEvent
from core.source_formats import project_calendar


class UVEventFormatter:
    """Project one legacy event dictionary through the adapter registry.

    New code should project a complete calendar with
    :func:`core.source_formats.project_calendar`; this wrapper remains for
    callers that previously constructed ``UVEventFormatter`` directly.
    """

    def __init__(self, event_dict: dict):
        self.event = event_dict
        raw = RawCalendarEvent(
            uid=_optional_text(event_dict.get("UID")),
            summary=_optional_text(event_dict.get("SUMMARY")),
            description=_optional_text(event_dict.get("DESCRIPTION")),
            classification=_optional_text(event_dict.get("CLASSIFICATION")),
            categories=_optional_text(event_dict.get("CATEGORIES")),
            created=event_dict.get("CREATED"),
            last_modified=event_dict.get("LAST_MODIFIED"),
            start=event_dict.get("DTSTART"),
            end=event_dict.get("DTEND"),
            location=_optional_text(event_dict.get("LOCATION")),
        )
        self._parsed = project_calendar(CalendarSourceMetadata(), (raw,)).events[0]
        self._sync_values()

    def _sync_values(self) -> None:
        self.subject_id = self._parsed.subject_id
        self.subject = self._parsed.original_subject
        self.group = self._parsed.group
        self.class_type = self._parsed.class_type

    def rename_subjects(self, config: dict | None = None, name: str | None = None):
        replacement = config.get(self.subject_id) if config is not None else None
        if replacement is None:
            replacement = name
        if replacement is not None:
            self._parsed = replace(self._parsed, original_subject=replacement)
            self._sync_values()
        return self

    def get_values(self):
        return {
            "subject": self.subject,
            "subject_id": self.subject_id,
            "class_type": self.class_type,
            "class_group": self.group,
        }

    def to_event_data(self):
        return self._parsed


def _optional_text(value) -> str | None:
    return None if value is None else str(value)
