from datetime import datetime
from pathlib import Path
from ics import Calendar, Event
try:
    from ics.grammar.parse import ContentLine
except Exception:
    ContentLine = None

# Last update: 16/9/25

class ICSCalendarHandler:
    def __init__(self, ics_filepath):
        self.filepath = None  
        self.calendar = self._open_file(ics_filepath)

    def _open_file(self, path:str|Path):
        ics_file_path = Path(path) if isinstance(path, str) else path 

        # log.info(f"Searching for calendar file '{ics_file_path}'")
        if not ics_file_path.exists():
            msg = f"Calendar file not found: {ics_file_path.resolve()}"
            # log.error(msg)
            raise FileNotFoundError(msg)
        self.filepath = ics_file_path

        with open(ics_file_path, 'r',encoding='utf-8') as f:
            return Calendar(f.read())

    def as_dicts(self)-> list:
        calendar = self.calendar
        events = []
        for event in calendar.events:
            # categories and descriptions may contain multiple lines, 
            # thus the type is found as a list or touple of values.
            categories_str  = ICSHelpers._stringify(getattr(event, "categories", None), sep=", ")
            description_str = ICSHelpers._stringify(getattr(event, "description", None), sep=" ")
            
            events.append({
                'UID':getattr(event, 'uid', None),
                'SUMMARY': getattr(event, 'name', '') or '',
                'DESCRIPTION': description_str,
                'CLASSIFICATION': getattr(event, 'classification', None),
                'CATEGORIES': categories_str,
                'CREATED': ICSHelpers._to_datetime(getattr(event, 'created', None)),
                'LAST_MODIFIED': ICSHelpers._to_datetime(getattr(event, 'last_modified', None)),
                'DTSTART': ICSHelpers._to_datetime(getattr(event, 'begin', None)),
                'DTEND':   ICSHelpers._to_datetime(getattr(event, 'end', None)),
                'LOCATION': getattr(event, 'location', None)
            })
        
        return events

class ICSGenerator:
    def __init__(self):
        self.calendar = Calendar()
    
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
    
    def generate_ics(self, filename:str="new_calendar"): # TODO: add: filepath:str|Path|None=None,
        with open(f'{filename}.ics', 'w', encoding='utf-8') as f:
            f.writelines(self.calendar)
    
    # TODO:
    def _add_extra(ev: Event, name: str, value: str, params: dict[str, str] | None = None) -> None:
        if value is None:
            return
        if ContentLine is not None:
            ev.extra.append(ContentLine(name=name, params=(params or {}), value=str(value)))
        else:
            # Fallback: flatten params manually (simple; sufficient for most keys)
            param_str = "".join(f";{k}={v}" for k, v in (params or {}).items())
            ev.extra.append(f"{name}{param_str}:{value}")

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
    def ics_unescape(s: str) -> str:
        """Unescape RFC5545 sequences in a property value."""
        if not isinstance(s, str):
            return s
        # Order matters: unescape backslash first
        s = s.replace("\\\\", "\\")
        s = s.replace("\\,", ",").replace("\\;", ";")
        s = s.replace("\\n", "\n").replace("\\N", "\n")
        return s