"""Camera platform for ShowMo integration."""

from __future__ import annotations

import asyncio
import logging

import voluptuous as vol

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import build_rtsp_url_with_credentials
from .const import (
    ATTR_CONTINUOUS_DURATION,
    ATTR_MOVE_MODE,
    ATTR_PAN,
    ATTR_PRESET,
    ATTR_TILT,
    ATTR_ZOOM,
    DEFAULT_NAME,
    DOMAIN,
    MANUFACTURER,
    MODEL,
    PTZ_MOVE_CONTINUOUS,
    PTZ_MOVE_GOTO_HOME,
    PTZ_MOVE_GOTO_PRESET,
    PTZ_MOVE_MODES,
    PTZ_MOVE_STOP,
    SERVICE_PTZ,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ShowMo camera from a config entry."""
    async_add_entities([ShowMoCamera(hass, entry)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_PTZ,
        {
            vol.Required(ATTR_MOVE_MODE, default=PTZ_MOVE_CONTINUOUS): vol.In(
                PTZ_MOVE_MODES
            ),
            vol.Optional(ATTR_PAN, default=0.0): vol.All(
                vol.Coerce(float), vol.Range(min=-1.0, max=1.0)
            ),
            vol.Optional(ATTR_TILT, default=0.0): vol.All(
                vol.Coerce(float), vol.Range(min=-1.0, max=1.0)
            ),
            vol.Optional(ATTR_ZOOM, default=0.0): vol.All(
                vol.Coerce(float), vol.Range(min=-1.0, max=1.0)
            ),
            vol.Optional(ATTR_PRESET, default=""): cv.string,
            vol.Optional(ATTR_CONTINUOUS_DURATION, default=0.5): vol.All(
                vol.Coerce(float), vol.Range(min=0.0, max=5.0)
            ),
        },
        "async_perform_ptz",
    )


class ShowMoCamera(Camera):
    """ShowMo camera entity."""

    _attr_has_entity_name = True
    _attr_supported_features = CameraEntityFeature.STREAM
    _attr_use_stream_for_stills = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the camera."""
        super().__init__()

        self._entry = entry
        runtime_data = hass.data[DOMAIN][entry.entry_id]
        self._attr_unique_id = entry.data.get("serial") or entry.entry_id

        # Entity name
        name = entry.data.get(CONF_NAME) or DEFAULT_NAME
        self._attr_name = name if name != DEFAULT_NAME else None

        # Build stream URL with credentials
        host = entry.data["host"]
        port = entry.data["port"]
        path = entry.data["path"]
        username = entry.data[CONF_USERNAME]
        password = entry.data[CONF_PASSWORD]

        self._stream_url = build_rtsp_url_with_credentials(
            host, port, path, username, password
        )
        self._api = runtime_data["api"]

        # Device info
        serial = entry.data.get("serial")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial or entry.entry_id)},
            name=entry.title,
            manufacturer=MANUFACTURER,
            model=MODEL,
            serial_number=serial,
        )

    async def stream_source(self) -> str | None:
        """Return the stream source URL."""
        return self._stream_url

    async def async_perform_ptz(
        self,
        move_mode: str,
        pan: float = 0.0,
        tilt: float = 0.0,
        zoom: float = 0.0,
        preset: str = "",
        continuous_duration: float = 0.5,
    ) -> None:
        """Handle the showmo.ptz service call.

        The camera may advertise PTZ while returning ``ActionNotSupported`` for
        the actual move (fixed-lens models do this), so failures are logged
        rather than raised.
        """
        if move_mode == PTZ_MOVE_STOP:
            await self._api.async_ptz_stop()
            return

        if move_mode == PTZ_MOVE_GOTO_HOME:
            if not await self._api.async_ptz_goto_home():
                _LOGGER.warning("PTZ home not supported by %s", self._entry.title)
            return

        if move_mode == PTZ_MOVE_GOTO_PRESET:
            if not preset:
                _LOGGER.warning("PTZ GotoPreset requires a preset token")
                return
            if not await self._api.async_ptz_goto_preset(preset):
                _LOGGER.warning(
                    "PTZ preset %s not supported by %s", preset, self._entry.title
                )
            return

        # ContinuousMove, optionally auto-stopped after the requested duration.
        if not await self._api.async_ptz_continuous_move(pan=pan, tilt=tilt, zoom=zoom):
            _LOGGER.warning("PTZ move not supported by %s", self._entry.title)
            return

        if continuous_duration > 0:
            await asyncio.sleep(continuous_duration)
            await self._api.async_ptz_stop()

    async def async_camera_image(
        self,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes | None:
        """Return a still image from the camera HTTP snapshot endpoint."""
        del width, height

        snapshot = await self._api.async_get_snapshot()
        if snapshot is None:
            return None

        _, image = snapshot
        return image
