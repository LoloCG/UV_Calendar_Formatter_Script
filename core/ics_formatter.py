from utils.ics_utils import ICSCalendarHandler, ICSHelpers
from ics import Calendar, Event
import re

from utils.logger import LoggerSingleton
log = LoggerSingleton().get_logger()

class UVEventFormatter:
    # _GROUP_TYPE_RE = re.compile(r'Grupo\s+(.+?)\s+([A-Za-z0-9-]+)\s*$', re.IGNORECASE)
    _GROUP_TYPE_RE = re.compile(r'Grupo\s+(?P<type>.+?)\s+(?P<tag>[A-Za-z0-9-]+)\s*$',re.IGNORECASE)
    _CODE_PREFIX_RE = re.compile(r'^\s*(?P<code>\d{4,6})\s*[-–—]\s*')        # 5-digit code + hyphen/en dash/em dash
    _GRUPO_TRAILER_RE = re.compile(r'\s+Grupo\s+.+$', re.IGNORECASE)       # strip trailing "Grupo ..."
    # 2026 UV export: "34082 - Subject(TEORÍA (34082))"
    _NEW_SUMMARY_RE = re.compile(
        r'^(?P<subject>.+?)\s*\((?P<type>[^()]+?)\s+\(\d{4,6}\)\)\s*$'
    )
    # In the 2026 export, the group moved to DESCRIPTION: "DG-T - Grupo Teoría".
    _NEW_DESCRIPTION_RE = re.compile(
        r'^(?P<tag>[A-Za-z0-9-]+)\s*-\s*Grupo\s+(?P<type>.+?)\s*$',
        re.IGNORECASE,
    )

    def __init__(self, event_dict:dict):
        self.event = event_dict

        self.subject_id: str    = ""
        self.subject: str       = ""
        self.group: str         = ""
        self.class_type: str    = ""

        self._extract_subject_data()

    def _extract_subject_data(self):
        summary = (self.event.get("SUMMARY") or "").strip()

        # Subject ID (from leading code)
        m_code = self._CODE_PREFIX_RE.match(summary)
        if m_code:
            self.subject_id = m_code.group("code")
            rest = summary[m_code.end():].strip()   # text after the code+dash
        else:
            self.subject_id = ""
            rest = summary

        # Maintained for backwards compatibility. For pre-2026 .ics from UV calendars
        # These contained subject, type and group in summary field. see #3
        m_group = self._GROUP_TYPE_RE.search(summary)
        if m_group:
            self.subject = self._GRUPO_TRAILER_RE.sub("", rest).strip()
            self.class_type = m_group.group("type")
            self.group = m_group.group("tag").upper()
            return self

        # The 2026 export puts the type in SUMMARY and group in DESCRIPTION.
        m_summary = self._NEW_SUMMARY_RE.match(rest)
        if m_summary:
            self.subject = m_summary.group("subject").strip()
            self.class_type = m_summary.group("type").strip()
        else:
            # Keep a readable title if a future export uses another layout.
            self.subject = rest

        description = (self.event.get("DESCRIPTION") or "").strip()
        m_description = self._NEW_DESCRIPTION_RE.match(description)
        if m_description:
            self.group = m_description.group("tag").upper()
            if not self.class_type:
                self.class_type = m_description.group("type").strip()

        return self

    def rename_subjects(self, config:dict|None = None, name:str|None=None):
        '''
        Requires dict parameter consisting of subject id (5 digits), and
        the desired name. 
        '''
        if config is None and name is None:
            return self
        
        if self.subject_id in config.keys():
            new_name = config[self.subject_id]

        elif name is not None:
            new_name = name

        self.subject = new_name
        
        return self
    
    def get_values(self):
        return {
            "subject": self.subject,
            "subject_id":self.subject_id,
            "class_type":self.class_type,
            "class_group":self.group
        }
