"""Select the sole supported implementation; no plugin framework is needed."""

from . import two_tower as implementation

__all__ = ['implementation']
