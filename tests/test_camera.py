from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch, sentinel

import pytest

from homeassistant.const import CONF_NAME, CONF_PASSWORD, CONF_USERNAME

from custom_components.showmo.camera import ShowMoCamera, async_setup_entry
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


def _seed_runtime_data(hass, entry: MockConfigEntry, api=None):
    api = api or AsyncMock()
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {"api": api}
    return api


async def test_async_setup_entry_adds_camera_with_stream_source(hass) -> None:
    """The platform setup should expose a camera and register the PTZ service."""
    entry = _build_entry()
    api = _seed_runtime_data(hass, entry)
    entities: list[ShowMoCamera] = []

    platform = Mock()
    with patch(
        "custom_components.showmo.camera.entity_platform.async_get_current_platform",
        return_value=platform,
    ):
        await async_setup_entry(hass, entry, entities.extend)

    assert len(entities) == 1
    entity = entities[0]
    assert await entity.stream_source() == (
        "rtsp://admin:123456@192.168.8.120/live0_0.sdp"
    )
    assert entity._api is api
    assert entity.unique_id == "sn-406A8EFF7512"
    assert entity.device_info["identifiers"] == {(DOMAIN, "sn-406A8EFF7512")}
    platform.async_register_entity_service.assert_called_once()


async def test_perform_ptz_continuous_move_auto_stops(hass) -> None:
    """A ContinuousMove should delegate then auto-stop after the duration."""
    entry = _build_entry()
    api = _seed_runtime_data(hass, entry)
    api.async_ptz_continuous_move = AsyncMock(return_value=True)
    api.async_ptz_stop = AsyncMock(return_value=True)
    entity = ShowMoCamera(hass, entry)

    with patch(
        "custom_components.showmo.camera.asyncio.sleep", AsyncMock()
    ) as sleep:
        await entity.async_perform_ptz(
            "ContinuousMove", pan=0.5, continuous_duration=0.5
        )

    api.async_ptz_continuous_move.assert_awaited_once_with(pan=0.5, tilt=0.0, zoom=0.0)
    sleep.assert_awaited_once()
    api.async_ptz_stop.assert_awaited_once_with()


async def test_perform_ptz_continuous_move_skips_stop_when_unsupported(hass) -> None:
    """When the camera rejects the move, no auto-stop is attempted."""
    entry = _build_entry()
    api = _seed_runtime_data(hass, entry)
    api.async_ptz_continuous_move = AsyncMock(return_value=False)
    api.async_ptz_stop = AsyncMock(return_value=True)
    entity = ShowMoCamera(hass, entry)

    with patch("custom_components.showmo.camera.asyncio.sleep", AsyncMock()):
        await entity.async_perform_ptz("ContinuousMove", pan=0.5)

    api.async_ptz_continuous_move.assert_awaited_once()
    api.async_ptz_stop.assert_not_awaited()


async def test_perform_ptz_stop(hass) -> None:
    """Stop should delegate directly to the API client."""
    entry = _build_entry()
    api = _seed_runtime_data(hass, entry)
    api.async_ptz_stop = AsyncMock(return_value=True)
    entity = ShowMoCamera(hass, entry)

    await entity.async_perform_ptz("Stop")

    api.async_ptz_stop.assert_awaited_once_with()


async def test_perform_ptz_goto_preset(hass) -> None:
    """GotoPreset should forward the preset token."""
    entry = _build_entry()
    api = _seed_runtime_data(hass, entry)
    api.async_ptz_goto_preset = AsyncMock(return_value=True)
    entity = ShowMoCamera(hass, entry)

    await entity.async_perform_ptz("GotoPreset", preset="Preset1")

    api.async_ptz_goto_preset.assert_awaited_once_with("Preset1")


async def test_perform_ptz_goto_preset_requires_token(hass) -> None:
    """GotoPreset without a token must not call the API."""
    entry = _build_entry()
    api = _seed_runtime_data(hass, entry)
    api.async_ptz_goto_preset = AsyncMock(return_value=True)
    entity = ShowMoCamera(hass, entry)

    await entity.async_perform_ptz("GotoPreset", preset="")

    api.async_ptz_goto_preset.assert_not_awaited()


async def test_camera_image_returns_snapshot_bytes(hass) -> None:
    """The entity should return snapshot bytes when the API client succeeds."""
    entry = _build_entry()
    api = _seed_runtime_data(hass, entry)
    api.async_get_snapshot = AsyncMock(
        return_value=("http://192.168.8.120:8080/onvif/snapshot", b"\xff\xd8\xff\xd9")
    )
    entity = ShowMoCamera(hass, entry)

    assert await entity.async_camera_image() == b"\xff\xd8\xff\xd9"
    api.async_get_snapshot.assert_awaited_once_with()


async def test_camera_image_returns_none_when_snapshot_is_unavailable(hass) -> None:
    """The entity should gracefully handle cameras without HTTP snapshot support."""
    entry = _build_entry()
    api = _seed_runtime_data(hass, entry)
    api.async_get_snapshot = AsyncMock(return_value=None)
    entity = ShowMoCamera(hass, entry)

    assert await entity.async_camera_image() is None
    api.async_get_snapshot.assert_awaited_once_with()


async def test_camera_uses_runtime_api_client(hass) -> None:
    """The camera should reuse the API client created during integration setup."""
    entry = _build_entry()
    api = _seed_runtime_data(hass, entry, api=sentinel.runtime_api)
    entity = ShowMoCamera(hass, entry)
    assert entity._api is api
