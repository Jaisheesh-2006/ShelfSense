"""Pluggable store registry (ADR-0028).

Every store is described by **one module** in this package that exposes a module-level
``STORE_CONFIG: StoreConfig`` (see `st1008.py`, `st1009.py`). This package **auto-discovers** them
at import, so onboarding a new store is a drop-in:

    1. add `stores/<store_id>.py` with `STORE_CONFIG = StoreConfig(...)` (copy an existing one),
    2. put its clips under `CCTV_DIR/<clips_dir>/`,
    3. (optional) list it in `STORES` so the dashboard switcher shows it.

Nothing else changes — the detector loop, analytics, and the API all read this registry, so they
pick the new store up automatically. See `README.md` for the full recipe + field reference.

The registry is a pure function of the modules present (deterministic, sorted by `store_id`), with
no filesystem or env dependency, so it is safe to import anywhere (including unit tests).
"""

from __future__ import annotations

import importlib
import pkgutil

from shelfsense_common.contracts.zones import StoreConfig

#: The store whose POS/conversion the headline metric uses, and the back-compat default for any
#: store-scoped helper called without an explicit id.
DEFAULT_STORE_ID = "ST1008"


def _discover() -> dict[str, StoreConfig]:
    """Import every non-private sibling module and collect its `STORE_CONFIG`, keyed by store_id."""
    found: dict[str, StoreConfig] = {}
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{__name__}.{info.name}")
        config = getattr(module, "STORE_CONFIG", None)
        if isinstance(config, StoreConfig):
            found[config.store_id] = config
    return found


_STORES: dict[str, StoreConfig] = _discover()


def all_stores() -> list[StoreConfig]:
    """Every configured store, ordered by `store_id` (deterministic)."""
    return [_STORES[k] for k in sorted(_STORES)]


def store_ids() -> list[str]:
    """The configured store ids, sorted."""
    return sorted(_STORES)


def get_store(store_id: str) -> StoreConfig | None:
    """The config for one store, or None if it isn't registered."""
    return _STORES.get(store_id)
