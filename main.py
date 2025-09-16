from utils.logger import LoggerSingleton
from utils.json_manager import JsonMng
from core.ics_formatter import UVEventFormatter
from utils.ics_utils import ICSCalendarHandler
from utils.file_selector import pick_file

CONFIGFILE = "calendar_config.json"
ICSFILEPATH = "horari_2026_.ics"

def formatter_event_loop(event_list:list, config:str|None):

    unique_id = {}

    for event in event_list:
        # log.debug(f"event={event}")
        
        values = UVEventFormatter(event).extract_subject().get_values()

        if values["subject_id"] not in unique_id.keys():
            unique_id[values["subject_id"]] = values["subject"]

    config_mng = JsonMng(CONFIGFILE)
    config_mng.save_dict_to_config(data=unique_id,ensure_ascii=False)

    # if not config_mng.config_exists():
    #     msg = "No config file found."

    return

def main():
    log.info("Start.")
    
    if True: ics_filepath=ICSFILEPATH
    else:
        ics_filepath = pick_file()
        if ics_filepath is None:
            log.info("No file selected")
            return
    
    log.debug(f"Filepath chosen = {ics_filepath}")

    ics = ICSCalendarHandler(ics_filepath)
    cal_list = ics.as_dicts()
    log.debug(f"Found a total of {len(cal_list)} events.")

    formatter_event_loop(cal_list, config=None)
    # formatter_event_loop([cal_list[0]], config=None)

logger_instance = LoggerSingleton()
logger_instance.set_logger_config(level='DEBUG')
logger_instance.set_third_party_loggers_level(level='ERROR')

log = logger_instance.get_logger()

if __name__ == "__main__":
    main()