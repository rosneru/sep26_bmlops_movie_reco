"""Select the configured training implementation."""

from importlib import import_module

from src import config

implementation = import_module(f".{config.MODEL_TYPE}", package=__name__)

__all__ = ["implementation"]
