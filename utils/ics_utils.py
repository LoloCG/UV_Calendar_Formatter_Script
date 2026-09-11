from datetime import datetime
from pathlib import Path
from ics import Calendar, Event

from core.models import CalendarSourceMetadata, RawCalendarEvent


class ICSCalendarHandler:
    def __init__(self, ics_filepath):
        self.filepath = None
        self._source_text = ""
        self._has_utf8_bom = False
        self._raw_events: tuple[RawCalendarEvent, ...] | None = None
        self.calendar = self._open_file(ics_filepath)

    def _open_file(self, path:str|Path):
        ics_file_path = Path(path) if isinstance(path, str) else path 

        if not ics_file_path.exists():
            msg = f"Calendar file not found: {ics_file_path.resolve()}"
            raise FileNotFoundError(msg)
        self.filepath = ics_file_path

        source_bytes = ics_file_path.read_bytes()
        self._has_utf8_bom = source_bytes.startswith(b"\xef\xbb\xbf")
        # Match text-mode universal-newline behavior while reading the file once.
        self._source_text = (
            source_bytes.decode("utf-8-sig")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
        )
        return Calendar(self._source_text)

    def as_raw_events(self) -> tuple[RawCalendarEvent, ...]:
        """Return typed source values before any UV-specific interpretation."""

        if self._raw_events is None:
            events = []
            for event in self.calendar.events:
                events.append(
                    RawCalendarEvent(
                        uid=ICSHelpers._optional_stringify(
                            getattr(event, "uid", None)
                        ),
                        summary=ICSHelpers._optional_stringify(
                            getattr(event, "name", None)
                        ),
                        description=ICSHelpers._optional_stringify(
                            getattr(event, "description", None), sep=" "
                        ),
                        classification=ICSHelpers._optional_stringify(
                            getattr(event, "classification", None)
                        ),
                        categories=ICSHelpers._optional_stringify(
                            getattr(event, "categories", None), sep=", "
                        ),
                        created=ICSHelpers._to_datetime(
                            getattr(event, "created", None)
                        ),
                        last_modified=ICSHelpers._to_datetime(
                            getattr(event, "last_modified", None)
                        ),
                        start=ICSHelpers._to_datetime(getattr(event, "begin", None)),
                        end=ICSHelpers._to_datetime(getattr(event, "end", None)),
                        location=ICSHelpers._optional_stringify(
                            getattr(event, "location", None)
                        ),
                    )
                )
            self._raw_events = tuple(events)
        return self._raw_events

    def as_dicts(self)-> list:
        """Compatibility projection for callers that still consume dictionaries."""

        return [
            {
                "UID": event.uid,
                "SUMMARY": event.summary or "",
                "DESCRIPTION": event.description or "",
                "CLASSIFICATION": event.classification,
                "CATEGORIES": event.categories or "",
                "CREATED": event.created,
                "LAST_MODIFIED": event.last_modified,
                "DTSTART": event.start,
                "DTEND": event.end,
                "LOCATION": event.location,
            }
            for event in self.as_raw_events()
        ]

    def source_metadata(self) -> CalendarSourceMetadata:
        """Return source metadata useful for future format-adapter scoring."""

        preamble = self.get_preamble()
        return CalendarSourceMetadata(
            prodid=ICSHelpers._property_value(preamble, "PRODID"),
            calendar_name=ICSHelpers._property_value(preamble, "X-WR-CALNAME"),
            has_utf8_bom=self._has_utf8_bom,
        )

    def get_preamble(self) -> str:
        """
        Return the original VCALENDAR preamble (everything before first VEVENT).
        This keeps source metadata/timezone definitions in regenerated files.
        """
        marker = "BEGIN:VEVENT"
        idx = self._source_text.find(marker)
        return self._source_text[:idx] if idx != -1 else ""

class ICSGenerator:
    def __init__(self, preamble: str | None = None):
        self.calendar = Calendar()
        self.preamble = preamble or ""
    
    def add_events(self, events:list):
        cal = self.calendar
        for row in events:
            ev = Event()

            if 'UID' in row:            ev.uid = str(row['UID'])
            if 'SUMMARY' in row:        ev.name = row['SUMMARY']
            if 'DESCRIPTION' in row:    ev.description = row['DESCRIPTION']
            if 'LOCATION' in row:       ev.location = row['LOCATION']
            if 'DTSTART' in row:        ev.begin = row['DTSTART']
            if 'DTEND' in row:          ev.end = row['DTEND']
            if 'CREATED' in row:        ev.created = row['CREATED']
            if 'LAST_MODIFIED' in row:  ev.last_modified = row['LAST_MODIFIED']
            if 'STATUS' in row:         ev.status = row['STATUS']
            if 'URL' in row:            ev.url = row['URL']
            if 'TRANSP' in row:         ev.transparent = row['TRANSP']
            # Priority is missing. Requires use of extras
            
            cal.events.add(ev)

        return self

    def get_cal(self)-> Calendar:
        return self.calendar

    @staticmethod
    def _extract_events_block(calendar_text: str) -> str:
        start = calendar_text.find("BEGIN:VEVENT")
        if start == -1:
            return ""
        end = calendar_text.rfind("END:VEVENT")
        if end == -1:
            return ""
        end += len("END:VEVENT")
        events_block = calendar_text[start:end]
        if not events_block.endswith(("\r\n", "\n", "\r")):
            events_block += "\r\n"
        return events_block

    def generate_ics(self, filename: str | Path = "new_calendar") -> Path:
        calendar_text = self.calendar.serialize()

        if self.preamble:
            output = self.preamble
            if not output.endswith(("\r\n", "\n", "\r")):
                output += "\r\n"
            output += self._extract_events_block(calendar_text)
            output += "END:VCALENDAR\r\n"
        else:
            output = calendar_text

        output_path = Path(filename)
        if output_path.suffix.casefold() != ".ics":
            output_path = output_path.with_suffix(".ics")

        # newline='' avoids Windows CRLF expansion that causes blank lines.
        with open(output_path, "w", encoding="utf-8", newline="") as f:
            f.write(output)
        return output_path
    
class ICSHelpers:
    @staticmethod
    def _to_datetime(value) -> datetime | None:
        """
        Return a datetime if possible; otherwise None.
        Handles ics.py Arrow-like objects, datetime, and ISO-ish strings.
        """
        if value is None:
            return None
        # ics.py uses Arrow; its fields expose `.datetime`
        if hasattr(value, "datetime"):
            try:
                dt = value.datetime
                return dt if isinstance(dt, datetime) else None
            except Exception:
                return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            s = value.strip()
            try:
                # Handle trailing 'Z' and offset forms
                return datetime.fromisoformat(s.replace("Z", "+00:00"))
            except Exception:
                return None
        return None

    @staticmethod
    def _stringify(value, sep: str = ", ") -> str:
        """Convert strings/iterables/None to a single string."""
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        try:
            return sep.join(str(x) for x in value)
        except TypeError:
            # Not iterable; fall back to plain str
            return str(value)

    @staticmethod
    def _optional_stringify(value, sep: str = ", ") -> str | None:
        """Stringify a present value without collapsing absence to empty text."""

        if value is None:
            return None
        return ICSHelpers._stringify(value, sep=sep)

    @staticmethod
    def _property_value(calendar_text: str, property_name: str) -> str | None:
        """Read one unfolded top-level calendar property from a preamble."""

        unfolded: list[str] = []
        for line in calendar_text.splitlines():
            if line.startswith((" ", "\t")) and unfolded:
                unfolded[-1] += line[1:]
            else:
                unfolded.append(line)
        expected = property_name.casefold()
        for line in unfolded:
            header, separator, value = line.partition(":")
            if separator and header.partition(";")[0].casefold() == expected:
                return ICSHelpers.ics_unescape(value)
        return None

    @staticmethod
    def ics_unescape(s: str) -> str:
        """Unescape RFC5545 sequences in a property value."""
        if not isinstance(s, str):
            return s
        # Order matters: unescape backslash first
        s = s.replace("\\\\", "\\")
        s = s.replace("\\,", ",").replace("\\;", ";")
        s = s.replace("\\n", "\n").replace("\\N", "\n")
        return s
