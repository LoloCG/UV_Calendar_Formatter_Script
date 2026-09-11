"""Canonical activity/location identities shared by all calendar features."""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from core.models import (
    ActivityIdentity,
    CalendarEventData,
    LoadedCalendar,
    LocationIdentity,
    ProjectionDiagnostic,
)
from core.text_utils import normalize_label


_ACTIVITY_ALIASES = {
    "teoria": "teoria",
    "teorias": "teoria",
    "laboratorio": "laboratorio",
    "laboratorios": "laboratorio",
    "seminario": "seminario",
    "seminarios": "seminario",
    "tutoria": "tutoria",
    "tutorias": "tutoria",
    "informatica": "informatica",
    "aula informatica": "informatica",
}


def activity_key(value: str | None) -> str:
    """Return the stable activity key, preserving unknown normalized labels."""

    normalized = normalize_label(value)
    return _ACTIVITY_ALIASES.get(normalized, normalized)


def activity_identity(value: str | None) -> ActivityIdentity:
    display = (value or "").strip()
    return ActivityIdentity(
        key=activity_key(display),
        display_value=display,
        raw_value=value,
        confidence="known" if display else "unknown",
    )


def event_activity_key(event: CalendarEventData) -> str:
    identity = event.activity_identity
    return identity.key if identity is not None else activity_key(event.class_type)


def room_key(value: str | None) -> str:
    return normalize_label(value)


def generic_location_identity(value: str | None) -> LocationIdentity:
    """Give hand-built/legacy domain events a conservative semantic identity."""

    display = (value or "").strip()
    if not display:
        return LocationIdentity(state="absent", confidence="known")
    return LocationIdentity(
        room_key=room_key(display),
        display_value=display,
        raw_value=value,
        provenance="source",
        confidence="known",
        state="known",
    )


def event_location_identity(event: CalendarEventData) -> LocationIdentity:
    return event.location_identity or generic_location_identity(event.location)


def location_signature(event: CalendarEventData) -> str:
    """Return a hash token that does not collapse unavailable data into absence."""

    identity = event_location_identity(event)
    if identity.state in {"known", "inferred"}:
        return f"known:{identity.building_code}|{identity.room_key}"
    if identity.state == "unknown":
        return f"unknown:{room_key(identity.raw_value)}"
    return identity.state


def location_relation(
    first: CalendarEventData, second: CalendarEventData
) -> str:
    """Return equal, relocated, or review for two semantic locations."""

    left = event_location_identity(first)
    right = event_location_identity(second)
    if left.state == "absent" and right.state == "absent":
        return "equal"
    if left.canonical_key is not None and right.canonical_key is not None:
        if left.canonical_key == right.canonical_key:
            return "equal"
        if left.state == right.state == "known":
            return "relocated"
        return "review"
    if {left.state, right.state} <= {"known", "absent"}:
        return "relocated"
    return "review"


def resolve_same_calendar_location_fallbacks(
    loaded: LoadedCalendar,
) -> LoadedCalendar:
    """Infer unavailable locations only when the current calendar is unanimous."""

    return _resolve_location_fallbacks(loaded, loaded.events, "same-calendar")


def resolve_baseline_location_fallbacks(
    current: LoadedCalendar, baseline: LoadedCalendar
) -> LoadedCalendar:
    """Use source-known values from the accepted baseline as secondary evidence."""

    return _resolve_location_fallbacks(current, baseline.events, "accepted-baseline")


def _resolve_location_fallbacks(
    loaded: LoadedCalendar,
    candidate_events: Iterable[CalendarEventData],
    provenance: str,
) -> LoadedCalendar:
    candidates = tuple(
        event
        for event in candidate_events
        if event_location_identity(event).state == "known"
    )
    projected: list[CalendarEventData] = []
    new_diagnostics: list[ProjectionDiagnostic] = []
    resolved_diagnostic_ids: set[int] = set()
    for event in loaded.events:
        identity = event_location_identity(event)
        if identity.state != "unavailable":
            projected.append(event)
            continue
        matching = [
            candidate
            for candidate in candidates
            if candidate.subject_id == event.subject_id
            and event_activity_key(candidate) == event_activity_key(event)
        ]
        selected, conflicted = _unique_location(matching, event.group)
        if selected is None:
            projected.append(event)
            if conflicted:
                diagnostic = ProjectionDiagnostic(
                    code="location-fallback-conflict",
                    message=(
                        f"Location fallback for subject {event.subject_id or 'unknown'} "
                        f"and activity {event.class_type or 'unknown'} has conflicting rooms."
                    ),
                    severity="review",
                    event_uid=event.uid or None,
                )
                new_diagnostics.append(diagnostic)
                projected[-1] = replace(
                    event,
                    location_identity=replace(identity, state="conflicting"),
                    projection_diagnostics=event.projection_diagnostics + (diagnostic,),
                )
            continue
        source_identity = event_location_identity(selected)
        inferred_identity = LocationIdentity(
            building_code=source_identity.building_code,
            room_key=source_identity.room_key,
            display_value=source_identity.display_value,
            raw_value=identity.raw_value,
            source_property=None,
            provenance=provenance,
            confidence="inferred",
            state="inferred",
        )
        diagnostic = ProjectionDiagnostic(
            code="location-inferred",
            message=(
                f"Location for subject {event.subject_id or 'unknown'} and activity "
                f"{event.class_type or 'unknown'} was inferred from {provenance}."
            ),
            severity="info",
            event_uid=event.uid or None,
        )
        new_diagnostics.append(diagnostic)
        retained_event_diagnostics = tuple(
            item
            for item in event.projection_diagnostics
            if item.code != "location-unavailable"
        )
        resolved_diagnostic_ids.update(
            id(item)
            for item in event.projection_diagnostics
            if item.code == "location-unavailable"
        )
        projected.append(
            replace(
                event,
                location=inferred_identity.display_value,
                location_identity=inferred_identity,
                projection_diagnostics=retained_event_diagnostics + (diagnostic,),
            )
        )
    if not new_diagnostics:
        return loaded
    return replace(
        loaded,
        events=tuple(projected),
        projection_diagnostics=tuple(
            item
            for item in loaded.projection_diagnostics
            if id(item) not in resolved_diagnostic_ids
        )
        + tuple(new_diagnostics),
    )


def _unique_location(
    candidates: list[CalendarEventData], group: str
) -> tuple[CalendarEventData | None, bool]:
    if not candidates:
        return None, False
    keys = {event_location_identity(event).canonical_key for event in candidates}
    if len(keys) == 1:
        return candidates[0], False
    normalized_group = normalize_label(group)
    narrowed = [
        event for event in candidates if normalize_label(event.group) == normalized_group
    ]
    narrowed_keys = {
        event_location_identity(event).canonical_key for event in narrowed
    }
    if narrowed and len(narrowed_keys) == 1:
        return narrowed[0], False
    return None, True
