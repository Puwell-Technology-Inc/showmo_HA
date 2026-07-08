from pyshowmo.discovery import discover_devices, discover_onvif_devices
from pyshowmo.models import DiscoveredDevice
from pyshowmo.onvif import check_onvif_url, parse_ws_discovery_response
import pytest

DEVICE_INFO_XML = """<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">
  <s:Body>
    <tds:GetDeviceInformationResponse xmlns:tds="http://www.onvif.org/ver10/device/wsdl">
      <tds:Manufacturer>puwell</tds:Manufacturer>
      <tds:Model>WIN2</tds:Model>
      <tds:SerialNumber>sn-1</tds:SerialNumber>
    </tds:GetDeviceInformationResponse>
  </s:Body>
</s:Envelope>"""


def _probe_match_xml(xaddrs: str) -> str:
    """Build a WS-Discovery ProbeMatch carrying the given XAddrs value."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
    xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing"
    xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery">
  <s:Body>
    <d:ProbeMatches>
      <d:ProbeMatch>
        <a:EndpointReference><a:Address>uuid:x</a:Address></a:EndpointReference>
        <d:Types>dn:NetworkVideoTransmitter</d:Types>
        <d:XAddrs>{xaddrs}</d:XAddrs>
      </d:ProbeMatch>
    </d:ProbeMatches>
  </s:Body>
</s:Envelope>"""


class _FakeResponse:
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self._body = body

    async def text(self) -> str:
        return self._body

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _RecordingSession:
    """Records each ONVIF POST and the auth it carried.

    ``responder`` maps a request URL to a callable ``(had_auth) -> _FakeResponse``
    so a test can model 401-then-authenticated flows and per-host behavior.
    """

    def __init__(self, responder) -> None:  # noqa: ANN001
        self._responder = responder
        self.requests: list[tuple[str, bool]] = []

    def post(self, url, data=None, auth=None, headers=None, timeout=None):  # noqa: ANN001
        del data, headers, timeout
        had_auth = auth is not None
        self.requests.append((url, had_auth))
        return self._responder(url, had_auth)

    async def close(self) -> None:
        return None

    @property
    def urls_with_auth(self) -> list[str]:
        return [url for url, had_auth in self.requests if had_auth]


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


def test_ws_discovery_pins_url_to_source_ip_when_xaddrs_spoofed() -> None:
    # A spoofed ProbeMatch points XAddrs at an attacker host (and even an
    # off-network URL). The parsed URL must be rebound to the UDP source IP.
    xml = _probe_match_xml(
        "http://10.0.0.9:8080/onvif/device_service http://evil.example.com/onvif/device_service"
    )
    matches = parse_ws_discovery_response(xml, "192.168.8.120", 3702)

    assert len(matches) == 1
    match = matches[0]
    assert match.ip == "192.168.8.120"
    # Port is taken from the advertised (http) XAddr, host is the source IP.
    assert match.onvif_url == "http://192.168.8.120:8080/onvif/device_service"


def test_ws_discovery_keeps_url_when_xaddrs_matches_source_ip() -> None:
    xml = _probe_match_xml("http://192.168.8.120:8080/onvif/device_service")
    matches = parse_ws_discovery_response(xml, "192.168.8.120", 3702)

    assert matches[0].onvif_url == "http://192.168.8.120:8080/onvif/device_service"
    assert matches[0].onvif_port == 8080


@pytest.mark.asyncio
async def test_spoofed_probematch_does_not_leak_credentials(monkeypatch):
    # WS-Discovery answered by an attacker whose XAddrs points at their own
    # host. The URL is rebound to the source IP, and the source IP answers
    # anonymously, so the camera credentials are never sent to any host.
    def responder(url, had_auth):  # noqa: ANN001
        return _FakeResponse(200, DEVICE_INFO_XML)

    session = _RecordingSession(responder)

    async def fake_ws_discover(**kwargs):
        xml = _probe_match_xml("http://10.0.0.9:8080/onvif/device_service")
        return parse_ws_discovery_response(xml, "192.168.8.120", 3702)

    monkeypatch.setattr("pyshowmo.discovery.ws_discover", fake_ws_discover)

    results = await discover_onvif_devices(
        username="admin",
        password="secret",
        session=session,
    )

    assert results
    # Every request went to the source IP, none to the attacker host.
    assert all("192.168.8.120" in url for url, _ in session.requests)
    assert not any("10.0.0.9" in url for url, _ in session.requests)
    # The endpoint answered anonymously (200), so credentials were never sent.
    assert session.urls_with_auth == []


@pytest.mark.asyncio
async def test_check_onvif_url_sends_no_auth_when_anonymous_succeeds():
    def responder(url, had_auth):  # noqa: ANN001
        return _FakeResponse(200, DEVICE_INFO_XML)

    session = _RecordingSession(responder)

    result = await check_onvif_url(
        session,
        "http://192.168.8.120:8080/onvif/device_service",
        username="admin",
        password="secret",
    )

    assert result is not None
    assert result.serial == "sn-1"
    assert session.urls_with_auth == []


@pytest.mark.asyncio
async def test_check_onvif_url_replays_credentials_on_401():
    # A real ONVIF endpoint challenges the anonymous probe with 401; only then
    # are credentials replayed, and only to that same (source-bound) host.
    def responder(url, had_auth):  # noqa: ANN001
        if had_auth:
            return _FakeResponse(200, DEVICE_INFO_XML)
        return _FakeResponse(401, "")

    session = _RecordingSession(responder)

    result = await check_onvif_url(
        session,
        "http://192.168.8.120:8080/onvif/device_service",
        username="admin",
        password="secret",
    )

    assert result is not None
    assert result.serial == "sn-1"
    # First request anonymous, second carried credentials to the same host.
    assert session.requests[0] == (
        "http://192.168.8.120:8080/onvif/device_service",
        False,
    )
    assert session.urls_with_auth == [
        "http://192.168.8.120:8080/onvif/device_service"
    ]


@pytest.mark.asyncio
async def test_scan_network_probes_anonymously_before_credentials(monkeypatch):
    # The subnet scan must probe each host anonymously first and only replay
    # credentials to hosts that answer 401 like a real ONVIF service, instead
    # of spraying the password across every host with an open RTSP port.
    from pyshowmo import discovery

    async def fake_check_rtsp(ip, port=554, timeout=1.0):  # noqa: ANN001
        return True

    monkeypatch.setattr(discovery, "check_rtsp", fake_check_rtsp)
    monkeypatch.setattr(
        discovery, "iter_subnet_hosts", lambda subnet: ["192.168.8.130"]
    )

    calls: list[tuple[str, bool]] = []

    async def fake_send_onvif_request(session, url, body, username=None, password=None, timeout=5.0, action=None):  # noqa: ANN001
        del session, body, action
        calls.append((url, bool(username or password)))
        # This host is not a real ONVIF service: it never returns 200/401 to
        # anonymous probes, so credentials must never be replayed.
        return 404, ""

    monkeypatch.setattr(
        "pyshowmo.onvif.send_onvif_request", fake_send_onvif_request
    )

    results = await discovery.scan_network(
        "192.168.8.0/24",
        username="admin",
        password="secret",
    )

    # RTSP host is still reported, but no credentialed probe was sent anywhere.
    assert [device.ip for device in results] == ["192.168.8.130"]
    assert calls  # anonymous probes did happen
    assert not any(had_auth for _, had_auth in calls)
