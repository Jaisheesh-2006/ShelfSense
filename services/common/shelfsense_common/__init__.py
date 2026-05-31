"""Shared library for ShelfSense services: event contracts, zone config, settings, logging."""

from shelfsense_common.config import Settings, get_settings
from shelfsense_common.logging import configure_logging, get_logger

__all__ = ["Settings", "get_settings", "configure_logging", "get_logger"]
__version__ = "0.1.0"
