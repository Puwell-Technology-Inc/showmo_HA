"""The ShowMo integration."""

from __future__ import annotations

import asyncio
import logging

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AuthenticationError, ShowMoApiClient
from .const import DOMAIN
from .motion import ShowMoMotionCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.CAMERA, Platform.BINARY_SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ShowMo from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    api = ShowMoApiClient(
        host=entry.data["host"],
        port=entry.data["port"],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        session=async_get_clientsession(hass),
    )

    # Probe the camera once so a changed password surfaces as a reauth prompt
    # instead of a silently unavailable stream. The RTSP path never reports
    # auth failures back to the integration (HA's stream component pulls it),
    # so (re)load time is the reliable place to detect stale credentials.
    try:
        async with asyncio.timeout(15):
            await api.check_credentials()
    except AuthenticationError as err:
        raise ConfigEntryAuthFailed(
            "Camera rejected the stored credentials"
        ) from err
    except (TimeoutError, aiohttp.ClientError, OSError, ValueError):
        # Unreachable is not an auth problem: entities go unavailable on
        # their own and recover when the camera comes back.
        _LOGGER.debug("Credential probe inconclusive for %s", entry.title)

    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "motion": ShowMoMotionCoordinator(hass, entry, api),
    }

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        raise

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    runtime_data = hass.data[DOMAIN][entry.entry_id]
    await runtime_data["motion"].async_stop()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok
