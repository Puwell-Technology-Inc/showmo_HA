from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import CONF_NAME, CONF_PASSWORD, CONF_USERNAME

from custom_components.showmo.binary_sensor import ShowMoMotionBinarySensor, async_setup_entry
from custom_components.showmo.const import DOMAIN

from pytest_homeassistant_custom_component.common import MockConfigEntry


pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


class MockMotionCoordinator:
    def __init__(self) -> None:
        self.available = True
        self.is_on = False
        self.last_topic = None
        self.last_motion_at = None
        self.async_initialize = AsyncMock(return_value=True)
        self.async_start = AsyncMock(return_value=True)
        self.async_stop = AsyncMock()
        self._listener = None

    def async_add_listener(self, listener):
        self._listener = listener

        def remove_listener() -> None:
            self._listener = None

        return remove_listener


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


async def test_async_setup_entry_adds_motion_binary_sensor(hass) -> None:
    """The binary sensor platform should add a motion entity when supported."""
    entry = _build_entry()
    motion = MockMotionCoordinator()
    hass.data[DOMAIN] = {
        entry.entry_id: {
            "motion": motion,
        }
    }
    entities: list[ShowMoMotionBinarySensor] = []

    await async_setup_entry(hass, entry, entities.extend)

    assert len(entities) == 1
    entity = entities[0]
    assert entity.device_class is BinarySensorDeviceClass.MOTION
    assert entity.unique_id == "sn-406A8EFF7512_motion"


async def test_motion_binary_sensor_reflects_coordinator_state(hass) -> None:
    """Entity state should mirror the coordinator."""
    motion = MockMotionCoordinator()
    entry = _build_entry()
    entity = ShowMoMotionBinarySensor(entry, motion)
    entity.async_write_ha_state = Mock()

    await entity.async_added_to_hass()

    assert entity.available is True
    assert entity.is_on is False
    motion.async_start.assert_awaited_once()

    motion.is_on = True
    motion.last_topic = "tns1:RuleEngine/CellMotionDetector/Motion"
    motion.last_motion_at = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
    motion._listener()

    assert entity.is_on is True
    entity.async_write_ha_state.assert_called_once_with()
    assert entity.extra_state_attributes == {
        "last_topic": "tns1:RuleEngine/CellMotionDetector/Motion",
        "last_motion_at": "2026-04-01T12:00:00+00:00",
    }


async def test_async_setup_entry_skips_entity_when_motion_is_unsupported(hass) -> None:
    """The binary sensor platform should not add entities when motion is unsupported."""
    entry = _build_entry()
    motion = MockMotionCoordinator()
    motion.async_initialize = AsyncMock(return_value=False)
    hass.data[DOMAIN] = {
        entry.entry_id: {
            "motion": motion,
        }
    }
    entities: list[ShowMoMotionBinarySensor] = []

    await async_setup_entry(hass, entry, entities.extend)

    assert entities == []
    motion.async_start.assert_not_awaited()


async def test_motion_binary_sensor_removes_listener_on_removal(hass) -> None:
    """Removing the entity should unregister the coordinator listener."""
    motion = MockMotionCoordinator()
    entry = _build_entry()
    entity = ShowMoMotionBinarySensor(entry, motion)

    await entity.async_added_to_hass()
    assert motion._listener is not None

    await entity.async_will_remove_from_hass()

    assert motion._listener is None
    assert entity._remove_listener is None
