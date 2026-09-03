from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CalendarEventData:
    """Normalized event data shared by formatting and analysis features."""

    uid: str
    subject_id: str
    original_subject: str
    class_type: str
    group: str
    start: datetime
    end: datetime
    created: datetime | None
    location: str


@dataclass(frozen=True, slots=True)
class LoadedCalendar:
    """A parsed source calendar and the data derived during its single read."""

    source_path: Path
    preamble: str
    events: tuple[CalendarEventData, ...]
    subject_catalog: dict[str, str]


@dataclass(frozen=True, slots=True)
class GenerationResult:
    """Summary returned after a formatted calendar has been written."""

    output_path: Path
    config_path: Path
    event_count: int
    custom_names_applied: bool
    config_saved: bool = True


@dataclass(frozen=True, slots=True)
class EventChange:
    """One conservative cross-snapshot event comparison result."""

    change: str
    categories: tuple[str, ...] = ()
    before: CalendarEventData | None = None
    current: CalendarEventData | None = None
    fields: dict[str, tuple[str, str]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MatchWarning:
    """Candidates that were deliberately left unmatched due to ambiguity."""

    reason: str
    baseline_candidates: tuple[CalendarEventData, ...]
    current_candidates: tuple[CalendarEventData, ...]


@dataclass(frozen=True, slots=True)
class CollisionChange:
    """A new, resolved, or overlap-changed collision pair."""

    change: str
    before: CollisionPair | None = None
    current: CollisionPair | None = None
    related_event_changes: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class CalendarComparison:
    """Complete result of comparing the selected calendar to its baseline."""

    status: str
    analyzed_at_utc: str
    source_name: str
    source_sha256: str
    canonical_sha256: str
    event_changes: tuple[EventChange, ...] = ()
    collision_changes: tuple[CollisionChange, ...] = ()
    warnings: tuple[MatchWarning, ...] = ()
    baseline_metadata: dict | None = None
    baseline_canonical_sha256: str | None = None
    baseline_source_sha256: str | None = None
    event_matches: tuple[tuple[int, int], ...] = ()
    possibly_unrelated: bool = False
    unrelated_reason: str = ""

    @property
    def can_remember(self) -> bool:
        return self.status in {"first", "changed"} and not self.possibly_unrelated

    @property
    def summary(self) -> dict[str, int]:
        return {
            "added": sum(c.change == "added" for c in self.event_changes),
            "removed": sum(c.change == "removed" for c in self.event_changes),
            "modified": sum(c.change == "modified" for c in self.event_changes),
            "ambiguous": len(self.warnings),
            "new_collisions": sum(
                c.change == "new" for c in self.collision_changes
            ),
            "resolved_collisions": sum(
                c.change == "resolved" for c in self.collision_changes
            ),
            "changed_collisions": sum(
                c.change == "changed" for c in self.collision_changes
            ),
        }


@dataclass(frozen=True, slots=True)
class CollisionPair:
    """Two source sessions and the exact interval in which they overlap."""

    first: CalendarEventData
    second: CalendarEventData
    overlap_start: datetime
    overlap_end: datetime


@dataclass(frozen=True, slots=True)
class CollisionAnalysis:
    """Neutral collisions plus the laboratory-focused reporting projection."""

    event_count: int
    collisions: tuple[CollisionPair, ...]
    laboratory_collisions: tuple[CollisionPair, ...]
    affected_laboratory_sessions: frozenset[str]

    @property
    def collision_count(self) -> int:
        return len(self.collisions)

    @property
    def laboratory_collision_count(self) -> int:
        return len(self.laboratory_collisions)

    @property
    def affected_laboratory_count(self) -> int:
        return len(self.affected_laboratory_sessions)
