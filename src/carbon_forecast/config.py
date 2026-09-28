"""Paths and settings loading."""

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = ROOT / "sql"
REPORTS_DIR = ROOT / "reports"
SETTINGS_PATH = ROOT / "config" / "settings.yaml"


def load_settings(path: Path = SETTINGS_PATH) -> dict[str, Any]:
    with open(path) as f:
        return yaml.safe_load(f)


def resolve(path: str | Path) -> Path:
    """Resolve a settings path relative to the repo root."""
    p = Path(path)
    return p if p.is_absolute() else ROOT / p
