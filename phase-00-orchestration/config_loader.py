"""
config_loader.py — Phase 00: Orchestration
--------------------------------------------
Loads and validates the pipeline configuration from
phase-00-orchestration/config/pipeline_config.yaml.

Raises clear, descriptive errors if required keys are missing,
so misconfiguration is caught at startup rather than mid-run.
"""

from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONFIG_PATH = Path(__file__).parent / "config" / "pipeline_config.yaml"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_config() -> dict[str, Any]:
    """
    Load and validate pipeline_config.yaml.

    Returns:
        dict: Fully validated configuration dictionary.

    Raises:
        FileNotFoundError: If the config file does not exist.
        ValueError:        If required keys are absent.
    """
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Pipeline config not found at: {CONFIG_PATH}\n"
            "Copy pipeline_config.yaml.example and fill in your values."
        )

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if not isinstance(config, dict):
        raise ValueError("pipeline_config.yaml must be a YAML mapping (key: value pairs).")

    _validate(config)
    return config


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

# Keys that must be present (dot-notation for nested paths)
_REQUIRED_KEYS = [
    "apps",
    "apps.ios_app_id",
    "apps.android_package_name",
    "regions",
    "llm.provider",
    "llm.api_key_env_var",
    "scheduling.weekly_day",
    "scheduling.weekly_hour_utc",
    "data_root",
]


def _validate(config: dict) -> None:
    """Validate that all required keys exist in the config."""
    missing = []
    for key_path in _REQUIRED_KEYS:
        if not _has_key(config, key_path):
            missing.append(key_path)

    if missing:
        raise ValueError(
            "Pipeline config is missing required keys:\n  - "
            + "\n  - ".join(missing)
            + f"\n\nCheck: {CONFIG_PATH}"
        )


def _has_key(config: dict, key_path: str) -> bool:
    """Traverse a dot-separated key path in a nested dict."""
    parts = key_path.split(".")
    node = config
    for part in parts:
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True
