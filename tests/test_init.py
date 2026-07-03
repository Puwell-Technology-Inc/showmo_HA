from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from homeassistant.const import CONF_NAME, CONF_PASSWORD, CONF_USERNAME

from custom_components.showmo import async_setup_entry, async_unload_entry
from custom_components.showmo.const import DOMAIN

from pytest_homeassistant_custom_component.common import MockConfigEntry


pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _build_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Front Door",
        data={
            CONF_NAME: "Front Door",
            CONF_USERNAME: "admin",
            CONF_PASSWORD: "123456",
            "host": "192.168.8.120",
            "port": 554,
            "path": "/live0_0.sdp",
            "serial": "sn-406A8EFF7512",
        },
    )


async def test_async_setup_entry_stores_runtime_data_and_forwards_platforms(hass) -> None:
    """Setup should create runtime data and forward supported platforms."""
    entry = _build_entry()
    session = object()
    motion = object()

    with (
        patch("custom_components.showmo.async_get_clientsession", return_value=session),
        patch("custom_components.showmo.ShowMoMotionCoordinator", return_value=motion),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            AsyncMock(return_value=None),
        ) as forward_setups,
    ):
        assert await async_setup_entry(hass, entry) is True

    runtime_data = hass.data[DOMAIN][entry.entry_id]
    assert runtime_data["motion"] is motion
    assert runtime_data["api"].host == "192.168.8.120"
    assert runtime_data["api"].port == 554
    assert runtime_data["api"]._session is session
    forward_setups.assert_awaited_once()


async def test_async_setup_entry_cleans_runtime_data_when_forward_fails(hass) -> None:
    """Setup should roll back runtime data if platform forwarding fails."""
    entry = _build_entry()
    session = object()
    motion = object()

    with (
        patch("custom_components.showmo.async_get_clientsession", return_value=session),
        patch("custom_components.showmo.ShowMoMotionCoordinator", return_value=motion),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            AsyncMock(side_effect=RuntimeError("forward failed")),
        ),
        pytest.raises(RuntimeError, match="forward failed"),
    ):
        await async_setup_entry(hass, entry)

    assert entry.entry_id not in hass.data[DOMAIN]


async def test_async_unload_entry_stops_motion_and_clears_runtime_data(hass) -> None:
    """Unload should stop the motion coordinator and remove runtime data."""
    entry = _build_entry()
    motion = type("Motion", (), {"async_stop": AsyncMock()})()
    hass.data[DOMAIN] = {
        entry.entry_id: {
            "api": object(),
            "motion": motion,
        }
    }

    with patch.object(
        hass.config_entries,
        "async_unload_platforms",
        AsyncMock(return_value=True),
    ) as unload_platforms:
        assert await async_unload_entry(hass, entry) is True

    motion.async_stop.assert_awaited_once()
    unload_platforms.assert_awaited_once()
    assert entry.entry_id not in hass.data[DOMAIN]


async def test_async_unload_entry_keeps_runtime_data_when_unload_fails(hass) -> None:
    """Unload should preserve runtime data when platform unloading fails."""
    entry = _build_entry()
    motion = type("Motion", (), {"async_stop": AsyncMock()})()
    hass.data[DOMAIN] = {
        entry.entry_id: {
            "api": object(),
            "motion": motion,
        }
    }

    with patch.object(
        hass.config_entries,
        "async_unload_platforms",
        AsyncMock(return_value=False),
    ):
        assert await async_unload_entry(hass, entry) is False

    motion.async_stop.assert_awaited_once()
    assert entry.entry_id in hass.data[DOMAIN]
