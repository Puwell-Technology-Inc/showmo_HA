"""ONVIF motion event handling for ShowMo cameras."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .api import ShowMoApiClient

_LOGGER = logging.getLogger(__name__)

RETRY_DELAY_SECONDS = 10


class ShowMoMotionCoordinator:
    """Manage an ONVIF PullPoint subscription for motion events."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: ShowMoApiClient,
    ) -> None:
        """Initialize the motion coordinator."""
        self._hass = hass
        self._entry = entry
        self._api = api
        self._subscription_url: str | None = None
        self._task: asyncio.Task[None] | None = None
        self._listeners: set[Callable[[], None]] = set()
        self._initialize_lock = asyncio.Lock()
        self._supported: bool | None = None
        self._available = False
        self._is_on = False
        self._last_topic: str | None = None
        self._last_motion_at: datetime | None = None

    @property
    def available(self) -> bool:
        """Return whether ONVIF motion delivery is currently available."""
        return self._available

    @property
    def is_on(self) -> bool:
        """Return the latest known motion state."""
        return self._is_on

    @property
    def supported(self) -> bool | None:
        """Return whether the camera appears to support ONVIF events."""
        return self._supported

    @property
    def last_topic(self) -> str | None:
        """Return the most recent ONVIF motion topic."""
        return self._last_topic

    @property
    def last_motion_at(self) -> datetime | None:
        """Return when the last motion notification was received."""
        return self._last_motion_at

    async def async_initialize(self) -> bool:
        """Resolve whether ONVIF events are supported.

        A camera must not only advertise an event service but actually accept a
        PullPoint subscription. WinEye firmware advertises an ``/onvif/events``
        endpoint it does not implement, so an advertised URL is not proof; only
        a subscription that the camera accepts is. The subscription created here
        is kept and reused by :meth:`_async_run` to avoid subscribing twice.
        """
        if self._supported is not None:
            return self._supported

        async with self._initialize_lock:
            if self._supported is not None:
                return self._supported

            subscription_url = await self._api.async_create_pullpoint_subscription()
            if subscription_url is None:
                self._supported = False
                return False

            self._subscription_url = subscription_url
            self._available = True
            self._supported = True
            return True

    async def async_start(self) -> bool:
        """Start the background PullPoint task."""
        if not await self.async_initialize():
            return False

        if self._task is None:
            # A long-lived poll loop: register it as a background task so HA's
            # shutdown/unload cancels it instead of waiting out the 70s pull.
            self._task = self._entry.async_create_background_task(
                self._hass,
                self._async_run(),
                name="showmo motion pullpoint",
            )
        return True

    async def async_stop(self) -> None:
        """Stop the background PullPoint task."""
        task = self._task
        self._task = None

        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        await self._async_clear_subscription()

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register a state update listener."""
        self._listeners.add(listener)

        @callback
        def remove_listener() -> None:
            """Remove the listener and stop polling if nobody is listening."""
            self._listeners.discard(listener)
            if not self._listeners and self._task is not None:
                self._hass.async_create_task(self.async_stop())

        return remove_listener

    @callback
    def _async_notify_listeners(self) -> None:
        """Notify listeners that coordinator state changed."""
        for listener in tuple(self._listeners):
            listener()

    @callback
    def _async_update_state(
        self,
        *,
        available: bool | None = None,
        is_on: bool | None = None,
        topic: str | None = None,
        motion_at: datetime | None = None,
    ) -> None:
        """Update coordinator state and notify listeners if needed."""
        changed = False

        if available is not None and self._available != available:
            self._available = available
            changed = True

        if is_on is not None and self._is_on != is_on:
            self._is_on = is_on
            changed = True

        if topic is not None and self._last_topic != topic:
            self._last_topic = topic
            changed = True

        if motion_at is not None:
            self._last_motion_at = motion_at
            changed = True

        if changed:
            self._async_notify_listeners()

    async def _async_run(self) -> None:
        """Create a PullPoint subscription and keep polling for motion events."""
        try:
            while True:
                if self._subscription_url is None:
                    subscription_url = await self._api.async_create_pullpoint_subscription()
                    if subscription_url is None:
                        self._async_update_state(available=False)
                        await asyncio.sleep(RETRY_DELAY_SECONDS)
                        continue

                    self._subscription_url = subscription_url
                    self._async_update_state(available=True)

                notifications = await self._api.async_pull_messages(
                    self._subscription_url,
                    timeout=70.0,
                    message_limit=10,
                )
                if notifications is None:
                    _LOGGER.debug(
                        "ONVIF PullMessages returned no data for %s",
                        self._entry.title,
                    )
                    self._async_update_state(available=False)
                    await self._async_clear_subscription()
                    await asyncio.sleep(RETRY_DELAY_SECONDS)
                    continue

                self._async_update_state(available=True)

                for notification in notifications:
                    motion = notification.get("motion")
                    if motion is None:
                        continue

                    self._async_update_state(
                        is_on=motion,
                        topic=notification.get("topic"),
                        motion_at=dt_util.utcnow(),
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("ONVIF motion listener failed for %s", self._entry.title)
            self._async_update_state(available=False)
        finally:
            await self._async_clear_subscription()

    async def _async_clear_subscription(self) -> None:
        """Unsubscribe from the current PullPoint subscription."""
        if self._subscription_url is None:
            return

        subscription_url = self._subscription_url
        self._subscription_url = None

        try:
            await self._api.async_unsubscribe(subscription_url)
        except Exception:
            _LOGGER.debug(
                "Failed to unsubscribe from ONVIF motion events for %s",
                self._entry.title,
                exc_info=True,
            )
