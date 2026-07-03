"""Async client for ShowMo cameras."""

from __future__ import annotations

import aiohttp

from .constants import COMMON_SNAPSHOT_PATHS
from .exceptions import AuthenticationError
from .models import DeviceInfo, OnvifNotification, PullPointSubscription
from .network import check_rtsp
from .onvif import (
    check_onvif,
    create_pullpoint_subscription,
    get_event_service_url,
    get_first_profile_token as onvif_get_first_profile_token,
    get_service_url,
    ptz_continuous_move as onvif_ptz_continuous_move,
    ptz_goto_home as onvif_ptz_goto_home,
    ptz_goto_preset as onvif_ptz_goto_preset,
    ptz_stop as onvif_ptz_stop,
    pull_messages,
    unsubscribe,
)


class ShowMoClient:
    """Async client for ShowMo cameras."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self._session = session
        self._owns_session = session is None
        self._snapshot_url: str | None = None
        self._event_service_url: str | None = None
        self._media_service_url: str | None = None
        self._ptz_service_url: str | None = None
        self._profile_token: str | None = None

    def _onvif_ports(self) -> list[int]:
        """Return the ONVIF ports to probe in preferred order."""
        if self.port in (80, 8080):
            return [8080, 80]
        return [8080, 80, self.port]

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    async def get_device_information(self, port: int | None = None) -> DeviceInfo | None:
        """Fetch normalized ONVIF device information."""
        session = await self._ensure_session()
        result = await check_onvif(
            session=session,
            ip=self.host,
            port=port or self.port,
            username=self.username,
            password=self.password,
            timeout=10.0,
        )
        if result is None:
            return None
        if result.auth_required:
            raise AuthenticationError("ONVIF authentication failed")
        return result.device_info

    async def get_device_serial(self) -> str | None:
        """Fetch the ONVIF serial number using common ports."""
        for onvif_port in self._onvif_ports():
            info = await self.get_device_information(onvif_port)
            if info and info.serial_number:
                return info.serial_number
        return None

    async def get_event_service_url(self) -> str | None:
        """Fetch and cache the ONVIF Events service URL."""
        if self._event_service_url is not None:
            return self._event_service_url

        session = await self._ensure_session()
        for onvif_port in self._onvif_ports():
            url = await get_event_service_url(
                session=session,
                device_service_url=f"http://{self.host}:{onvif_port}/onvif/device_service",
                username=self.username,
                password=self.password,
                timeout=10.0,
            )
            if url is not None:
                self._event_service_url = url
                return url

        return None

    async def create_pullpoint_subscription(self) -> PullPointSubscription | None:
        """Create a PullPoint subscription against the camera Events service."""
        event_service_url = await self.get_event_service_url()
        if event_service_url is None:
            return None

        session = await self._ensure_session()
        return await create_pullpoint_subscription(
            session=session,
            event_service_url=event_service_url,
            username=self.username,
            password=self.password,
            timeout=10.0,
        )

    async def pull_messages(
        self,
        subscription_url: str,
        timeout: float = 70.0,
        message_limit: int = 10,
    ) -> list[OnvifNotification] | None:
        """Pull ONVIF event messages from a subscription URL."""
        session = await self._ensure_session()
        return await pull_messages(
            session=session,
            subscription_url=subscription_url,
            username=self.username,
            password=self.password,
            timeout=timeout,
            message_limit=message_limit,
        )

    async def unsubscribe(self, subscription_url: str) -> bool:
        """Best-effort unsubscribe from a PullPoint subscription."""
        session = await self._ensure_session()
        return await unsubscribe(
            session=session,
            subscription_url=subscription_url,
            username=self.username,
            password=self.password,
            timeout=5.0,
        )

    async def _resolve_service_url(self, category: str, cache_attr: str) -> str | None:
        """Resolve and cache an ONVIF service URL by capability category."""
        cached = getattr(self, cache_attr)
        if cached is not None:
            return cached

        session = await self._ensure_session()
        for onvif_port in self._onvif_ports():
            url = await get_service_url(
                session=session,
                device_service_url=f"http://{self.host}:{onvif_port}/onvif/device_service",
                category=category,
                username=self.username,
                password=self.password,
                timeout=10.0,
            )
            if url is not None:
                setattr(self, cache_attr, url)
                return url

        return None

    async def get_media_service_url(self) -> str | None:
        """Fetch and cache the ONVIF Media service URL."""
        return await self._resolve_service_url("Media", "_media_service_url")

    async def get_ptz_service_url(self) -> str | None:
        """Fetch and cache the ONVIF PTZ service URL."""
        return await self._resolve_service_url("PTZ", "_ptz_service_url")

    async def get_first_profile_token(self) -> str | None:
        """Fetch and cache the first media profile token (needed for PTZ)."""
        if self._profile_token is not None:
            return self._profile_token

        media_url = await self.get_media_service_url()
        if media_url is None:
            return None

        session = await self._ensure_session()
        token = await onvif_get_first_profile_token(
            session=session,
            media_service_url=media_url,
            username=self.username,
            password=self.password,
            timeout=10.0,
        )
        if token is not None:
            self._profile_token = token
        return token

    async def _ptz_context(self) -> tuple[str, str] | None:
        """Resolve the PTZ service URL and a profile token, or None."""
        ptz_url = await self.get_ptz_service_url()
        profile_token = await self.get_first_profile_token()
        if ptz_url is None or profile_token is None:
            return None
        return ptz_url, profile_token

    async def ptz_continuous_move(
        self,
        pan: float = 0.0,
        tilt: float = 0.0,
        zoom: float = 0.0,
    ) -> bool:
        """Start a continuous PTZ move at the given pan/tilt/zoom velocities."""
        context = await self._ptz_context()
        if context is None:
            return False
        ptz_url, profile_token = context
        session = await self._ensure_session()
        return await onvif_ptz_continuous_move(
            session=session,
            ptz_service_url=ptz_url,
            profile_token=profile_token,
            pan=pan,
            tilt=tilt,
            zoom=zoom,
            username=self.username,
            password=self.password,
        )

    async def ptz_stop(self) -> bool:
        """Stop any ongoing PTZ movement."""
        context = await self._ptz_context()
        if context is None:
            return False
        ptz_url, profile_token = context
        session = await self._ensure_session()
        return await onvif_ptz_stop(
            session=session,
            ptz_service_url=ptz_url,
            profile_token=profile_token,
            username=self.username,
            password=self.password,
        )

    async def ptz_goto_preset(self, preset_token: str) -> bool:
        """Move the camera to a stored PTZ preset."""
        context = await self._ptz_context()
        if context is None:
            return False
        ptz_url, profile_token = context
        session = await self._ensure_session()
        return await onvif_ptz_goto_preset(
            session=session,
            ptz_service_url=ptz_url,
            profile_token=profile_token,
            preset_token=preset_token,
            username=self.username,
            password=self.password,
        )

    async def ptz_goto_home(self) -> bool:
        """Move the camera to its PTZ home position."""
        context = await self._ptz_context()
        if context is None:
            return False
        ptz_url, profile_token = context
        session = await self._ensure_session()
        return await onvif_ptz_goto_home(
            session=session,
            ptz_service_url=ptz_url,
            profile_token=profile_token,
            username=self.username,
            password=self.password,
        )

    async def get_snapshot(self, preferred_ports: tuple[int, ...] = (8080, 80)) -> tuple[str, bytes] | None:
        """Fetch a JPEG snapshot from a common HTTP endpoint."""
        session = await self._ensure_session()
        auth = aiohttp.BasicAuth(self.username, self.password)

        if self._snapshot_url is not None:
            try:
                async with session.get(
                    self._snapshot_url,
                    auth=auth,
                    timeout=aiohttp.ClientTimeout(total=5.0),
                ) as response:
                    if response.status == 200:
                        content_type = response.headers.get("Content-Type", "")
                        image = await response.read()
                        if "image/jpeg" in content_type.lower() and image.startswith(b"\xff\xd8"):
                            return self._snapshot_url, image
            except (TimeoutError, aiohttp.ClientError):
                self._snapshot_url = None

        ports = list(preferred_ports)
        if self.port not in ports and self.port != 554:
            ports.append(self.port)

        for port in ports:
            for path in COMMON_SNAPSHOT_PATHS:
                url = f"http://{self.host}:{port}{path}"
                try:
                    async with session.get(
                        url,
                        auth=auth,
                        timeout=aiohttp.ClientTimeout(total=5.0),
                    ) as response:
                        if response.status != 200:
                            continue
                        content_type = response.headers.get("Content-Type", "")
                        image = await response.read()
                except (TimeoutError, aiohttp.ClientError):
                    continue

                if "image/jpeg" not in content_type.lower() or not image.startswith(b"\xff\xd8"):
                    continue

                self._snapshot_url = url
                return url, image

        return None

    async def test_connection(self) -> bool:
        """Test whether the camera is reachable via HTTP or RTSP.

        Some ShowMo/WinEye models redirect the HTTP root to a page that
        returns 404 (e.g. ``/index.asp``). Redirects are therefore not
        followed here: a 3xx from the root already proves the HTTP interface
        is alive. Cameras that expose no usable HTTP root but do stream over
        RTSP are accepted via an RTSP port reachability check, so the config
        flow does not reject an otherwise-working camera.
        """
        session = await self._ensure_session()
        auth = aiohttp.BasicAuth(self.username, self.password)

        for port in (8080, 80):
            try:
                async with session.get(
                    f"http://{self.host}:{port}/",
                    auth=auth,
                    allow_redirects=False,
                    timeout=aiohttp.ClientTimeout(total=5.0),
                ) as response:
                    if response.status in (200, 301, 302, 303, 401, 403):
                        return True
            except (TimeoutError, aiohttp.ClientError):
                continue

        return await check_rtsp(self.host, self.port or 554)
