"""Dataset adapter registry."""

from __future__ import annotations

from imuops.adapters.base import BaseAdapter
from imuops.adapters.oxiod import OxIODAdapter
from imuops.adapters.ronin import RoNINAdapter
from imuops.adapters.tabular import TabularAdapter
from imuops.adapters.wisdm import WISDMAdapter

ADAPTERS: dict[str, type[BaseAdapter]] = {
    OxIODAdapter.name: OxIODAdapter,
    RoNINAdapter.name: RoNINAdapter,
    TabularAdapter.name: TabularAdapter,
    WISDMAdapter.name: WISDMAdapter,
}


def get_adapter(name: str) -> type[BaseAdapter]:
    normalized = name.strip().lower()
    if normalized not in ADAPTERS:
        raise KeyError(f"Unknown adapter '{name}'. Available: {', '.join(sorted(ADAPTERS))}")
    return ADAPTERS[normalized]


__all__ = ["ADAPTERS", "BaseAdapter", "get_adapter"]
