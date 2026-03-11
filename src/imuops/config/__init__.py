"""Config helpers."""

from __future__ import annotations

import tomllib
from importlib import resources
from typing import Any


def load_defaults() -> dict[str, Any]:
    with resources.files("imuops.config").joinpath("defaults.toml").open("rb") as handle:
        return tomllib.load(handle)

