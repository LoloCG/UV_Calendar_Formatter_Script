from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from core.activity_policy import blocks_calendar_time
from core.ics_formatter import UVEventFormatter
from core.models import GenerationResult, LoadedCalendar
from core.state_store import CalendarStateStore, portable_state_path
from core.subject_catalog import build_subject_catalog
from utils.ics_compat import disable_parser_colorization
from utils.ics_utils import ICSCalendarHandler, ICSGenerator


DEFAULT_CONFIG_PATH = portable_state_path()
DEFAULT_OUTPUT_PATH = Path("new_calendar.ics")


def load_calendar(path: str | Path) -> LoadedCalendar:
    """Read a calendar once and normalize all of its events."""

    disable_parser_colorization()
    source_path = Path(path)
    handler = ICSCalendarHandler(source_path)
    events = tuple(
        UVEventFormatter(event_dict).to_event_data()
        for event_dict in handler.as_dicts()
    )
    return LoadedCalendar(
        source_path=source_path,
        preamble=handler.get_preamble(),
        events=events,
        subject_catalog=build_subject_catalog(events),
    )


def prepare_subject_names(
    loaded_calendar: LoadedCalendar,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> tuple[dict[str, str], frozenset[str]]:
    """Merge stored aliases with newly discovered UV subject names."""

    configured_names = CalendarStateStore(config_path).subject_names()

    subject_names = dict(configured_names)
    for subject_id, original_name in loaded_calendar.subject_catalog.items():
        subject_names.setdefault(subject_id, original_name)
    return subject_names, frozenset(configured_names)


def generate_formatted_calendar(
    loaded_calendar: LoadedCalendar,
    *,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
    subject_names: Mapping[str, str] | None = None,
    persist_subject_names: bool = True,
) -> GenerationResult:
    """Generate an ICS file using the formatter's existing naming behavior."""

    state_store = CalendarStateStore(config_path)
    if subject_names is not None:
        resolved_subject_names = _validated_subject_names(subject_names)
        apply_names = True
        save_subject_names = True
    elif state_store.path.exists() or state_store.legacy_path.exists():
        resolved_subject_names = _validated_subject_names(state_store.subject_names())
        apply_names = True
        save_subject_names = False
    else:
        resolved_subject_names = {}
        apply_names = False
        save_subject_names = True

    edited_events: list[dict] = []
    for event in loaded_calendar.events:
        if event.subject_id not in resolved_subject_names:
            resolved_subject_names[event.subject_id] = event.original_subject

        subject = (
            resolved_subject_names[event.subject_id]
            if apply_names
            else event.original_subject
        )
        opaque = blocks_calendar_time(event.class_type)

        edited_event = {
            "UID": event.uid,
            "SUMMARY": f"{subject} - {event.class_type}",
            "DESCRIPTION": (
                f"({event.subject_id}) - {event.class_type} grupo {event.group}."
            ),
            "CREATED": event.created,
            "LAST_MODIFIED": datetime.now(),
            "DTSTART": event.start,
            "DTEND": event.end,
            "TRANSP": not opaque,
        }
        if event.location:
            edited_event["LOCATION"] = event.location
        edited_events.append(edited_event)

    config_target = Path(config_path)
    config_saved = True
    if save_subject_names and persist_subject_names:
        state_store.save_subject_names(resolved_subject_names)
    elif save_subject_names:
        config_saved = False

    output_target = Path(output_path)
    generator = ICSGenerator(preamble=loaded_calendar.preamble)
    generator.add_events(edited_events).generate_ics(output_target)

    return GenerationResult(
        output_path=_with_ics_suffix(output_target).resolve(),
        config_path=config_target.resolve(),
        event_count=len(edited_events),
        custom_names_applied=apply_names,
        config_saved=config_saved,
    )


def _with_ics_suffix(path: Path) -> Path:
    return path if path.suffix.casefold() == ".ics" else path.with_suffix(".ics")


def _validated_subject_names(subject_names: object) -> dict[str, str]:
    if not isinstance(subject_names, Mapping):
        raise TypeError("Calendar configuration must contain a JSON object")

    validated: dict[str, str] = {}
    for subject_id, subject_name in subject_names.items():
        if not isinstance(subject_id, str):
            raise TypeError("Calendar configuration subject IDs must be strings")
        if not isinstance(subject_name, str) or not subject_name.strip():
            raise ValueError(
                f"Calendar configuration name for {subject_id!r} must be non-empty"
            )
        validated[subject_id] = subject_name.strip()
    return validated
