from utils.logger import LoggerSingleton
from utils.json_manager import JsonMng
from core.ics_formatter import open_ics_file

CONFIGFILE = "calendar_config.json"
ICSFILEPATH = "horari_2026_.ics"

def main():
    log.info("Start.")

    config_mng = JsonMng(CONFIGFILE)
    # if not config_mng.config_exists():
    #     msg = "No config file found."
    #     log.error(msg)
    #     raise FileNotFoundError(msg)

    cal_list = open_ics_file(path=ICSFILEPATH, as_list=True)
    log.debug(f"Found a total of {len(cal_list)} events.")

    i=0
    while i < 5:
        event = cal_list[i]
        log.debug(event)
        i += 1

    config_mng.save_dict_to_config(cal_list)

logger_instance = LoggerSingleton()
logger_instance.set_logger_config(level='DEBUG')
logger_instance.set_third_party_loggers_level(level='ERROR')

log = logger_instance.get_logger()

if __name__ == "__main__":
    main()