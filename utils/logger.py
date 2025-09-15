import logging
import logging.config
from threading import Lock

logging.getLogger("matplotlib").setLevel(logging.ERROR)
logging.getLogger("matplotlib.pyplot").setLevel(logging.ERROR)
logging.getLogger("PIL.PngImagePlugin").setLevel(logging.ERROR)

class LoggerSingleton:
    _instance = None
    _lock = Lock()  # for thread-safety

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:  # double-checked locking
                    cls._instance = super(LoggerSingleton, cls).__new__(cls)
        return cls._instance
		
    def __init__(self, main_log_level='INFO', disable_third_party=False):
        if not hasattr(self, '_initialized'):
            self._initialized = True
            self.set_logger_config(main_log_level, disable_third_party)

            if disable_third_party == False:
                self.set_third_party_loggers_level(exception_level=main_log_level)

    def set_logger_config(self, level='INFO', custom_config=None, disable_third_party=False):
        
        if custom_config:
            logging.config.dictConfig(custom_config)
        else:
            logging_config = {
                'version': 1,
                'disable_existing_loggers': disable_third_party,
                'formatters': {
                    'basic': {
                        'format': "{asctime} - {levelname} - {filename} - {funcName}: {message}",
                        'style': "{",
                        'datefmt': "%H:%M:%S",
                    }
                },
                'handlers': {
                    'stdout': {
                        'class': 'logging.StreamHandler',
                        'formatter': 'basic',
                        'stream': 'ext://sys.stdout',
                    }
                },
                'loggers': {
                    'root': {
                        'level': level,
                        'handlers': ['stdout'],
                    }
                },
            }

        logging.config.dictConfig(logging_config)

    def set_third_party_loggers_level(self, level='ERROR', exceptions=['core.logger', __name__], exception_level='DEBUG'):
        for name, logger in logging.root.manager.loggerDict.items():
            if isinstance(logger, logging.Logger):
                if name in exceptions:
                    logging.getLogger(name).setLevel(getattr(logging, exception_level))
                else:
                    logging.getLogger(name).setLevel(getattr(logging, level))

    def get_logger(self, logger_name=__name__):
        return logging.getLogger(logger_name)

# Example of usage
# logger_instance = LoggerSingleton(level='DEBUG')
# logger = logger_instance.get_logger()
# logger.info('This is an info message')

# import logging.config