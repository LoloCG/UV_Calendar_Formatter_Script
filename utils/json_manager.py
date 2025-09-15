import json
from pathlib import Path

from utils.logger import LoggerSingleton
log = LoggerSingleton().get_logger()

class JsonMng:
    def __init__(self, path: Path | str = "config.json"):
        if isinstance(path, Path):
            self.path = path
        elif isinstance(path, str):
            self.path = Path(path)
        else:
            raise TypeError(f"path must be str or Path, got {type(path).__name__}")
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(path={self.path})"
    
    def config_exists(self) -> bool:
        if (self.load_json_config() == {}): return False
        return True

    def save_dict_to_config(self, data, path=None):
        if not path: path = self.path
        log.info(f"Saving data to {path}")

        with open(path, 'w') as json_file:
            json.dump(data, json_file, indent=2)

    def load_json_config(self) -> dict:
        """
        Read and return the JSON config, or {} if the file doesn't exist.
        """
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def json_upsert(self, new_data) -> dict:
        """update or insert, and save the config data."""
        cfg_file = Path(self.path)
        if cfg_file.exists():
            with open(cfg_file, 'r') as file:
                try:
                    config = json.load(file)
                except json.JSONDecodeError:
                    config = {}
        else:
            config = {}

        config.update(new_data)

        with open(cfg_file, 'w') as file:
            json.dump(config, file, indent=4)

        return config
