from pyshowmo.discovery import discover_devices
from pyshowmo.models import DiscoveredDevice
import pytest


@pytest.mark.asyncio
async def test_discover_devices_deduplicates(monkeypatch):
    async def fake_discover_onvif_devices(**kwargs):
        return [
            DiscoveredDevice(ip="192.168.8.120", serial="sn-1", onvif=True),
        ]

    async def fake_scan_network(*args, **kwargs):
        return [
            DiscoveredDevice(ip="192.168.8.120", serial="sn-1", onvif=True),
            DiscoveredDevice(ip="192.168.8.121", serial="sn-2", onvif=True),
        ]

    monkeypatch.setattr(
        "pyshowmo.discovery.discover_onvif_devices",
        fake_discover_onvif_devices,
    )
    monkeypatch.setattr("pyshowmo.discovery.scan_network", fake_scan_network)

    results = await discover_devices(subnet="192.168.8.0/24")

    assert [device.ip for device in results] == ["192.168.8.120", "192.168.8.121"]
