from pathlib import Path
from typing import Any

import yaml


def load_config(path: str) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as stream:
        config = yaml.safe_load(stream) or {}
    config.setdefault("server", {})
    config["server"].setdefault("host", "0.0.0.0")
    config["server"].setdefault("port", 8080)
    config["server"].setdefault("max_file_size_mb", 50)
    config["server"].setdefault("storage_dir", "./data")
    config["server"].setdefault("delete_after_submit", False)
    config.setdefault("printers", {})
    config.setdefault("rules", [])
    config.setdefault("default_printer", next(iter(config["printers"]), ""))
    return config
