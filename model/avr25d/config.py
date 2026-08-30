"""Configuration loader for ``config.yaml`` (NFR-7).

Every tunable in the system lives in one YAML file with its units and its
reason.  This module is the only thing that reads it, and it exposes the tree
as attribute-addressable ``Config`` nodes so call sites read like
``cfg.perception.geometric.ground_tol`` rather than a chain of dict lookups.

Missing keys raise ``AttributeError`` rather than returning ``None``: a typo in
a threshold name should fail loudly at startup, not silently disable a hazard
check.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.yaml")


class Config:
    """Attribute-addressable read-only view over a nested mapping."""

    __slots__ = ("_data",)

    def __init__(self, data: dict[str, Any]):
        object.__setattr__(self, "_data", data)

    def __getattr__(self, name: str) -> Any:
        try:
            value = self._data[name]
        except KeyError:
            raise AttributeError(
                f"no configuration key {name!r} (available: "
                f"{', '.join(sorted(self._data))})"
            ) from None
        return Config(value) if isinstance(value, dict) else value

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("Config is read-only; edit config.yaml instead")

    def __getitem__(self, name: str) -> Any:
        return getattr(self, name)

    def __contains__(self, name: str) -> bool:
        return name in self._data

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def get(self, name: str, default: Any = None) -> Any:
        return getattr(self, name) if name in self._data else default

    def to_dict(self) -> dict[str, Any]:
        """Deep copy as plain containers — for ``results.json`` provenance."""
        import copy

        return copy.deepcopy(self._data)

    def __repr__(self) -> str:
        return f"Config({', '.join(sorted(self._data))})"


def load_config(path: str | Path | None = None) -> Config:
    """Load ``config.yaml``.  ``path=None`` loads the packaged default."""
    p = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    with p.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{p} did not parse to a mapping")
    return Config(data)
