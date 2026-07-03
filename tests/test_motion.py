from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from homeassistant.const import CONF_NAME, CONF_PASSWORD, CONF_USERNAME

from custom_components.showmo.const import DOMAIN
from custom_components.showmo.motion import ShowMoMotionCoordinator

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


async def test_motion_initialize_caches_supported_state(hass) -> None:
    """Initialization should probe with a real subscription once and cache it."""
    api = SimpleNamespace(
        async_create_pullpoint_subscription=AsyncMock(
            return_value="http://192.168.8.120:8080/subscription"
        )
    )
    coordinator = ShowMoMotionCoordinator(hass, _build_entry(), api)

    assert await coordinator.async_initialize() is True
    assert await coordinator.async_initialize() is True
    api.async_create_pullpoint_subscription.assert_awaited_once()
    # The probe subscription is kept so the polling loop does not subscribe twice.
    assert coordinator._subscription_url == "http://192.168.8.120:8080/subscription"


async def test_motion_start_returns_false_when_events_are_unsupported(hass) -> None:
    """Start should fail cleanly when the camera rejects a subscription.

    WinEye firmware advertises an event endpoint it does not implement, so the
    subscription attempt returns None and the sensor must not be exposed.
    """
    api = SimpleNamespace(
        async_create_pullpoint_subscription=AsyncMock(return_value=None)
    )
    coordinator = ShowMoMotionCoordinator(hass, _build_entry(), api)

    assert await coordinator.async_start() is False
    assert coordinator.supported is False


async def test_motion_run_updates_state_from_notifications(hass) -> None:
    """The coordinator should become available and reflect incoming motion."""
    now = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
    api = SimpleNamespace(
        async_create_pullpoint_subscription=AsyncMock(
            return_value="http://192.168.8.120:8080/subscription"
        ),
        async_pull_messages=AsyncMock(
            side_effect=[
                [
                    {
                        "topic": "tns1:RuleEngine/CellMotionDetector/Motion",
                        "motion": True,
                    }
                ],
                asyncio.CancelledError(),
            ]
        ),
        async_unsubscribe=AsyncMock(return_value=True),
    )
    coordinator = ShowMoMotionCoordinator(hass, _build_entry(), api)

    with patch("custom_components.showmo.motion.dt_util.utcnow", return_value=now):
        with pytest.raises(asyncio.CancelledError):
            await coordinator._async_run()

    assert coordinator.available is True
    assert coordinator.is_on is True
    assert coordinator.last_topic == "tns1:RuleEngine/CellMotionDetector/Motion"
    assert coordinator.last_motion_at == now
    api.async_unsubscribe.assert_awaited_once_with(
        "http://192.168.8.120:8080/subscription"
    )


async def test_motion_run_marks_unavailable_when_pull_messages_fail(hass) -> None:
    """The coordinator should clear availability when a pull returns no data."""
    api = SimpleNamespace(
        async_create_pullpoint_subscription=AsyncMock(
            return_value="http://192.168.8.120:8080/subscription"
        ),
        async_pull_messages=AsyncMock(return_value=None),
        async_unsubscribe=AsyncMock(return_value=True),
    )
    coordinator = ShowMoMotionCoordinator(hass, _build_entry(), api)

    with patch(
        "custom_components.showmo.motion.asyncio.sleep",
        AsyncMock(side_effect=asyncio.CancelledError()),
    ):
        with pytest.raises(asyncio.CancelledError):
            await coordinator._async_run()

    assert coordinator.available is False
    api.async_unsubscribe.assert_awaited_once_with(
        "http://192.168.8.120:8080/subscription"
    )


async def test_motion_remove_last_listener_schedules_stop(hass) -> None:
    """Removing the last listener should schedule coordinator shutdown."""
    api = SimpleNamespace(async_get_event_service_url=AsyncMock(return_value="http://events"))
    coordinator = ShowMoMotionCoordinator(hass, _build_entry(), api)
    coordinator._task = object()
    coordinator.async_stop = AsyncMock()

    scheduled_tasks: list[asyncio.Task[None]] = []

    def _create_task(coro):
        task = asyncio.create_task(coro)
        scheduled_tasks.append(task)
        return task

    with patch.object(hass, "async_create_task", Mock(side_effect=_create_task)) as create_task:
        remove_listener = coordinator.async_add_listener(lambda: None)
        remove_listener()

    assert scheduled_tasks
    await asyncio.gather(*scheduled_tasks)
    coordinator.async_stop.assert_awaited_once()
    create_task.assert_called_once()
