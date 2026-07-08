"""Binary sensors for ShowMo integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import build_device_info
from .motion import ShowMoMotionCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ShowMo binary sensors from a config entry."""
    runtime_data = hass.data[DOMAIN][entry.entry_id]
    motion: ShowMoMotionCoordinator = runtime_data["motion"]
    if not await motion.async_initialize():
        return

    async_add_entities([ShowMoMotionBinarySensor(entry, motion)])


class ShowMoMotionBinarySensor(BinarySensorEntity):
    """Expose ONVIF motion alarms as a binary sensor."""

    _attr_device_class = BinarySensorDeviceClass.MOTION
    _attr_has_entity_name = True
    _attr_name = "Motion"

    def __init__(self, entry: ConfigEntry, motion: ShowMoMotionCoordinator) -> None:
        """Initialize the binary sensor."""
        self._entry = entry
        self._motion = motion
        serial = entry.data.get("serial") or entry.entry_id
        self._attr_unique_id = f"{serial}_motion"
        self._attr_device_info = build_device_info(entry)
        self._remove_listener = None

    @property
    def available(self) -> bool:
        """Return whether the motion stream is available."""
        return self._motion.available

    @property
    def is_on(self) -> bool:
        """Return the latest motion state."""
        return self._motion.is_on

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Expose the last motion topic and receive time for debugging."""
        attributes: dict[str, str] = {}
        if self._motion.last_topic:
            attributes["last_topic"] = self._motion.last_topic
        if self._motion.last_motion_at:
            attributes["last_motion_at"] = self._motion.last_motion_at.isoformat()
        return attributes or None

    async def async_added_to_hass(self) -> None:
        """Register listeners and start ONVIF motion polling."""
        self._remove_listener = self._motion.async_add_listener(self._handle_update)
        await self._motion.async_start()

    async def async_will_remove_from_hass(self) -> None:
        """Remove listeners when the entity is removed."""
        if self._remove_listener is not None:
            self._remove_listener()
            self._remove_listener = None

    @callback
    def _handle_update(self) -> None:
        """Write the updated entity state to Home Assistant."""
        self.async_write_ha_state()
