from utils.logger import LoggerSingleton
from utils.json_manager import JsonMng
from core.ics_formatter import ICSHandler
from utils.file_selector import pick_file

CONFIGFILE = "calendar_config.json"
ICSFILEPATH = "horari_2026_.ics"

def main():
    log.info("Start.")
    
    ics_filepath = pick_file()
    if ics_filepath is None:
        log.info("No file selected")
        return
    
    log.debug(f"Filepath chosen = {ics_filepath}")

    ics = ICSHandler(ics_filepath)
    cal_list = ics.as_list()
    log.debug(f"Found a total of {len(cal_list)} events.")

    i=0
    while i < 1:
        event = cal_list[i]
        log.debug(f"event={event}")
        i += 1
    return


    config_mng.save_dict_to_config(cal_list)

logger_instance = LoggerSingleton()
logger_instance.set_logger_config(level='DEBUG')
logger_instance.set_third_party_loggers_level(level='ERROR')

log = logger_instance.get_logger()

if __name__ == "__main__":
    main()