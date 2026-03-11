"""Adapter protocol for supported datasets."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from imuops.session import SessionBundle


class BaseAdapter(ABC):
    name: str

    @classmethod
    @abstractmethod
    def detect(cls, src_path: Path) -> bool:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def ingest(cls, src_path: Path, out_dir: Path, config: dict[str, Any]) -> SessionBundle:
        raise NotImplementedError

