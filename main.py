from utils.logger import LoggerSingleton
from utils.json_manager import JsonMng
from core.ics_formatter import UVEventFormatter
from utils.ics_utils import ICSCalendarHandler, ICSGenerator
from utils.file_selector import pick_file
import unicodedata

from datetime import datetime

CONFIGFILE = "calendar_config.json"
ICSFILEPATH = "horari_2026_.ics"

def main():
    log.info("Start.")
    
    if True: ics_filepath=ICSFILEPATH # Added for debug to avoid selection of calendar
    else:
        ics_filepath = pick_file()
        if ics_filepath is None:
            log.info("No file selected")
            return
    log.debug(f"Filepath chosen = {ics_filepath}")

    ics = ICSCalendarHandler(ics_filepath)
    cal_list = ics.as_dicts()
    log.debug(f"Found a total of {len(cal_list)} events.")

    config_mng = JsonMng(CONFIGFILE)

    if config_mng.config_exists():
        unique_id = config_mng.load_json_config()
        apply_names = True
    else:
        unique_id = {}
        apply_names=False
    
    log.debug(f"apply_names={apply_names}")

    new_cal_list = []
    for event in cal_list:
        ev = UVEventFormatter(event)

        if ev.subject_id not in unique_id.keys():
            unique_id[ev.subject_id] = ev.subject
        
        if apply_names:
            ev.rename_subjects(unique_id)

        ev_values = ev.get_values()

        raw_class_type = ev_values.get("class_type")

        cls_norm = _norm(raw_class_type)        
        opaque = cls_norm in {"seminario", "tutorias", "laboratorio"}

        # TODO: priority not yet added due to some fault in detecting similarities in string or something... 
        # priority = 6
        # if (cls_norm in {"seminario", "tutorias"}): priority = 3
        # elif cls_norm == "laboratorio": priority = 1

        edited_event = {
            'UID': event['UID'],
            'SUMMARY': f"{ev_values["subject"]} - {raw_class_type}", 
            'DESCRIPTION': f'({ev_values["subject_id"]}) - {raw_class_type} grupo {ev_values["class_group"]}. Location: {event['DESCRIPTION']}', 
            'CREATED': event['CREATED'], 
            'LAST_MODIFIED': datetime.now(), 
            'DTSTART': event['DTSTART'],
            'DTEND': event['DTEND'],
            'TRANSP': False if opaque else True,
            # 'PRIORITY': priority
        }
        new_cal_list.append(edited_event)

    if apply_names == False:
        config_mng.save_dict_to_config(data=unique_id, ensure_ascii=True)

    gen = ICSGenerator()
    log.info(f"Adding events and generating ics file.")
    gen.add_events(new_cal_list).generate_ics()

def _norm(s: str) -> str:
    """strip, collapse spaces, strip accents, casefold"""
    s = (s or "").replace("\u00A0", " ").strip()          # NBSP → space
    s = " ".join(s.split())                                # collapse inner spaces
    s = "".join(c for c in unicodedata.normalize("NFD", s) # remove accents
    if not unicodedata.combining(c))
    return s.casefold()

logger_instance = LoggerSingleton()
logger_instance.set_logger_config(level='DEBUG')
logger_instance.set_third_party_loggers_level(level='ERROR')

log = logger_instance.get_logger()

if __name__ == "__main__":
    main()