"""The machine-specific settings, read from config.json next to this file."""
import json
from dataclasses import dataclass
from pathlib import Path

CONFIG_PATH = Path(__file__).with_name("config.json")
EXAMPLE_NAME = "config.example.json"


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    project_dir: Path
    database: str
    branch: str
    odoo_url: str
    backup_script: Path
    backup_root: Path
    # Outside backup_root on purpose: backup_odoo.bat prunes that one down to
    # its newest few, which must never take the copy made before an overwrite.
    safety_backup_root: Path


def load_config(path=CONFIG_PATH):
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"{path} not found. Copy {EXAMPLE_NAME} to config.json and correct it for this machine, or run install.bat.") from None
    except ValueError as error:
        raise ConfigError(f"{path} is not valid JSON: {error}") from None
    try:
        return Config(
            project_dir=Path(raw["project_dir"]),
            database=raw["database"],
            branch=raw["branch"],
            odoo_url=raw["odoo_url"].rstrip("/"),
            backup_script=Path(raw["backup_script"]),
            backup_root=Path(raw["backup_root"]),
            safety_backup_root=Path(raw["safety_backup_root"]),
        )
    except KeyError as error:
        raise ConfigError(f"{path} is missing {error}.") from None
