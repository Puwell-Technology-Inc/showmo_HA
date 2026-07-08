"""Shared entity helpers for the ShowMo integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, MANUFACTURER, MODEL


def build_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Build the DeviceInfo shared by every ShowMo entity of a config entry.

    All platforms must register identical device metadata; otherwise the last
    entity to load overwrites the device page. The discovered manufacturer,
    model and firmware from ``entry.data`` are preferred, falling back to the
    packaged defaults.
    """
    serial = entry.data.get("serial")
    return DeviceInfo(
        identifiers={(DOMAIN, serial or entry.entry_id)},
        name=entry.title,
        manufacturer=entry.data.get("manufacturer") or MANUFACTURER,
        model=entry.data.get("model") or MODEL,
        sw_version=entry.data.get("firmware"),
        serial_number=serial,
    )
