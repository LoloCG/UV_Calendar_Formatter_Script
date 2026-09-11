"""Detection and semantic projection for the observed UV calendar formats."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from core.models import (
    CalendarEventData,
    CalendarSourceMetadata,
    LocationIdentity,
    ProjectionDiagnostic,
    RawCalendarEvent,
    SourceFormatEvidence,
)
from core.semantic import activity_identity, room_key


CALENDAR_DOWNLOAD = "calendar-download"
DIRECT_DOWNLOAD = "direct-download"
UNKNOWN = "unknown"
MIXED = "mixed"

_CODE_PREFIX_RE = re.compile(r"^\s*(?P<code>\d{4,6})\s*[-–—]\s*")
_DIRECT_GROUP_RE = re.compile(
    r"Grupo\s+(?P<type>.+?)\s+(?P<tag>[A-Za-z0-9-]+)\s*$", re.IGNORECASE
)
_DIRECT_TRAILER_RE = re.compile(r"\s+Grupo\s+.+$", re.IGNORECASE)
_CALENDAR_SUMMARY_RE = re.compile(
    r"^(?P<subject>.+?)\s*\((?P<type>[^()]+?)\s+\(\d{4,6}\)\)\s*$"
)
_CALENDAR_DESCRIPTION_RE = re.compile(
    r"^(?P<tag>[A-Za-z0-9-]+)\s*-\s*Grupo\s+(?P<type>.+?)\s*$",
    re.IGNORECASE,
)
_FULL_LOCATION_RE = re.compile(
    r"^(?P<building>\d+)\s+.+?\s+-\s+(?P<room>.+?)\s*$"
)
_COMPACT_LOCATION_RE = re.compile(
    r"^(?P<room>.+?)\s+(?P<building>\d+)\s*$"
)


@dataclass(frozen=True, slots=True)
class FormatScore:
    adapter_id: str
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CalendarProjection:
    events: tuple[CalendarEventData, ...]
    evidence: SourceFormatEvidence
    diagnostics: tuple[ProjectionDiagnostic, ...]


class CalendarSourceAdapter(Protocol):
    id: str

    def score_calendar(
        self, metadata: CalendarSourceMetadata, raw_events: tuple[RawCalendarEvent, ...]
    ) -> FormatScore: ...

    def supports_event(self, event: RawCalendarEvent) -> bool: ...

    def project_event(self, event: RawCalendarEvent) -> CalendarEventData: ...


class CalendarDownloadAdapter:
    id = CALENDAR_DOWNLOAD

    def score_calendar(self, metadata, raw_events) -> FormatScore:
        shape_count = sum(self.supports_event(event) for event in raw_events)
        ratio = shape_count / len(raw_events) if raw_events else 0.0
        producer = metadata.prodid == "-//UXXIAC-GRD//ES"
        return FormatScore(
            self.id,
            min(1.0, ratio * 0.8 + (0.2 if producer else 0.0)),
            tuple(
                reason
                for reason, matched in (
                    ("calendar-download summary/description shape", ratio > 0),
                    ("UXXIAC-GRD producer", producer),
                )
                if matched
            ),
        )

    def supports_event(self, event: RawCalendarEvent) -> bool:
        _, rest = _subject_prefix(event.summary)
        return bool(_CALENDAR_SUMMARY_RE.match(rest))

    def project_event(self, event: RawCalendarEvent) -> CalendarEventData:
        subject_id, rest = _subject_prefix(event.summary)
        summary_match = _CALENDAR_SUMMARY_RE.match(rest)
        assert summary_match is not None
        description = (event.description or "").strip()
        description_match = _CALENDAR_DESCRIPTION_RE.match(description)
        group = description_match.group("tag").upper() if description_match else ""
        activity = summary_match.group("type").strip()
        diagnostics: list[ProjectionDiagnostic] = []
        if not description_match:
            diagnostics.append(
                _event_diagnostic(
                    event,
                    "calendar-description-unrecognized",
                    "Calendar-download DESCRIPTION did not contain a recognized group.",
                    severity="review",
                )
            )
        location, location_diagnostic = _full_location(event)
        if location_diagnostic:
            diagnostics.append(location_diagnostic)
        return _event_data(
            event,
            subject_id,
            summary_match.group("subject").strip(),
            activity,
            group,
            location,
            self.id,
            diagnostics,
        )


class DirectDownloadAdapter:
    id = DIRECT_DOWNLOAD

    def score_calendar(self, metadata, raw_events) -> FormatScore:
        shape_count = sum(self.supports_event(event) for event in raw_events)
        ratio = shape_count / len(raw_events) if raw_events else 0.0
        producer = metadata.prodid == "-//secvirtual.uv.es//SECVIRTUAL UV"
        return FormatScore(
            self.id,
            min(1.0, ratio * 0.8 + (0.2 if producer else 0.0)),
            tuple(
                reason
                for reason, matched in (
                    ("direct-download summary shape", ratio > 0),
                    ("SECVIRTUAL UV producer", producer),
                )
                if matched
            ),
        )

    def supports_event(self, event: RawCalendarEvent) -> bool:
        return bool(_DIRECT_GROUP_RE.search(event.summary or ""))

    def project_event(self, event: RawCalendarEvent) -> CalendarEventData:
        subject_id, rest = _subject_prefix(event.summary)
        group_match = _DIRECT_GROUP_RE.search(event.summary or "")
        assert group_match is not None
        subject = _DIRECT_TRAILER_RE.sub("", rest).strip()
        activity = group_match.group("type").strip()
        group = group_match.group("tag").upper()
        location, location_diagnostic = _compact_location(event)
        diagnostics = [location_diagnostic] if location_diagnostic else []
        return _event_data(
            event,
            subject_id,
            subject,
            activity,
            group,
            location,
            self.id,
            diagnostics,
        )


class UnknownUVAdapter:
    id = UNKNOWN

    def score_calendar(self, metadata, raw_events) -> FormatScore:
        return FormatScore(self.id, 0.0, ("no supported event shape",))

    def supports_event(self, event: RawCalendarEvent) -> bool:
        return True

    def project_event(self, event: RawCalendarEvent) -> CalendarEventData:
        subject_id, subject = _subject_prefix(event.summary)
        raw_location = event.location
        if raw_location is None:
            raw_location = event.description
        state = "unknown" if raw_location not in {None, ""} else "unavailable"
        location = LocationIdentity(
            display_value=(raw_location or "").strip(),
            raw_value=raw_location,
            provenance="source",
            confidence="unknown",
            state=state,
        )
        diagnostic = _event_diagnostic(
            event,
            "unknown-event-format",
            "Event did not match a supported UV calendar shape; semantic fields need review.",
            severity="review",
        )
        return _event_data(
            event,
            subject_id,
            subject,
            "",
            "",
            location,
            self.id,
            [diagnostic],
        )


ADAPTERS = (CalendarDownloadAdapter(), DirectDownloadAdapter())
UNKNOWN_ADAPTER = UnknownUVAdapter()


def project_calendar(
    metadata: CalendarSourceMetadata, raw_events: tuple[RawCalendarEvent, ...]
) -> CalendarProjection:
    scores = tuple(adapter.score_calendar(metadata, raw_events) for adapter in ADAPTERS)
    projected: list[CalendarEventData] = []
    adapter_ids: list[str] = []
    diagnostics: list[ProjectionDiagnostic] = []
    for raw_event in raw_events:
        supporting = [adapter for adapter in ADAPTERS if adapter.supports_event(raw_event)]
        adapter = supporting[0] if supporting else UNKNOWN_ADAPTER
        event = adapter.project_event(raw_event)
        projected.append(event)
        adapter_ids.append(adapter.id)
        diagnostics.extend(event.projection_diagnostics)

    distinct = set(adapter_ids)
    warnings: list[str] = []
    if not distinct or distinct == {UNKNOWN}:
        adapter_id = UNKNOWN
    elif len(distinct) == 1:
        adapter_id = next(iter(distinct))
    else:
        adapter_id = MIXED
        warnings.append("Calendar contains events from multiple source shapes.")
        diagnostics.append(
            ProjectionDiagnostic(
                code="mixed-calendar-format",
                message=warnings[-1],
                severity="warning",
            )
        )

    metadata_hint = _metadata_hint(metadata)
    if metadata_hint and adapter_id not in {metadata_hint, MIXED}:
        warning = (
            f"Calendar metadata suggests {metadata_hint}, but event shape suggests "
            f"{adapter_id}; event shape was used."
        )
        warnings.append(warning)
        diagnostics.append(
            ProjectionDiagnostic(
                code="format-metadata-mismatch", message=warning, severity="warning"
            )
        )

    relevant_scores = [score for score in scores if score.adapter_id in distinct]
    confidence = (
        sum(score.score for score in relevant_scores) / len(relevant_scores)
        if relevant_scores
        else 0.0
    )
    reasons = tuple(
        dict.fromkeys(reason for score in relevant_scores for reason in score.reasons)
    )
    evidence = SourceFormatEvidence(
        adapter_id=adapter_id,
        confidence=confidence,
        calendar_prodid=metadata.prodid,
        calendar_name=metadata.calendar_name,
        matched_shape_rules=reasons,
        warnings=tuple(warnings),
    )
    return CalendarProjection(tuple(projected), evidence, tuple(diagnostics))


def _subject_prefix(summary: str | None) -> tuple[str, str]:
    text = (summary or "").strip()
    match = _CODE_PREFIX_RE.match(text)
    if not match:
        return "", text
    return match.group("code"), text[match.end() :].strip()


def _full_location(
    event: RawCalendarEvent,
) -> tuple[LocationIdentity, ProjectionDiagnostic | None]:
    raw = event.location
    if raw is None:
        return LocationIdentity(state="unavailable", confidence="unknown"), _event_diagnostic(
            event,
            "location-unavailable",
            "Calendar-download event has no LOCATION property.",
            severity="review",
        )
    if not raw.strip():
        return LocationIdentity(raw_value=raw, state="absent"), None
    match = _FULL_LOCATION_RE.match(raw.strip())
    if not match:
        return LocationIdentity(
            display_value=raw.strip(),
            raw_value=raw,
            source_property="LOCATION",
            confidence="unknown",
            state="unknown",
        ), _event_diagnostic(
            event,
            "location-unrecognized",
            "LOCATION could not be converted to a building/room identity.",
            severity="review",
        )
    return LocationIdentity(
        building_code=match.group("building"),
        room_key=room_key(match.group("room")),
        display_value=raw.strip(),
        raw_value=raw,
        source_property="LOCATION",
    ), None


def _compact_location(
    event: RawCalendarEvent,
) -> tuple[LocationIdentity, ProjectionDiagnostic | None]:
    if event.location is not None and event.location.strip():
        # Prefer a future enriched dedicated property when it has a supported shape.
        full, _ = _full_location(event)
        if full.state == "known":
            return full, None
    raw = event.description
    if raw is None:
        return LocationIdentity(state="unavailable", confidence="unknown"), _event_diagnostic(
            event,
            "location-unavailable",
            "Direct-download event supplies no comparable location value.",
            severity="review",
        )
    if not raw.strip():
        return LocationIdentity(raw_value=raw, state="absent"), None
    match = _COMPACT_LOCATION_RE.match(raw.strip())
    if not match:
        return LocationIdentity(
            display_value=raw.strip(),
            raw_value=raw,
            source_property="DESCRIPTION",
            confidence="unknown",
            state="unknown",
        ), _event_diagnostic(
            event,
            "location-unrecognized",
            "Direct-download DESCRIPTION could not be converted to a room/building identity.",
            severity="review",
        )
    return LocationIdentity(
        building_code=match.group("building"),
        room_key=room_key(match.group("room")),
        display_value=raw.strip(),
        raw_value=raw,
        source_property="DESCRIPTION",
    ), None


def _event_data(
    raw: RawCalendarEvent,
    subject_id: str,
    subject: str,
    activity: str,
    group: str,
    location: LocationIdentity,
    adapter_id: str,
    diagnostics: list[ProjectionDiagnostic],
) -> CalendarEventData:
    if raw.start is None or raw.end is None:
        raise ValueError(f"Calendar event {raw.uid or '<missing UID>'} is missing DTSTART or DTEND")
    identity = activity_identity(activity)
    return CalendarEventData(
        uid=raw.uid or "",
        subject_id=subject_id,
        original_subject=subject,
        class_type=identity.display_value,
        group=group,
        start=raw.start,
        end=raw.end,
        created=raw.created,
        location=location.display_value,
        activity_identity=identity,
        location_identity=location,
        adapter_id=adapter_id,
        projection_diagnostics=tuple(diagnostics),
    )


def _event_diagnostic(
    event: RawCalendarEvent,
    code: str,
    message: str,
    severity: str = "warning",
) -> ProjectionDiagnostic:
    return ProjectionDiagnostic(code, message, severity, event.uid)


def _metadata_hint(metadata: CalendarSourceMetadata) -> str | None:
    if metadata.prodid == "-//UXXIAC-GRD//ES":
        return CALENDAR_DOWNLOAD
    if metadata.prodid == "-//secvirtual.uv.es//SECVIRTUAL UV":
        return DIRECT_DOWNLOAD
    return None
