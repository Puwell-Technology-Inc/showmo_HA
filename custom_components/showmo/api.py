"""Home Assistant adapter around the pyshowmo package."""

from __future__ import annotations

from typing import Any

import aiohttp

try:
    from .pyshowmo.exceptions import AuthenticationError, DiscoveryError
    from .pyshowmo import (
        ShowMoClient,
        build_default_rtsp_path,
        build_rtsp_url_with_credentials,
        build_rtsp_url_without_credentials,
        check_onvif,
        check_onvif_url,
        check_rtsp,
        discover_devices,
        discover_onvif_devices,
        get_local_ip,
        get_local_subnet,
        parse_device_information,
        parse_rtsp_url,
        parse_ws_discovery_response,
        scan_network,
        ws_discover,
    )
except ImportError:
    from pyshowmo.exceptions import AuthenticationError, DiscoveryError
    from pyshowmo import (
        ShowMoClient,
        build_default_rtsp_path,
        build_rtsp_url_with_credentials,
        build_rtsp_url_without_credentials,
        check_onvif,
        check_onvif_url,
        check_rtsp,
        discover_devices,
        discover_onvif_devices,
        get_local_ip,
        get_local_subnet,
        parse_device_information,
        parse_rtsp_url,
        parse_ws_discovery_response,
        scan_network,
        ws_discover,
    )


class ShowMoApiClient(ShowMoClient):
    """Backward-compatible HA adapter for ShowMo cameras."""

    @staticmethod
    def get_local_ip() -> str | None:
        """Return the outbound local IPv4 address."""
        return get_local_ip()

    @staticmethod
    def get_local_subnet() -> str | None:
        """Return the outbound /24 subnet."""
        return get_local_subnet()

    @staticmethod
    def parse_device_information(xml_text: str) -> dict[str, str | None]:
        """Parse ONVIF device information into the legacy dict shape."""
        info = parse_device_information(xml_text)
        return {
            "manufacturer": info.manufacturer,
            "model": info.model,
            "firmwareversion": info.firmware_version,
            "serialnumber": info.serial_number,
            "hardwareid": info.hardware_id,
        }

    @staticmethod
    def parse_ws_discovery_response(
        xml_text: str,
        source_ip: str,
        source_port: int,
    ) -> list[dict[str, Any]]:
        """Parse WS-Discovery ProbeMatch responses."""
        return [
            match.to_dict()
            for match in parse_ws_discovery_response(xml_text, source_ip, source_port)
        ]

    @staticmethod
    async def ws_discover(
        timeout: float = 5.0,
        local_ip: str | None = None,
    ) -> list[dict[str, Any]]:
        """Run WS-Discovery without blocking the event loop."""
        return [match.to_dict() for match in await ws_discover(timeout, local_ip)]

    @staticmethod
    async def check_onvif_url(
        session: aiohttp.ClientSession,
        url: str,
        username: str | None = None,
        password: str | None = None,
        timeout: float = 5.0,
    ) -> dict[str, Any] | None:
        """Check whether the given ONVIF device service URL is reachable."""
        result = await check_onvif_url(session, url, username, password, timeout)
        return result.to_dict() if result is not None else None

    @staticmethod
    async def check_onvif(
        session: aiohttp.ClientSession,
        ip: str,
        port: int = 8080,
        username: str | None = None,
        password: str | None = None,
        timeout: float = 5.0,
    ) -> dict[str, Any] | None:
        """Check ONVIF on a host/port pair."""
        result = await check_onvif(session, ip, port, username, password, timeout)
        return result.to_dict() if result is not None else None

    @staticmethod
    async def check_rtsp(
        ip: str,
        port: int = 554,
        timeout: float = 1.0,
    ) -> bool:
        """Check whether the RTSP port is reachable."""
        return await check_rtsp(ip, port, timeout)

    @staticmethod
    async def scan_network(
        subnet: str,
        max_concurrent: int = 50,
        username: str | None = None,
        password: str | None = None,
        rtsp_port: int = 554,
        onvif_ports: tuple[int, ...] = (8080, 80),
    ) -> list[dict[str, Any]]:
        """Scan a subnet for RTSP/ONVIF devices."""
        return [
            device.to_dict()
            for device in await scan_network(
                subnet,
                max_concurrent=max_concurrent,
                username=username,
                password=password,
                rtsp_port=rtsp_port,
                onvif_ports=onvif_ports,
            )
        ]

    @staticmethod
    async def discover_onvif_devices(
        timeout: float = 5.0,
        local_ip: str | None = None,
        username: str | None = None,
        password: str | None = None,
        session: aiohttp.ClientSession | None = None,
    ) -> list[dict[str, Any]]:
        """Discover ONVIF devices via WS-Discovery and validate XAddrs."""
        return [
            device.to_dict()
            for device in await discover_onvif_devices(
                timeout=timeout,
                local_ip=local_ip,
                username=username,
                password=password,
                session=session,
            )
        ]

    @staticmethod
    async def discover_devices(
        timeout: float = 5.0,
        local_ip: str | None = None,
        subnet: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> list[dict[str, Any]]:
        """Discover devices via WS-Discovery first, then network scan fallback."""
        return [
            device.to_dict()
            for device in await discover_devices(
                timeout=timeout,
                local_ip=local_ip,
                subnet=subnet,
                username=username,
                password=password,
            )
        ]

    async def get_device_serial(self) -> str | None:
        """Fetch the ONVIF serial number."""
        return await super().get_device_serial()

    async def async_get_snapshot(self) -> tuple[str, bytes] | None:
        """Fetch a still image using the legacy adapter method name."""
        return await super().get_snapshot()

    async def async_get_event_service_url(self) -> str | None:
        """Fetch the ONVIF Events service URL."""
        return await super().get_event_service_url()

    async def async_create_pullpoint_subscription(self) -> str | None:
        """Create a PullPoint subscription and return its address."""
        subscription = await super().create_pullpoint_subscription()
        return subscription.address if subscription is not None else None

    async def async_pull_messages(
        self,
        subscription_url: str,
        timeout: float = 70.0,
        message_limit: int = 10,
    ) -> list[dict[str, Any]] | None:
        """Pull ONVIF event messages and return legacy dicts."""
        notifications = await super().pull_messages(
            subscription_url=subscription_url,
            timeout=timeout,
            message_limit=message_limit,
        )
        if notifications is None:
            return None

        return [
            {
                "topic": notification.topic,
                "source_items": dict(notification.source_items),
                "data_items": dict(notification.data_items),
                "motion": notification.motion,
            }
            for notification in notifications
        ]

    async def async_unsubscribe(self, subscription_url: str) -> bool:
        """Best-effort unsubscribe from a PullPoint subscription."""
        return await super().unsubscribe(subscription_url)

    async def async_ptz_continuous_move(
        self,
        pan: float = 0.0,
        tilt: float = 0.0,
        zoom: float = 0.0,
    ) -> bool:
        """Start a continuous PTZ move at the given pan/tilt/zoom velocities."""
        return await super().ptz_continuous_move(pan=pan, tilt=tilt, zoom=zoom)

    async def async_ptz_stop(self) -> bool:
        """Stop any ongoing PTZ movement."""
        return await super().ptz_stop()

    async def async_ptz_goto_preset(self, preset_token: str) -> bool:
        """Move the camera to a stored PTZ preset."""
        return await super().ptz_goto_preset(preset_token)

    async def async_ptz_goto_home(self) -> bool:
        """Move the camera to its PTZ home position."""
        return await super().ptz_goto_home()

    async def test_connection(self) -> bool:
        """Test whether the camera HTTP interface is reachable."""
        return await super().test_connection()
