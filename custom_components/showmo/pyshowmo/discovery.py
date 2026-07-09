"""Discovery helpers for ShowMo cameras."""

from __future__ import annotations

import asyncio
import socket
import time
import uuid

import aiohttp

from .constants import WS_DISCOVERY_MULTICAST_ADDR, WS_DISCOVERY_MULTICAST_PORT
from .exceptions import DiscoveryError
from .models import DiscoveredDevice
from .network import check_rtsp, get_local_subnet, iter_subnet_hosts
from .onvif import check_onvif, check_onvif_url, parse_ws_discovery_response
from .rtsp import build_default_rtsp_path, build_rtsp_url_without_credentials

WS_DISCOVERY_PROBE_MESSAGE = """<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing"
            xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
            xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
  <s:Header>
    <a:Action s:mustUnderstand="1">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</a:Action>
    <a:MessageID>uuid:{message_id}</a:MessageID>
    <a:ReplyTo>
      <a:Address>http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</a:Address>
    </a:ReplyTo>
    <a:To s:mustUnderstand="1">urn:schemas-xmlsoap-org:ws:2005:04:discovery</a:To>
  </s:Header>
  <s:Body>
    <d:Probe>
      <d:Types>dn:NetworkVideoTransmitter</d:Types>
    </d:Probe>
  </s:Body>
</s:Envelope>"""


def _ws_discover_sync(
    timeout: float = 5.0,
    local_ip: str | None = None,
) -> list[DiscoveredDevice]:
    """Send WS-Discovery probe and collect ProbeMatch responses."""
    message_id = str(uuid.uuid4())
    probe = WS_DISCOVERY_PROBE_MESSAGE.format(message_id=message_id).encode("utf-8")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)

        if local_ip:
            sock.setsockopt(
                socket.IPPROTO_IP,
                socket.IP_MULTICAST_IF,
                socket.inet_aton(local_ip),
            )
            sock.bind((local_ip, 0))
        else:
            sock.bind(("", 0))

        sock.sendto(
            probe,
            (WS_DISCOVERY_MULTICAST_ADDR, WS_DISCOVERY_MULTICAST_PORT),
        )

        deadline = time.monotonic() + timeout
        results: list[DiscoveredDevice] = []
        seen: set[tuple[str, str]] = set()

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break

            sock.settimeout(remaining)
            try:
                data, addr = sock.recvfrom(65535)
            except socket.timeout:
                break

            response_text = data.decode("utf-8", errors="ignore")
            matches = parse_ws_discovery_response(response_text, addr[0], addr[1])
            for match in matches:
                dedupe_key = (match.endpoint or "", match.onvif_url or "")
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                match.raw_response = response_text
                results.append(match)

        return results
    except OSError as err:
        raise DiscoveryError(str(err)) from err
    finally:
        sock.close()


async def ws_discover(
    timeout: float = 5.0,
    local_ip: str | None = None,
) -> list[DiscoveredDevice]:
    """Run WS-Discovery without blocking the event loop."""
    return await asyncio.to_thread(_ws_discover_sync, timeout, local_ip)


async def scan_network(
    subnet: str,
    max_concurrent: int = 50,
    username: str | None = None,
    password: str | None = None,
    rtsp_port: int = 554,
    onvif_ports: tuple[int, ...] = (8080, 80),
) -> list[DiscoveredDevice]:
    """Scan a subnet for RTSP/ONVIF devices."""
    semaphore = asyncio.Semaphore(max_concurrent)
    results: list[DiscoveredDevice] = []

    async with aiohttp.ClientSession() as session:
        async def scan_ip(ip: str) -> DiscoveredDevice | None:
            async with semaphore:
                if not await check_rtsp(ip, port=rtsp_port):
                    return None

                device = DiscoveredDevice(
                    ip=ip,
                    rtsp=True,
                    rtsp_port=rtsp_port,
                    suggested_rtsp_url=build_rtsp_url_without_credentials(
                        ip,
                        rtsp_port,
                        build_default_rtsp_path(),
                    ),
                )

                for onvif_port in onvif_ports:
                    onvif_result = await check_onvif(
                        session,
                        ip,
                        port=onvif_port,
                        username=username,
                        password=password,
                        timeout=2.0,
                    )
                    if onvif_result:
                        onvif_result.rtsp = True
                        onvif_result.rtsp_port = rtsp_port
                        onvif_result.suggested_rtsp_url = device.suggested_rtsp_url
                        onvif_result.discovery_method = "network-scan"
                        return onvif_result

                device.onvif = False
                device.discovery_method = "network-scan"
                return device

        tasks = [scan_ip(ip) for ip in iter_subnet_hosts(subnet)]
        for result in await asyncio.gather(*tasks):
            if result is not None:
                results.append(result)

    return results


async def discover_onvif_devices(
    timeout: float = 5.0,
    local_ip: str | None = None,
    username: str | None = None,
    password: str | None = None,
    session: aiohttp.ClientSession | None = None,
) -> list[DiscoveredDevice]:
    """Discover ONVIF devices via WS-Discovery and validate XAddrs."""
    matches = await ws_discover(timeout=timeout, local_ip=local_ip)
    if not matches:
        return []

    owns_session = session is None
    if session is None:
        session = aiohttp.ClientSession()

    try:
        results: list[DiscoveredDevice] = []
        for match in matches:
            verified = None
            if match.onvif_url:
                verified = await check_onvif_url(
                    session,
                    match.onvif_url,
                    username=username,
                    password=password,
                    timeout=timeout,
                )

            merged = verified or match
            merged.discovery_method = "ws-discovery"
            merged.onvif = True
            if merged.suggested_rtsp_url is None:
                merged.suggested_rtsp_url = build_rtsp_url_without_credentials(
                    merged.ip,
                    554,
                    build_default_rtsp_path(),
                )
            if verified is not None:
                merged.endpoint = match.endpoint
                merged.ws_port = match.ws_port
                merged.types = match.types
                merged.scopes = match.scopes
                merged.xaddrs = match.xaddrs
                merged.metadata_version = match.metadata_version
                merged.raw_response = match.raw_response
            results.append(merged)

        return results
    finally:
        if owns_session:
            await session.close()


async def discover_devices(
    timeout: float = 5.0,
    local_ip: str | None = None,
    subnet: str | None = None,
    username: str | None = None,
    password: str | None = None,
) -> list[DiscoveredDevice]:
    """Discover devices via WS-Discovery first, then network scan fallback."""
    discovered: list[DiscoveredDevice] = []
    # A single IP is one device on a LAN scan, so dedupe by IP alone. Keying on
    # serial too would split one camera into two entries when one discovery path
    # resolves its serial and the other does not (e.g. ws-discovery verification
    # times out but the network scan reads the serial number).
    seen: set[str] = set()

    try:
        ws_results = await discover_onvif_devices(
            timeout=timeout,
            local_ip=local_ip,
            username=username,
            password=password,
        )
    except DiscoveryError:
        ws_results = []

    for result in ws_results:
        seen.add(result.ip)
        discovered.append(result)

    effective_subnet = subnet or get_local_subnet(local_ip=local_ip)
    if not effective_subnet:
        return discovered

    scan_results = await scan_network(
        effective_subnet,
        username=username,
        password=password,
    )
    for result in scan_results:
        if result.ip in seen:
            continue
        seen.add(result.ip)
        discovered.append(result)

    return discovered
