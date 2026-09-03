"""Versioned portable state and durable content-addressed baseline storage."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from datetime import datetime

from core.change_tracking import (
    PARSER_DATA_VERSION,
    comparison_to_record,
    date_range,
    utc_now_iso,
)
from core.models import CalendarComparison, LoadedCalendar


SCHEMA_VERSION = 2
APPLICATION_VERSION = "0.2.0"
STATE_FILENAME = "calendar_config.json"


class StateValidationError(ValueError):
    pass


def executable_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def portable_data_directory() -> Path:
    return executable_directory() / "data"


def portable_state_path() -> Path:
    return portable_data_directory() / STATE_FILENAME


class CalendarStateStore:
    """Own schema migration, atomic JSON writes, and raw baseline commits."""

    def __init__(
        self,
        state_path: str | Path | None = None,
        *,
        legacy_path: str | Path | None = None,
    ) -> None:
        using_portable_default = state_path is None
        self.path = Path(state_path) if state_path is not None else portable_state_path()
        self.data_dir = self.path.parent
        self.baseline_dir = self.data_dir / "baseline"
        self.legacy_path = (
            Path(legacy_path)
            if legacy_path is not None
            else (
                executable_directory() / STATE_FILENAME
                if using_portable_default or self.path == portable_state_path()
                else self.path
            )
        )
        self._legacy_source: Path | None = None

    def load(self) -> dict:
        source = self.path
        if not source.exists() and self.legacy_path != self.path and self.legacy_path.exists():
            source = self.legacy_path
            self._legacy_source = source
        if not source.exists():
            manifest = self.empty_manifest()
            self._cleanup_orphans_from_manifest(manifest)
            return manifest
        with source.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        if self._is_legacy(raw) or (
            isinstance(raw, dict) and raw.get("schema_version") == 1
        ):
            self._legacy_source = source
            legacy_names = (
                raw.get("subject_names", {})
                if raw.get("schema_version") == 1
                else raw
            )
            return {
                "schema_version": SCHEMA_VERSION,
                "subject_names": _validated_subject_names(legacy_names),
                "tracking": {},
            }
        manifest = self._validate_manifest(raw)
        self._cleanup_orphans_from_manifest(manifest)
        return manifest

    @staticmethod
    def empty_manifest() -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "subject_names": {},
            "tracking": {},
        }

    def subject_names(self) -> dict[str, str]:
        return dict(self.load()["subject_names"])

    def baseline_metadata(self) -> dict | None:
        baseline = self.load()["tracking"].get("baseline")
        return dict(baseline) if baseline else None

    def baseline_path(self, manifest: dict | None = None) -> Path | None:
        state = manifest or self.load()
        baseline = state["tracking"].get("baseline")
        if not baseline:
            return None
        relative = Path(baseline["raw_ics_path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise StateValidationError("Baseline path must stay inside the data directory")
        result = (self.data_dir / relative).resolve()
        if self.data_dir.resolve() not in result.parents:
            raise StateValidationError("Baseline path escapes the data directory")
        return result

    def verified_baseline_path(self, manifest: dict | None = None) -> Path | None:
        state = manifest or self.load()
        path = self.baseline_path(state)
        if path is None:
            return None
        if not path.is_file():
            raise StateValidationError(f"Stored baseline is missing: {path}")
        expected = state["tracking"]["baseline"]["source_sha256"]
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise StateValidationError("Stored baseline source hash does not match its file")
        return path

    def is_writable(self) -> tuple[bool, str]:
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            descriptor, probe_name = tempfile.mkstemp(prefix=".write-probe-", dir=self.data_dir)
            os.close(descriptor)
            Path(probe_name).unlink()
            return True, ""
        except OSError as error:
            return False, (
                f"Tracking is read-only at {self.data_dir}: {error}. Move the "
                "executable together with its data directory to a writable location."
            )

    def save_subject_names(self, names: Mapping[str, str]) -> None:
        manifest = self.load()
        manifest["subject_names"] = _validated_subject_names(names)
        self._atomic_write(manifest)

    def record_last_check(self, comparison: CalendarComparison) -> None:
        manifest = self.load()
        manifest["tracking"]["last_check"] = {
            "analyzed_at_utc": comparison.analyzed_at_utc,
            "source_name": comparison.source_name,
            "source_sha256": comparison.source_sha256,
            "canonical_sha256": comparison.canonical_sha256,
            "result": comparison.status,
        }
        self._atomic_write(manifest)

    def migrate_projection_metadata(
        self,
        canonical_sha256: str,
        event_count: int,
        event_date_range: dict | None,
    ) -> None:
        manifest = self.load()
        baseline = manifest["tracking"].get("baseline")
        if not baseline:
            return
        baseline["parser_data_version"] = PARSER_DATA_VERSION
        baseline["canonical_sha256"] = canonical_sha256
        baseline["event_count"] = event_count
        baseline["date_range"] = event_date_range
        last_change = manifest["tracking"].get("last_change")
        if last_change is not None:
            last_change["current_canonical_sha256"] = canonical_sha256
        self._atomic_write(manifest)

    def accept_baseline(
        self,
        loaded: LoadedCalendar,
        comparison: CalendarComparison,
        subject_names: Mapping[str, str],
        *,
        accepted_at_utc: str | None = None,
    ) -> dict:
        if not comparison.can_remember:
            raise ValueError("This comparison cannot be remembered as a baseline")
        source_bytes = loaded.source_path.read_bytes()
        source_hash = hashlib.sha256(source_bytes).hexdigest()
        if source_hash != comparison.source_sha256:
            raise ValueError("Selected calendar changed after it was analysed")
        accepted_at = accepted_at_utc or utc_now_iso()
        manifest = self.load()
        old_baseline = manifest["tracking"].get("baseline")

        self.baseline_dir.mkdir(parents=True, exist_ok=True)
        target = self.baseline_dir / f"{source_hash}.ics"
        if not target.exists():
            temporary = self._write_durable_temp(self.baseline_dir, source_bytes)
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != source_hash:
                temporary.unlink(missing_ok=True)
                raise OSError("Raw baseline verification failed")
            os.replace(temporary, target)

        manifest["subject_names"] = _validated_subject_names(subject_names)
        manifest["tracking"]["baseline"] = {
            "analyzed_at_utc": comparison.analyzed_at_utc,
            "accepted_at_utc": accepted_at,
            "application_version": APPLICATION_VERSION,
            "parser_data_version": PARSER_DATA_VERSION,
            "source_name": loaded.source_path.name,
            "source_sha256": source_hash,
            "raw_ics_path": f"baseline/{source_hash}.ics",
            "canonical_sha256": comparison.canonical_sha256,
            "event_count": len(loaded.events),
            "date_range": date_range(loaded.events),
        }
        manifest["tracking"]["last_check"] = {
            "analyzed_at_utc": comparison.analyzed_at_utc,
            "source_name": comparison.source_name,
            "source_sha256": comparison.source_sha256,
            "canonical_sha256": comparison.canonical_sha256,
            "result": comparison.status,
        }
        if comparison.status == "changed":
            manifest["tracking"]["last_change"] = comparison_to_record(
                comparison, accepted_at
            )
        else:
            manifest["tracking"].pop("last_change", None)
        self._atomic_write(manifest)

        if old_baseline and old_baseline.get("source_sha256") != source_hash:
            old_path = self.data_dir / old_baseline["raw_ics_path"]
            try:
                old_path.unlink(missing_ok=True)
            except OSError:
                pass
        self._remove_unreferenced_baselines(source_hash)
        return manifest["tracking"]["baseline"]

    def reset(self) -> None:
        """Remove only this feature's known academic-year state."""

        if self.baseline_dir.exists():
            shutil.rmtree(self.baseline_dir)
        self.path.unlink(missing_ok=True)
        self.path.with_suffix(self.path.suffix + ".legacy.bak").unlink(missing_ok=True)
        try:
            self.data_dir.rmdir()
        except OSError:
            pass

    def _atomic_write(self, manifest: dict) -> None:
        validated = self._validate_manifest(manifest)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        legacy_source = self._legacy_source
        if legacy_source is not None:
            backup = (
                self.path.with_suffix(self.path.suffix + ".legacy.bak")
                if legacy_source == self.path
                else legacy_source.with_suffix(legacy_source.suffix + ".legacy.bak")
            )
            if not backup.exists():
                shutil.copy2(legacy_source, backup)
        payload = json.dumps(validated, indent=2, ensure_ascii=False).encode("utf-8")
        temporary = self._write_durable_temp(self.data_dir, payload)
        try:
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
        if legacy_source is not None and legacy_source != self.path:
            # The recoverable sibling backup remains, while removing the old
            # discovery name makes migration genuinely one-time after a later
            # manual deletion of data/.
            try:
                legacy_source.unlink(missing_ok=True)
            except OSError:
                pass
        self._legacy_source = None

    @staticmethod
    def _write_durable_temp(directory: Path, payload: bytes) -> Path:
        descriptor, name = tempfile.mkstemp(prefix=".calendar-state-", dir=directory)
        path = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return path

    def _remove_unreferenced_baselines(self, retained_hash: str) -> None:
        if not self.baseline_dir.exists():
            return
        for path in self.baseline_dir.glob("*.ics"):
            if path.name != f"{retained_hash}.ics":
                try:
                    path.unlink()
                except OSError:
                    pass

    def _cleanup_orphans_from_manifest(self, manifest: dict) -> None:
        """Best-effort cleanup after an interrupted pre-manifest raw write."""

        if not self.baseline_dir.exists():
            return
        baseline = manifest["tracking"].get("baseline")
        retained_hash = baseline.get("source_sha256") if baseline else None
        for path in self.baseline_dir.glob("*.ics"):
            if retained_hash is None or path.name != f"{retained_hash}.ics":
                try:
                    path.unlink()
                except OSError:
                    pass

    @staticmethod
    def _is_legacy(raw: object) -> bool:
        return isinstance(raw, dict) and "schema_version" not in raw

    @staticmethod
    def _validate_manifest(raw: object) -> dict:
        if not isinstance(raw, dict):
            raise StateValidationError("Calendar state must contain a JSON object")
        version = raw.get("schema_version")
        if not isinstance(version, int):
            raise StateValidationError("Calendar state is missing schema_version")
        if version > SCHEMA_VERSION:
            raise StateValidationError(
                f"Calendar state schema {version} is newer than supported schema {SCHEMA_VERSION}"
            )
        if version != SCHEMA_VERSION:
            raise StateValidationError(f"Unsupported calendar state schema {version}")
        subject_names = _validated_subject_names(raw.get("subject_names"))
        tracking = raw.get("tracking")
        if not isinstance(tracking, dict):
            raise StateValidationError("Calendar state tracking must be an object")
        baseline = tracking.get("baseline")
        if baseline is not None:
            _validate_baseline(baseline)
        if "last_check" in tracking:
            _validate_last_check(tracking["last_check"])
        if "last_change" in tracking:
            _validate_last_change(tracking["last_change"])
            if baseline is None:
                raise StateValidationError("tracking.last_change requires an accepted baseline")
            if (
                tracking["last_change"]["current_source_sha256"]
                != baseline["source_sha256"]
                or tracking["last_change"]["current_canonical_sha256"]
                != baseline["canonical_sha256"]
            ):
                raise StateValidationError(
                    "tracking.last_change current hashes must match the accepted baseline"
                )
        return {
            "schema_version": SCHEMA_VERSION,
            "subject_names": subject_names,
            "tracking": dict(tracking),
        }


def _validated_subject_names(subject_names: object) -> dict[str, str]:
    if not isinstance(subject_names, Mapping):
        raise StateValidationError("subject_names must be a JSON object")
    result = {}
    for subject_id, name in subject_names.items():
        if not isinstance(subject_id, str):
            raise StateValidationError("Subject IDs must be strings")
        if not isinstance(name, str) or not name.strip():
            raise StateValidationError(f"Subject name for {subject_id!r} must be non-empty")
        result[subject_id] = name.strip()
    return result


def _validate_baseline(baseline: object) -> None:
    if not isinstance(baseline, dict):
        raise StateValidationError("tracking.baseline must be an object")
    required_strings = (
        "analyzed_at_utc",
        "accepted_at_utc",
        "application_version",
        "source_name",
        "source_sha256",
        "raw_ics_path",
        "canonical_sha256",
    )
    for field in required_strings:
        if not isinstance(baseline.get(field), str) or not baseline[field]:
            raise StateValidationError(f"tracking.baseline.{field} must be a string")
    _validate_utc_timestamp(baseline["analyzed_at_utc"], "tracking.baseline.analyzed_at_utc")
    _validate_utc_timestamp(baseline["accepted_at_utc"], "tracking.baseline.accepted_at_utc")
    _validate_hash(baseline["source_sha256"], "tracking.baseline.source_sha256")
    _validate_hash(baseline["canonical_sha256"], "tracking.baseline.canonical_sha256")
    if not isinstance(baseline.get("parser_data_version"), int):
        raise StateValidationError("tracking.baseline.parser_data_version must be an integer")
    if not isinstance(baseline.get("event_count"), int) or baseline["event_count"] < 0:
        raise StateValidationError("tracking.baseline.event_count must be non-negative")
    date_value = baseline.get("date_range")
    if date_value is not None and (
        not isinstance(date_value, dict)
        or not isinstance(date_value.get("start"), str)
        or not isinstance(date_value.get("end"), str)
    ):
        raise StateValidationError("tracking.baseline.date_range is invalid")


def _validate_last_check(value: object) -> None:
    if not isinstance(value, dict):
        raise StateValidationError("tracking.last_check must be an object")
    for field in ("analyzed_at_utc", "source_name", "source_sha256", "canonical_sha256", "result"):
        if not isinstance(value.get(field), str) or not value[field]:
            raise StateValidationError(f"tracking.last_check.{field} must be a string")
    _validate_utc_timestamp(value["analyzed_at_utc"], "tracking.last_check.analyzed_at_utc")
    _validate_hash(value["source_sha256"], "tracking.last_check.source_sha256")
    _validate_hash(value["canonical_sha256"], "tracking.last_check.canonical_sha256")
    if value["result"] not in {"first", "unchanged", "changed"}:
        raise StateValidationError("tracking.last_check.result is invalid")


def _validate_last_change(value: object) -> None:
    if not isinstance(value, dict):
        raise StateValidationError("tracking.last_change must be an object")
    for field in (
        "analyzed_at_utc",
        "accepted_at_utc",
        "previous_source_sha256",
        "current_source_sha256",
        "previous_canonical_sha256",
        "current_canonical_sha256",
        "current_source_name",
    ):
        if not isinstance(value.get(field), str) or not value[field]:
            raise StateValidationError(f"tracking.last_change.{field} must be a string")
    _validate_utc_timestamp(value["analyzed_at_utc"], "tracking.last_change.analyzed_at_utc")
    _validate_utc_timestamp(value["accepted_at_utc"], "tracking.last_change.accepted_at_utc")
    for field in ("previous_source_sha256", "current_source_sha256", "previous_canonical_sha256", "current_canonical_sha256"):
        _validate_hash(value[field], f"tracking.last_change.{field}")
    summary = value.get("summary")
    events = value.get("event_changes")
    collisions = value.get("collision_changes")
    if not isinstance(summary, dict) or not isinstance(events, list) or not isinstance(collisions, list):
        raise StateValidationError("tracking.last_change summary and detail arrays are required")
    for item in events:
        if not isinstance(item, dict) or item.get("change") not in {
            "added", "removed", "modified", "ambiguous"
        }:
            raise StateValidationError("tracking.last_change.event_changes contains an invalid entry")
    for item in collisions:
        if not isinstance(item, dict) or item.get("change") not in {
            "new", "resolved", "changed"
        }:
            raise StateValidationError("tracking.last_change.collision_changes contains an invalid entry")
    expected = {
        "added": sum(isinstance(item, dict) and item.get("change") == "added" for item in events),
        "removed": sum(isinstance(item, dict) and item.get("change") == "removed" for item in events),
        "modified": sum(isinstance(item, dict) and item.get("change") == "modified" for item in events),
        "ambiguous": sum(isinstance(item, dict) and item.get("change") == "ambiguous" for item in events),
        "new_collisions": sum(isinstance(item, dict) and item.get("change") == "new" for item in collisions),
        "resolved_collisions": sum(isinstance(item, dict) and item.get("change") == "resolved" for item in collisions),
        "changed_collisions": sum(isinstance(item, dict) and item.get("change") == "changed" for item in collisions),
    }
    if summary != expected:
        raise StateValidationError("tracking.last_change summary does not agree with its detail arrays")


def _validate_hash(value: str, field: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise StateValidationError(f"{field} must be a lowercase SHA-256 hash")


def _validate_utc_timestamp(value: str, field: str) -> None:
    if not value.endswith("Z"):
        raise StateValidationError(f"{field} must use an explicit UTC Z suffix")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise StateValidationError(f"{field} is not a valid ISO 8601 timestamp") from error
