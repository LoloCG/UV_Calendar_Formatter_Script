from utils.logger import LoggerSingleton
from utils.json_manager import JsonMng
from core.ics_formatter import UVEventFormatter
from utils.ics_utils import ICSCalendarHandler
from utils.file_selector import pick_file

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
        
    if apply_names == False:
        config_mng.save_dict_to_config(data=unique_id, ensure_ascii=True)


    # formatter_event_loop([cal_list[0]], config=None)

logger_instance = LoggerSingleton()
logger_instance.set_logger_config(level='DEBUG')
logger_instance.set_third_party_loggers_level(level='ERROR')

log = logger_instance.get_logger()

if __name__ == "__main__":
    main()