# Last update: 16/9/25
from datetime import datetime
from pathlib import Path
from ics import Calendar, Event

class ICSHandler:
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
