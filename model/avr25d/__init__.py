"""AVR-25D — Adaptive Variable-Resolution 2.5D LiDAR Mapping.

This package holds the perception, synthetic-scene and benchmarking half of the
system (see ``docs/WORK_DISTRIBUTION.md`` §4.1).  The grid engine (``core/``),
the wire protocol and the server (``server/``) live alongside it and are owned
separately; nothing here imports them.
"""

from avr25d.config import Config, load_config

__all__ = ["Config", "load_config"]
__version__ = "0.1.0"
