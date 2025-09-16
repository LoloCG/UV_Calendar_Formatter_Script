from utils.logger import LoggerSingleton
from utils.json_manager import JsonMng
from core.ics_formatter import UVEventFormatter
from utils.ics_utils import ICSCalendarHandler
from utils.file_selector import pick_file

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

        class_type = ev_values.get("class_type")
        priority = 6
        if (class_type in {"Seminario", "Tutorías"}): priority = 3
        elif class_type == "Laboratorio": priority = 1

        edited_event = {
            'UID': event['UID'],
            'SUMMARY': f"{ev_values["subject"]} - {class_type}", 
            'DESCRIPTION': f'({ev_values["subject_id"]}) - {class_type}, {ev_values["class_group"]}. Location: {event['DESCRIPTION']}', 
            'CREATED': event['CREATED'], 
            'LAST_MODIFIED': datetime.now(), 
            'DTSTART': event['DTSTART'],
            'DTEND': event['DTEND'],
            'TRANSP': "OPAQUE" if class_type in {"Seminario", "Tutorías", "Laboratorio"} else "TRANSPARENT",
            'PRIORITY': priority
        }
        new_cal_list.append(edited_event)

    if apply_names == False:
        config_mng.save_dict_to_config(data=unique_id, ensure_ascii=True)


    # TODO
    for event in new_cal_list:
        log.info(event)
    # formatter_event_loop([cal_list[0]], config=None)

logger_instance = LoggerSingleton()
logger_instance.set_logger_config(level='DEBUG')
logger_instance.set_third_party_loggers_level(level='ERROR')

log = logger_instance.get_logger()

if __name__ == "__main__":
    main()