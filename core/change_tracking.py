"""Deterministic, UID-independent calendar and collision comparison."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from core.collision_detector import analyze_collisions
from core.models import (
    CalendarComparison,
    CalendarEventData,
    CollisionAnalysis,
    CollisionChange,
    EventChange,
    LoadedCalendar,
    MatchWarning,
)
from core.text_utils import normalize_label


PARSER_DATA_VERSION = 1
UNRELATED_SUBJECT_OVERLAP = 0.25
UNRELATED_DATE_OVERLAP = 0.25
UNRELATED_DATE_GAP_DAYS = 90


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def source_sha256(path: str | Path) -> str:
    source = Path(path)
    if not source.is_file():
        # Supports injected in-memory calendars in UI/unit tests. Baseline
        # acceptance still requires and verifies the real selected source.
        return hashlib.sha256(b"").hexdigest()
    return hashlib.sha256(source.read_bytes()).hexdigest()


def subject_key(event: CalendarEventData) -> str:
    return event.subject_id.strip() or normalize_label(event.original_subject)


def canonical_signature(event: CalendarEventData) -> tuple[str, ...]:
    return (
        subject_key(event),
        normalize_label(event.class_type),
        normalize_label(event.group),
        _utc_value(event.start),
        _utc_value(event.end),
        normalize_label(event.location),
    )


def canonical_sha256(events: Iterable[CalendarEventData]) -> str:
    signatures = sorted(canonical_signature(event) for event in events)
    payload = json.dumps(
        signatures, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def date_range(events: Iterable[CalendarEventData]) -> dict[str, str] | None:
    source = tuple(events)
    if not source:
        return None
    return {
        "start": min(event.start.date() for event in source).isoformat(),
        "end": max(event.end.date() for event in source).isoformat(),
    }


def compare_calendars(
    baseline: LoadedCalendar | None,
    current: LoadedCalendar,
    *,
    baseline_collisions: CollisionAnalysis | None = None,
    current_collisions: CollisionAnalysis | None = None,
    baseline_metadata: dict | None = None,
    analyzed_at_utc: str | None = None,
) -> CalendarComparison:
    """Compare normalized projections without relying on source UIDs."""

    analyzed_at = analyzed_at_utc or utc_now_iso()
    current_hash = canonical_sha256(current.events)
    current_source_hash = source_sha256(current.source_path)
    if baseline is None:
        return CalendarComparison(
            status="first",
            analyzed_at_utc=analyzed_at,
            source_name=current.source_path.name,
            source_sha256=current_source_hash,
            canonical_sha256=current_hash,
        )

    baseline_hash = canonical_sha256(baseline.events)
    metadata = dict(baseline_metadata or {})
    baseline_source_hash = metadata.get("source_sha256") or source_sha256(
        baseline.source_path
    )
    if Counter(map(canonical_signature, baseline.events)) == Counter(
        map(canonical_signature, current.events)
    ):
        return CalendarComparison(
            status="unchanged",
            analyzed_at_utc=analyzed_at,
            source_name=current.source_path.name,
            source_sha256=current_source_hash,
            canonical_sha256=current_hash,
            baseline_metadata=metadata,
            baseline_canonical_sha256=baseline_hash,
            baseline_source_sha256=baseline_source_hash,
        )

    matches, warnings = _match_events(baseline.events, current.events)
    event_changes = _event_changes(baseline.events, current.events, matches)
    baseline_analysis = baseline_collisions or analyze_collisions(baseline.events)
    current_analysis = current_collisions or analyze_collisions(current.events)
    collision_changes = _collision_changes(
        baseline.events,
        current.events,
        baseline_analysis,
        current_analysis,
        matches,
        event_changes,
    )
    unrelated, unrelated_reason = unrelated_calendar_reason(
        baseline.events, current.events
    )
    return CalendarComparison(
        status="changed",
        analyzed_at_utc=analyzed_at,
        source_name=current.source_path.name,
        source_sha256=current_source_hash,
        canonical_sha256=current_hash,
        event_changes=event_changes,
        collision_changes=collision_changes,
        warnings=warnings,
        baseline_metadata=metadata,
        baseline_canonical_sha256=baseline_hash,
        baseline_source_sha256=baseline_source_hash,
        event_matches=tuple(sorted(matches.items())),
        possibly_unrelated=unrelated,
        unrelated_reason=unrelated_reason,
    )


def unrelated_calendar_reason(
    baseline: tuple[CalendarEventData, ...],
    current: tuple[CalendarEventData, ...],
) -> tuple[bool, str]:
    """Return a containment-friendly overlap warning; never resets state."""

    old_subjects = {subject_key(event) for event in baseline}
    new_subjects = {subject_key(event) for event in current}
    smaller = min(len(old_subjects), len(new_subjects))
    subject_overlap = (
        len(old_subjects & new_subjects) / smaller if smaller else 0.0
    )
    old_range = _date_bounds(baseline)
    new_range = _date_bounds(current)
    date_overlap = 0.0
    gap_days = 0
    if old_range and new_range:
        overlap_days = max(
            0,
            (min(old_range[1], new_range[1]) - max(old_range[0], new_range[0])).days
            + 1,
        )
        smaller_span = min(
            (old_range[1] - old_range[0]).days + 1,
            (new_range[1] - new_range[0]).days + 1,
        )
        date_overlap = overlap_days / smaller_span
        if overlap_days == 0:
            gap_days = max(
                (new_range[0] - old_range[1]).days,
                (old_range[0] - new_range[1]).days,
            )

    unrelated = (
        subject_overlap < UNRELATED_SUBJECT_OVERLAP
        and date_overlap < UNRELATED_DATE_OVERLAP
    ) or (date_overlap == 0 and gap_days > UNRELATED_DATE_GAP_DAYS)
    reason = (
        f"subject overlap {subject_overlap:.0%}, date-range overlap "
        f"{date_overlap:.0%}"
    )
    if gap_days:
        reason += f", date gap {gap_days} days"
    return unrelated, reason


def event_to_record(event: CalendarEventData) -> dict[str, str]:
    return {
        "subject_id": event.subject_id,
        "subject": event.original_subject,
        "activity_type": normalize_label(event.class_type),
        "group": normalize_label(event.group),
        "start": _utc_value(event.start),
        "end": _utc_value(event.end),
        "source_start": event.start.isoformat(),
        "source_end": event.end.isoformat(),
        "location": " ".join(event.location.split()),
    }


def comparison_to_record(comparison: CalendarComparison, accepted_at: str) -> dict:
    event_records = []
    for change in comparison.event_changes:
        event_records.append(
            {
                "change": change.change,
                "categories": list(change.categories),
                "before": event_to_record(change.before) if change.before else None,
                "current": event_to_record(change.current) if change.current else None,
                "fields": {
                    name: {"before": values[0], "current": values[1]}
                    for name, values in change.fields.items()
                },
            }
        )
    for warning in comparison.warnings:
        event_records.append(
            {
                "change": "ambiguous",
                "reason": warning.reason,
                "baseline_candidates": [
                    event_to_record(event) for event in warning.baseline_candidates
                ],
                "current_candidates": [
                    event_to_record(event) for event in warning.current_candidates
                ],
            }
        )
    collision_records = [
        {
            "change": change.change,
            "before": _collision_record(change.before),
            "current": _collision_record(change.current),
            "related_event_changes": list(change.related_event_changes),
        }
        for change in comparison.collision_changes
    ]
    return {
        "analyzed_at_utc": comparison.analyzed_at_utc,
        "accepted_at_utc": accepted_at,
        "previous_source_sha256": comparison.baseline_source_sha256,
        "current_source_sha256": comparison.source_sha256,
        "previous_canonical_sha256": comparison.baseline_canonical_sha256,
        "current_canonical_sha256": comparison.canonical_sha256,
        "current_source_name": comparison.source_name,
        "summary": comparison.summary,
        "event_changes": event_records,
        "collision_changes": collision_records,
    }


def _match_events(
    baseline: tuple[CalendarEventData, ...],
    current: tuple[CalendarEventData, ...],
) -> tuple[dict[int, int], tuple[MatchWarning, ...]]:
    matches: dict[int, int] = {}
    old_by_signature: dict[tuple[str, ...], deque[int]] = defaultdict(deque)
    new_by_signature: dict[tuple[str, ...], deque[int]] = defaultdict(deque)
    for index, event in enumerate(baseline):
        old_by_signature[canonical_signature(event)].append(index)
    for index, event in enumerate(current):
        new_by_signature[canonical_signature(event)].append(index)
    for signature in sorted(old_by_signature.keys() & new_by_signature.keys()):
        old_queue = old_by_signature[signature]
        new_queue = new_by_signature[signature]
        while old_queue and new_queue:
            matches[old_queue.popleft()] = new_queue.popleft()

    old_remaining = set(range(len(baseline))) - set(matches)
    new_remaining = set(range(len(current))) - set(matches.values())
    warnings: list[MatchWarning] = []
    blocked_old: set[int] = set()
    blocked_new: set[int] = set()

    strong_old: dict[tuple[str, str, str], set[int]] = defaultdict(set)
    strong_new: dict[tuple[str, str, str], set[int]] = defaultdict(set)
    for index in old_remaining:
        strong_old[_strong_key(baseline[index])].add(index)
    for index in new_remaining:
        strong_new[_strong_key(current[index])].add(index)
    for key in sorted(strong_old.keys() & strong_new.keys()):
        group_matches, ambiguous_old, ambiguous_new = _closest_pairs(
            strong_old[key], strong_new[key], baseline, current
        )
        matches.update(group_matches)
        old_remaining -= set(group_matches)
        new_remaining -= set(group_matches.values())
        if ambiguous_old and ambiguous_new:
            blocked_old.update(ambiguous_old)
            blocked_new.update(ambiguous_new)
            warnings.append(
                MatchWarning(
                    reason="equally close sessions share subject, activity, and group",
                    baseline_candidates=tuple(baseline[i] for i in sorted(ambiguous_old)),
                    current_candidates=tuple(current[i] for i in sorted(ambiguous_new)),
                )
            )

    weak_old: dict[str, set[int]] = defaultdict(set)
    weak_new: dict[str, set[int]] = defaultdict(set)
    for index in old_remaining - blocked_old:
        weak_old[subject_key(baseline[index])].add(index)
    for index in new_remaining - blocked_new:
        weak_new[subject_key(current[index])].add(index)
    for key in sorted(weak_old.keys() & weak_new.keys()):
        candidates = {
            (old, new)
            for old in weak_old[key]
            for new in weak_new[key]
            if _weak_confidence(baseline[old], current[new])
        }
        group_matches, ambiguous_old, ambiguous_new = _unique_candidate_pairs(
            candidates
        )
        matches.update(group_matches)
        old_remaining -= set(group_matches)
        new_remaining -= set(group_matches.values())
        if ambiguous_old and ambiguous_new:
            warnings.append(
                MatchWarning(
                    reason="multiple same-subject candidates have equal time/context evidence",
                    baseline_candidates=tuple(baseline[i] for i in sorted(ambiguous_old)),
                    current_candidates=tuple(current[i] for i in sorted(ambiguous_new)),
                )
            )
    return matches, tuple(warnings)


def _closest_pairs(old_indices, new_indices, baseline, current):
    remaining_old = set(old_indices)
    remaining_new = set(new_indices)
    matches: dict[int, int] = {}
    made_progress = True
    while made_progress and remaining_old and remaining_new:
        made_progress = False
        old_choices = {
            old: _nearest_new(old, remaining_new, baseline, current)
            for old in remaining_old
        }
        new_choices = {
            new: _nearest_old(new, remaining_old, baseline, current)
            for new in remaining_new
        }
        pairs = []
        for old, choices in old_choices.items():
            if len(choices) != 1:
                continue
            new = next(iter(choices))
            if new_choices[new] == {old}:
                pairs.append((old, new))
        for old, new in sorted(pairs):
            matches[old] = new
            remaining_old.remove(old)
            remaining_new.remove(new)
            made_progress = True
    return matches, remaining_old, remaining_new


def _unique_candidate_pairs(candidates: set[tuple[int, int]]):
    matches: dict[int, int] = {}
    remaining = set(candidates)
    progress = True
    while progress:
        progress = False
        old_counts = Counter(old for old, _ in remaining)
        new_counts = Counter(new for _, new in remaining)
        unique = sorted(
            (old, new)
            for old, new in remaining
            if old_counts[old] == 1 and new_counts[new] == 1
        )
        for old, new in unique:
            matches[old] = new
            remaining = {
                pair for pair in remaining if old not in pair and new not in pair
            }
            progress = True
    return (
        matches,
        {old for old, _ in remaining},
        {new for _, new in remaining},
    )


def _nearest_new(old, new_indices, baseline, current):
    distances = {
        new: _time_distance(baseline[old], current[new]) for new in new_indices
    }
    nearest = min(distances.values())
    return {new for new, distance in distances.items() if distance == nearest}


def _nearest_old(new, old_indices, baseline, current):
    distances = {
        old: _time_distance(baseline[old], current[new]) for old in old_indices
    }
    nearest = min(distances.values())
    return {old for old, distance in distances.items() if distance == nearest}


def _time_distance(first, second):
    return abs((first.start - second.start).total_seconds()) + abs(
        (first.end - second.end).total_seconds()
    )


def _weak_confidence(first, second):
    exact_interval = first.start == second.start and first.end == second.end
    same_location = normalize_label(first.location) == normalize_label(second.location)
    close = abs((first.start - second.start).total_seconds()) <= 7 * 86400
    return exact_interval or (same_location and close)


def _strong_key(event):
    return (
        subject_key(event),
        normalize_label(event.class_type),
        normalize_label(event.group),
    )


def _event_changes(baseline, current, matches):
    changes: list[EventChange] = []
    for old, new in sorted(matches.items(), key=lambda item: current[item[1]].start):
        first, second = baseline[old], current[new]
        fields: dict[str, tuple[str, str]] = {}
        categories: list[str] = []
        if first.start != second.start or first.end != second.end:
            fields["schedule"] = (
                f"{first.start.isoformat()} / {first.end.isoformat()}",
                f"{second.start.isoformat()} / {second.end.isoformat()}",
            )
            categories.append("rescheduled")
        if normalize_label(first.location) != normalize_label(second.location):
            fields["location"] = (first.location, second.location)
            categories.append("relocated")
        if normalize_label(first.group) != normalize_label(second.group):
            fields["group"] = (first.group, second.group)
            categories.append("regrouped")
        if normalize_label(first.class_type) != normalize_label(second.class_type):
            fields["activity_type"] = (first.class_type, second.class_type)
            categories.append("retyped")
        if categories:
            changes.append(
                EventChange(
                    change="modified",
                    categories=tuple(categories),
                    before=first,
                    current=second,
                    fields=fields,
                )
            )
    matched_old = set(matches)
    matched_new = set(matches.values())
    changes.extend(
        EventChange(change="removed", before=baseline[index])
        for index in sorted(set(range(len(baseline))) - matched_old, key=lambda i: baseline[i].start)
    )
    changes.extend(
        EventChange(change="added", current=current[index])
        for index in sorted(set(range(len(current))) - matched_new, key=lambda i: current[i].start)
    )
    return tuple(sorted(changes, key=_change_sort_key))


def _collision_changes(
    baseline_events,
    current_events,
    baseline_analysis,
    current_analysis,
    matches,
    event_changes,
):
    old_index = {id(event): index for index, event in enumerate(baseline_events)}
    new_index = {id(event): index for index, event in enumerate(current_events)}
    old_collisions = {
        tuple(sorted((old_index[id(pair.first)], old_index[id(pair.second)]))): pair
        for pair in baseline_analysis.collisions
    }
    new_collisions = {
        tuple(sorted((new_index[id(pair.first)], new_index[id(pair.second)]))): pair
        for pair in current_analysis.collisions
    }
    consumed_new = set()
    changes: list[CollisionChange] = []
    event_change_indexes = _event_change_indexes(
        baseline_events, current_events, event_changes
    )
    for old_pair, old_collision in sorted(old_collisions.items()):
        translated = (
            tuple(sorted((matches[old_pair[0]], matches[old_pair[1]])))
            if old_pair[0] in matches and old_pair[1] in matches
            else None
        )
        current_collision = new_collisions.get(translated) if translated else None
        related = tuple(
            sorted(
                set(event_change_indexes.get(("old", index), -1) for index in old_pair)
                - {-1}
            )
        )
        if current_collision is None:
            changes.append(
                CollisionChange("resolved", before=old_collision, related_event_changes=related)
            )
        else:
            consumed_new.add(translated)
            if (
                _utc_value(old_collision.overlap_start)
                != _utc_value(current_collision.overlap_start)
                or _utc_value(old_collision.overlap_end)
                != _utc_value(current_collision.overlap_end)
            ):
                changes.append(
                    CollisionChange(
                        "changed",
                        before=old_collision,
                        current=current_collision,
                        related_event_changes=related,
                    )
                )
    for new_pair, current_collision in sorted(new_collisions.items()):
        if new_pair not in consumed_new:
            related = tuple(
                sorted(
                    set(event_change_indexes.get(("new", index), -1) for index in new_pair)
                    - {-1}
                )
            )
            changes.append(
                CollisionChange("new", current=current_collision, related_event_changes=related)
            )
    return tuple(changes)


def _event_change_indexes(baseline, current, changes):
    result = {}
    old_index = {id(event): index for index, event in enumerate(baseline)}
    new_index = {id(event): index for index, event in enumerate(current)}
    for index, change in enumerate(changes):
        if change.before is not None:
            result[("old", old_index[id(change.before)])] = index
        if change.current is not None:
            result[("new", new_index[id(change.current)])] = index
    return result


def _collision_record(collision):
    if collision is None:
        return None
    return {
        "first": event_to_record(collision.first),
        "second": event_to_record(collision.second),
        "overlap_start": _utc_value(collision.overlap_start),
        "overlap_end": _utc_value(collision.overlap_end),
    }


def _change_sort_key(change):
    event = change.current or change.before
    return (event.start, {"removed": 0, "modified": 1, "added": 2}[change.change])


def _utc_value(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Calendar comparison requires timezone-aware event times")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _date_bounds(events):
    if not events:
        return None
    return min(event.start.date() for event in events), max(
        event.end.date() for event in events
    )
