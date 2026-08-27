from pathlib import Path

import yaml


def load_settings() -> dict:
    config_path = Path(__file__).resolve().parent.parent / 'config' / 'settings.yaml'
    with config_path.open(encoding='utf-8') as f:
        return yaml.safe_load(f)
