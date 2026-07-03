"""Data models for pyshowmo."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class DeviceInfo:
    """Normalized ONVIF device information."""

    manufacturer: str | None = None
    model: str | None = None
    firmware_version: str | None = None
    serial_number: str | None = None
    hardware_id: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        """Return a dict representation compatible with HA integration code."""
        return asdict(self)


@dataclass(slots=True)
class PullPointSubscription:
    """A normalized ONVIF PullPoint subscription."""

    address: str
    current_time: str | None = None
    termination_time: str | None = None


@dataclass(slots=True)
class OnvifNotification:
    """A normalized ONVIF event notification."""

    topic: str | None = None
    source_items: dict[str, str] = field(default_factory=dict)
    data_items: dict[str, str] = field(default_factory=dict)
    motion: bool | None = None


@dataclass(slots=True)
class DiscoveredDevice:
    """A device discovered via WS-Discovery or network scan."""

    ip: str
    onvif_url: str | None = None
    endpoint: str | None = None
    ws_port: int | None = None
    onvif_port: int | None = None
    status: int | None = None
    auth_required: bool = False
    onvif: bool = False
    rtsp: bool = False
    rtsp_port: int | None = None
    discovery_method: str | None = None
    suggested_rtsp_url: str | None = None
    types: list[str] = field(default_factory=list)
    scopes: list[str] = field(default_factory=list)
    xaddrs: list[str] = field(default_factory=list)
    metadata_version: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    serial: str | None = None
    firmware: str | None = None
    hardware_id: str | None = None
    device_info: DeviceInfo = field(default_factory=DeviceInfo)
    raw_response: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a dict representation compatible with HA integration code."""
        data = asdict(self)
        data["device_info"] = self.device_info.to_dict()
        return data
